from __future__ import annotations

import copy
import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Literal

from backend.agents.base import BaseAgent
from backend.agents.tool_registry import AgentToolContext, AgentToolRegistry
from backend.agents.tools.hitl_tool import HumanInteractionRequired


ToolLoopStatus = Literal["completed", "needs_human", "failed", "max_turns"]
ModelTurn = Callable[[list[dict[str, str]]], str]
EventSink = Callable[[dict[str, Any]], None]


@dataclass
class ToolLoopResult:
    status: ToolLoopStatus
    final_text: str = ""
    turns: int = 0
    events: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""


@dataclass
class ResponsesJsonActionModelTurn:
    openai_client: Any
    model: str
    namespace: str = "agentic_tool_loop"
    temperature: float = 0.1
    extra_create_kwargs: dict[str, Any] = field(default_factory=dict)
    last_provider_usage: dict[str, Any] = field(default_factory=dict)
    deltas: list[str] = field(default_factory=list)
    stream_delta_sink: Callable[[str], None] | None = None

    def __call__(self, messages: list[dict[str, str]]) -> str:
        if not self.openai_client:
            raise ValueError("ResponsesJsonActionModelTurn requires an openai_client.")
        response_args = BaseAgent._messages_to_responses_args(messages)
        create_kwargs: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "input": response_args["input"],
        }
        if response_args["instructions"]:
            create_kwargs["instructions"] = response_args["instructions"]
        create_kwargs.update(self.extra_create_kwargs)
        BaseAgent._apply_responses_prompt_cache(
            create_kwargs,
            self.openai_client,
            model=self.model,
            namespace=self.namespace,
        )
        self.deltas = []
        self.last_provider_usage = {}

        def collect_delta(delta: str) -> None:
            self.deltas.append(delta)
            if self.stream_delta_sink:
                self.stream_delta_sink(delta)

        try:
            text = BaseAgent._collect_responses_stream_sync(
                self.openai_client,
                create_kwargs,
                on_delta=collect_delta,
                model=self.model,
                namespace=self.namespace,
            )
        finally:
            self.last_provider_usage = BaseAgent.pop_provider_cache_usage(self.openai_client)
        return text


@dataclass
class ResponsesNativeTurnResult:
    text: str = ""
    response: Any = None
    response_id: str = ""


@dataclass
class ResponsesNativeToolModelTurn:
    openai_client: Any
    model: str
    tools: list[dict[str, Any]]
    namespace: str = "agentic_resume_native_tools"
    temperature: float = 0.1
    extra_create_kwargs: dict[str, Any] = field(default_factory=dict)
    last_provider_usage: dict[str, Any] = field(default_factory=dict)
    deltas: list[str] = field(default_factory=list)

    def create(
        self,
        input_items: list[dict[str, Any]],
        *,
        instructions: str = "",
        previous_response_id: str = "",
        on_delta: Callable[[str], None] | None = None,
    ) -> ResponsesNativeTurnResult:
        if not self.openai_client:
            raise ValueError("ResponsesNativeToolModelTurn requires an openai_client.")
        create_kwargs: dict[str, Any] = {
            "model": self.model,
            "temperature": self.temperature,
            "input": input_items,
        }
        if instructions:
            create_kwargs["instructions"] = instructions
        if previous_response_id:
            create_kwargs["previous_response_id"] = previous_response_id
        if self.tools:
            create_kwargs["tools"] = self.tools
        create_kwargs.update(self.extra_create_kwargs)
        BaseAgent._apply_responses_prompt_cache(
            create_kwargs,
            self.openai_client,
            model=self.model,
            namespace=self.namespace,
        )
        self.deltas = []
        self.last_provider_usage = {}

        def collect_delta(delta: str) -> None:
            self.deltas.append(delta)
            if on_delta:
                on_delta(delta)

        try:
            result = BaseAgent._collect_responses_stream_result_sync(
                self.openai_client,
                create_kwargs,
                on_delta=collect_delta,
                model=self.model,
                namespace=self.namespace,
            )
        finally:
            self.last_provider_usage = BaseAgent.pop_provider_cache_usage(self.openai_client)

        response = result.get("response") if isinstance(result, dict) else None
        response_id = str(BaseAgent._get_attr_or_key(response, "id") or "")
        return ResponsesNativeTurnResult(
            text=str((result or {}).get("text") or ""),
            response=response,
            response_id=response_id,
        )


def _response_output_items(response: Any) -> list[Any]:
    output = BaseAgent._get_attr_or_key(response, "output") or []
    if isinstance(output, (list, tuple)):
        return list(output)
    return []


def _coerce_response_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        return item
    for method_name in ("model_dump", "to_dict", "dict"):
        method = getattr(item, method_name, None)
        if not callable(method):
            continue
        try:
            value = method(exclude_none=True)
        except TypeError:
            value = method()
        if isinstance(value, dict):
            return value
    result: dict[str, Any] = {}
    for key in ("id", "type", "status", "role", "content", "name", "arguments", "call_id"):
        value = BaseAgent._get_attr_or_key(item, key)
        if value is not None:
            result[key] = value
    return result


def _extract_native_function_calls(response: Any) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for item in _response_output_items(response):
        if BaseAgent._get_attr_or_key(item, "type") != "function_call":
            continue
        calls.append({
            "name": str(BaseAgent._get_attr_or_key(item, "name") or ""),
            "arguments": BaseAgent._get_attr_or_key(item, "arguments"),
            "call_id": str(
                BaseAgent._get_attr_or_key(item, "call_id")
                or BaseAgent._get_attr_or_key(item, "id")
                or ""
            ),
            "raw": _coerce_response_item(item),
        })
    return calls


def _parse_native_tool_arguments(raw_arguments: Any) -> dict[str, Any]:
    if raw_arguments in (None, ""):
        return {}
    if isinstance(raw_arguments, dict):
        return raw_arguments
    if isinstance(raw_arguments, str):
        parsed = json.loads(raw_arguments)
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("Native tool arguments must decode to a JSON object.")
    raise ValueError("Native tool arguments must be a JSON object string.")


def _function_call_output(call_id: str, tool_result: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": json.dumps(tool_result, ensure_ascii=False, default=str),
    }


def _retry_failure_tool(retry_failure_point: dict[str, Any] | None) -> tuple[str, dict[str, Any], int, int]:
    if not isinstance(retry_failure_point, dict):
        return "", {}, 0, 0
    tool_name = str(
        retry_failure_point.get("failed_tool_name")
        or retry_failure_point.get("tool_name")
        or retry_failure_point.get("toolName")
        or ""
    ).strip()
    raw_arguments = (
        retry_failure_point.get("failed_tool_arguments")
        if "failed_tool_arguments" in retry_failure_point
        else retry_failure_point.get("arguments")
    )
    arguments: dict[str, Any] = {}
    if isinstance(raw_arguments, dict):
        arguments = raw_arguments
    elif isinstance(raw_arguments, str) and raw_arguments.strip():
        try:
            parsed = json.loads(raw_arguments)
            if isinstance(parsed, dict):
                arguments = parsed
        except Exception:
            arguments = {}
    failed_sequence = int(retry_failure_point.get("failed_sequence") or retry_failure_point.get("sequence") or 0)
    retry_count = int(retry_failure_point.get("retry_count") or retry_failure_point.get("retryCount") or 0)
    return tool_name, arguments, failed_sequence, retry_count


def _coerce_dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [copy.deepcopy(item) for item in value if isinstance(item, dict)]


def _coerce_message_list(value: Any) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for item in _coerce_dict_list(value):
        role = str(item.get("role") or "").strip()
        content = item.get("content")
        if not role or content is None:
            continue
        messages.append({"role": role, "content": str(content)})
    return messages


def _retry_failed_model_input(retry_failure_point: dict[str, Any] | None, mode: str) -> dict[str, Any]:
    if not isinstance(retry_failure_point, dict):
        return {}
    raw_input = retry_failure_point.get("failed_model_input") or retry_failure_point.get("failedModelInput")
    if not isinstance(raw_input, dict):
        return {}
    if str(raw_input.get("mode") or "") != mode:
        return {}
    return copy.deepcopy(raw_input)


def _last_successful_tool_result(events: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(events):
        if event.get("type") == "tool_result" and event.get("ok"):
            return copy.deepcopy(event)
    return {}


def strip_json_fence(text: str) -> str:
    value = str(text or "").strip()
    if value.startswith("```"):
        fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```", value, flags=re.IGNORECASE | re.DOTALL)
        if fenced:
            return fenced.group(1).strip()
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    return value.strip()


def decode_json_action_object(text: str) -> dict[str, Any]:
    value = strip_json_fence(text)
    candidates = [value]
    first_brace = value.find("{")
    if first_brace > 0:
        candidates.append(value[first_brace:].strip())

    decoder = json.JSONDecoder()
    last_error: json.JSONDecodeError | None = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError as exc:
            last_error = exc
            try:
                parsed, _ = decoder.raw_decode(candidate)
            except json.JSONDecodeError as raw_exc:
                last_error = raw_exc
                continue
        if isinstance(parsed, dict):
            return parsed
        raise ValueError("Model JSON action must be an object.")
    if last_error is not None:
        raise ValueError(f"Model did not return valid JSON action: {last_error}") from last_error
    raise ValueError("Model did not return valid JSON action: empty response")


def parse_json_action(text: str) -> dict[str, Any]:
    parsed = decode_json_action_object(text)
    action = parsed.get("action")
    if action not in {"call_tool", "final_answer"}:
        raise ValueError("Model JSON action must be 'call_tool' or 'final_answer'.")
    return parsed


def _make_model_stream_delta_emitter(
    emit: Callable[[dict[str, Any]], None],
    *,
    turn: int,
    mode: str,
    min_chars: int = 1200,
    min_interval_seconds: float = 1.5,
) -> tuple[Callable[[str], None], Callable[[], None]]:
    state: dict[str, Any] = {
        "buffer": "",
        "total_chars": 0,
        "last_emit_at": 0.0,
        "emitted": False,
    }

    def publish(*, final: bool = False) -> None:
        buffer = str(state.get("buffer") or "")
        if not buffer:
            return
        emit({
            "type": "model_stream_delta",
            "turn": turn,
            "mode": mode,
            "content": buffer[-1200:],
            "total_chars": int(state.get("total_chars") or 0),
            "final": final,
        })
        state["buffer"] = ""
        state["last_emit_at"] = time.perf_counter()
        state["emitted"] = True

    def on_delta(delta: str) -> None:
        text = str(delta or "")
        if not text:
            return
        state["buffer"] = f"{state.get('buffer') or ''}{text}"
        state["total_chars"] = int(state.get("total_chars") or 0) + len(text)
        now = time.perf_counter()
        should_emit = (
            not state.get("emitted")
            or len(str(state.get("buffer") or "")) >= min_chars
            or (now - float(state.get("last_emit_at") or 0.0)) >= min_interval_seconds
        )
        if should_emit:
            publish()

    def flush() -> None:
        publish(final=True)

    return on_delta, flush


class AgenticToolLoop:
    def __init__(
        self,
        registry: AgentToolRegistry | None = None,
        *,
        max_turns: int = 12,
    ):
        self.registry = registry or AgentToolRegistry()
        self.max_turns = max(1, int(max_turns or 12))

    def build_system_prompt(self, *, is_co_pilot: bool = True) -> str:
        tools = self.registry.list_tools(is_co_pilot=is_co_pilot)
        tool_lines = []
        for tool in tools:
            tool_lines.append(f"- {tool.name}: {tool.description}")
        return (
            "You are the InternPath resume optimization agent. "
            "You must operate only by returning strict JSON actions. "
            "Use call_tool when you need project tools, and final_answer only when the resume artifacts are ready.\n\n"
            "Hard completion rules:\n"
            "- Never return a full rewritten resume directly as final_answer.\n"
            "- First inspect the workspace/bootstrap evidence, then call replace_resume_section for each concrete edit.\n"
            "- If the resume/JD does not support a factual claim, call ask_user_for_fact instead of inventing it.\n"
            "- Before final_answer, call generate_modification_diff and finalize_resume_artifacts.\n"
            "- final_answer is valid only after at least one successful replace_resume_section and one successful finalize_resume_artifacts.\n\n"
            "Allowed JSON shapes:\n"
            '{"action":"call_tool","tool":"tool_name","arguments":{}}\n'
            '{"action":"final_answer","content":"short completion summary"}\n\n'
            "Available tools:\n"
            + "\n".join(tool_lines)
        )

    def build_native_instructions(self, *, is_co_pilot: bool = True) -> str:
        tools = self.registry.list_tools(is_co_pilot=is_co_pilot)
        tool_lines = [f"- {tool.name}: {tool.description}" for tool in tools]
        return (
            "You are the InternPath resume optimization agent. "
            "Use the provided Responses function tools to inspect, rewrite, diff, and finalize resume artifacts. "
            "Do not invent facts. Preserve the original resume structure and only strengthen wording that is supported "
            "by the resume, JD, or confirmed user context. If a required fact is missing, call ask_user_for_fact. "
            "Never return a full rewritten resume directly as final text. You must call replace_resume_section for "
            "each concrete edit, then generate_modification_diff, then finalize_resume_artifacts. Return a concise "
            "final answer only after at least one replace_resume_section call and a successful finalize_resume_artifacts "
            "call. If no safe edit is possible, ask the user for missing facts instead of finalizing.\n\n"
            "Available tools:\n"
            + "\n".join(tool_lines)
        )

    @staticmethod
    def _requires_resume_artifacts(ctx: AgentToolContext) -> bool:
        return bool(str(ctx.resume_text or "").strip() and str(ctx.jd_text or "").strip())

    @staticmethod
    def _successful_tool_events(events: list[dict[str, Any]], tool_name: str) -> list[dict[str, Any]]:
        return [
            event
            for event in events
            if event.get("type") == "tool_result"
            and event.get("tool_name") == tool_name
            and bool(event.get("ok"))
        ]

    def _resume_artifacts_ready(self, events: list[dict[str, Any]], ctx: AgentToolContext) -> bool:
        if not self._requires_resume_artifacts(ctx):
            return True
        return bool(
            self._successful_tool_events(events, "replace_resume_section")
            and self._successful_tool_events(events, "finalize_resume_artifacts")
        )

    @staticmethod
    def _resume_artifacts_feedback(events: list[dict[str, Any]]) -> str:
        replaced = any(
            event.get("type") == "tool_result"
            and event.get("tool_name") == "replace_resume_section"
            and bool(event.get("ok"))
            for event in events
        )
        finalized = any(
            event.get("type") == "tool_result"
            and event.get("tool_name") == "finalize_resume_artifacts"
            and bool(event.get("ok"))
            for event in events
        )
        missing = []
        if not replaced:
            missing.append("a successful replace_resume_section call")
        if not finalized:
            missing.append("a successful finalize_resume_artifacts call")
        return (
            "The previous final answer was rejected because resume artifacts are not ready. "
            f"Missing: {', '.join(missing)}. "
            "Call the required tools with concrete, evidence-backed section edits. "
            "If evidence is insufficient, call ask_user_for_fact."
        )

    def _replay_retry_tool(
        self,
        ctx: AgentToolContext,
        retry_failure_point: dict[str, Any] | None,
        emit: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any] | None:
        tool_name, arguments, failed_sequence, retry_count = _retry_failure_tool(retry_failure_point)
        if not tool_name:
            return None
        retry_meta = {
            "retry": True,
            "retry_count": retry_count,
            "failed_sequence": failed_sequence,
        }
        emit({
            "type": "tool_call",
            "turn": 0,
            "tool_name": tool_name,
            "arguments": arguments,
            **retry_meta,
        })
        tool_result = self.registry.execute(tool_name, arguments, ctx)
        tool_result.update(retry_meta)
        emit({"type": "tool_result", "turn": 0, **tool_result})
        return {
            "tool_name": tool_name,
            "arguments": arguments,
            "tool_result": tool_result,
            **retry_meta,
        }

    def _run_json_bootstrap_tools(
        self,
        ctx: AgentToolContext,
        emit: Callable[[dict[str, Any]], None],
    ) -> list[dict[str, Any]]:
        bootstrap_calls: list[tuple[str, dict[str, Any]]] = [("list_workspace_files", {})]
        results: list[dict[str, Any]] = []
        workspace_files: set[str] = set()

        for index, (tool_name, arguments) in enumerate(bootstrap_calls, start=1):
            emit({
                "type": "tool_call",
                "turn": 0,
                "tool_name": tool_name,
                "arguments": arguments,
                "bootstrap": True,
                "bootstrap_index": index,
            })
            tool_result = self.registry.execute(tool_name, arguments, ctx)
            tool_result.update({"bootstrap": True, "bootstrap_index": index})
            emit({"type": "tool_result", "turn": 0, **tool_result})
            results.append({
                "tool_name": tool_name,
                "arguments": arguments,
                "tool_result": tool_result,
            })
            if tool_name == "list_workspace_files" and tool_result.get("ok"):
                data = ((tool_result.get("result") or {}).get("data") or {})
                workspace_files = {str(item) for item in data.get("files") or []}

        followup_calls: list[tuple[str, dict[str, Any]]] = []
        for filename in ("original_resume.txt", "job_description.txt"):
            if filename in workspace_files:
                followup_calls.append(("read_workspace_file", {"filename": filename}))
        followup_calls.append(("extract_resume_sections", {}))

        for offset, (tool_name, arguments) in enumerate(followup_calls, start=len(results) + 1):
            emit({
                "type": "tool_call",
                "turn": 0,
                "tool_name": tool_name,
                "arguments": arguments,
                "bootstrap": True,
                "bootstrap_index": offset,
            })
            tool_result = self.registry.execute(tool_name, arguments, ctx)
            tool_result.update({"bootstrap": True, "bootstrap_index": offset})
            emit({"type": "tool_result", "turn": 0, **tool_result})
            results.append({
                "tool_name": tool_name,
                "arguments": arguments,
                "tool_result": tool_result,
            })

        return results

    def _run_native_bootstrap_tools(
        self,
        ctx: AgentToolContext,
        emit: Callable[[dict[str, Any]], None],
    ) -> list[dict[str, Any]]:
        return self._run_json_bootstrap_tools(ctx, emit)

    def run_json_action_loop(
        self,
        ctx: AgentToolContext,
        model_turn: ModelTurn,
        *,
        event_sink: EventSink | None = None,
        retry_failure_point: dict[str, Any] | None = None,
    ) -> ToolLoopResult:
        events: list[dict[str, Any]] = []

        def emit(event: dict[str, Any]) -> None:
            events.append(event)
            if event_sink:
                event_sink(event)

        retry_model_input = _retry_failed_model_input(retry_failure_point, "json_action")
        retry_messages = _coerce_message_list(retry_model_input.get("messages")) if retry_model_input else []
        if retry_messages:
            messages = retry_messages
        else:
            messages: list[dict[str, str]] = [
                {"role": "system", "content": self.build_system_prompt(is_co_pilot=ctx.is_co_pilot)},
                {
                    "role": "user",
                    "content": (
                        "Optimize this resume for the target JD using the tools. "
                        "Do not invent facts. Ask the user if required facts are missing. "
                        "Before your first model turn, the runner will execute safe bootstrap tools so you can start "
                        "from live workspace evidence instead of rereading obvious files."
                        + (
                            "\n\n[Verified user answer]\n"
                            + ctx.human_context
                            + "\nUse this answer as confirmed evidence for the pending question."
                            if ctx.human_context
                            else ""
                        )
                    ),
                },
            ]
            retry_replay = self._replay_retry_tool(ctx, retry_failure_point, emit)
            if retry_replay:
                messages.append({
                    "role": "assistant",
                    "content": json.dumps({
                        "action": "call_tool",
                        "tool": retry_replay["tool_name"],
                        "arguments": retry_replay["arguments"],
                    }, ensure_ascii=False),
                })
                messages.append({
                    "role": "user",
                    "content": json.dumps({
                        "retry_tool_result": retry_replay,
                        "instruction": (
                            "This retry has replayed the same failed tool with the same arguments. "
                            "Continue from this result without restarting unrelated work."
                        ),
                    }, ensure_ascii=False, default=str),
                })
            elif not retry_failure_point:
                bootstrap_results = self._run_json_bootstrap_tools(ctx, emit)
                messages.append({
                    "role": "user",
                    "content": json.dumps({
                        "bootstrap_tool_results": bootstrap_results,
                        "instruction": (
                            "These safe bootstrap tools have already run before the first model turn. "
                            "Use their outputs as the current workspace evidence. Continue with the next necessary "
                            "tool call, ask for missing facts, or produce the final answer only after artifacts are ready."
                        ),
                    }, ensure_ascii=False, default=str),
                })

        for turn_index in range(1, self.max_turns + 1):
            emit({"type": "model_turn_start", "turn": turn_index})
            on_stream_delta, flush_stream_delta = _make_model_stream_delta_emitter(
                emit,
                turn=turn_index,
                mode="json_action",
            )
            previous_stream_sink = None
            can_set_stream_sink = hasattr(model_turn, "stream_delta_sink")
            try:
                if can_set_stream_sink:
                    previous_stream_sink = getattr(model_turn, "stream_delta_sink", None)
                    setattr(model_turn, "stream_delta_sink", on_stream_delta)
                raw_text = model_turn(copy.deepcopy(messages))
            except Exception as exc:
                error = str(exc)
                emit({
                    "type": "error",
                    "stage": "model_turn",
                    "turn": turn_index,
                    "error": error,
                    "retryable": True,
                    "failed_model_input": {
                        "mode": "json_action",
                        "messages": copy.deepcopy(messages),
                    },
                    "last_successful_tool_result": _last_successful_tool_result(events),
                })
                return ToolLoopResult(status="failed", turns=turn_index, events=events, error=error)
            finally:
                if can_set_stream_sink:
                    setattr(model_turn, "stream_delta_sink", previous_stream_sink)
                flush_stream_delta()
            emit({"type": "model_delta", "turn": turn_index, "content": raw_text})
            provider_usage = getattr(model_turn, "last_provider_usage", None)
            if isinstance(provider_usage, dict) and provider_usage:
                emit({"type": "provider_usage", "turn": turn_index, **provider_usage})
            try:
                action = parse_json_action(raw_text)
            except Exception as exc:
                error = str(exc)
                emit({"type": "error", "turn": turn_index, "error": error, "retryable": True})
                messages.append({"role": "assistant", "content": raw_text})
                messages.append({
                    "role": "user",
                    "content": (
                        "The previous response was not a valid JSON action. "
                        f"Error: {error}. Return only one valid JSON action."
                    ),
                })
                continue

            if action["action"] == "final_answer":
                final_text = str(action.get("content") or "")
                if not self._resume_artifacts_ready(events, ctx):
                    feedback = self._resume_artifacts_feedback(events)
                    emit({
                        "type": "error",
                        "turn": turn_index,
                        "error": feedback,
                        "retryable": True,
                    })
                    messages.append({"role": "assistant", "content": raw_text})
                    messages.append({"role": "user", "content": feedback})
                    continue
                emit({"type": "done", "turn": turn_index, "content": final_text})
                return ToolLoopResult(status="completed", final_text=final_text, turns=turn_index, events=events)

            tool_name = str(action.get("tool") or "").strip()
            arguments = action.get("arguments") or {}
            emit({"type": "tool_call", "turn": turn_index, "tool_name": tool_name, "arguments": arguments})
            try:
                tool_result = self.registry.execute(tool_name, arguments, ctx)
            except HumanInteractionRequired as exc:
                tool_result = {
                    "tool_name": tool_name,
                    "ok": True,
                    "result": {"status": "waiting_for_human"},
                    "error": "",
                    "duration_ms": 0,
                    "preview": str(exc),
                }
            emit({"type": "tool_result", "turn": turn_index, **tool_result})

            messages.append({"role": "assistant", "content": json.dumps(action, ensure_ascii=False)})
            messages.append({"role": "user", "content": json.dumps({
                "tool_name": tool_name,
                "tool_result": tool_result,
            }, ensure_ascii=False)})

            if tool_name == "ask_user_for_fact":
                question = str(arguments.get("question") or tool_result.get("preview") or tool_result.get("error") or "")
                return ToolLoopResult(
                    status="needs_human",
                    final_text=question,
                    turns=turn_index,
                    events=events,
                )

            if not tool_result.get("ok"):
                messages.append({
                    "role": "user",
                    "content": (
                        "The tool call failed. You may retry with corrected arguments, "
                        "call another tool, or ask the user if factual input is needed."
                    ),
                })

        emit({"type": "error", "turn": self.max_turns, "error": "Agentic tool loop exceeded max_turns.", "retryable": True})
        return ToolLoopResult(status="max_turns", turns=self.max_turns, events=events, error="max_turns exceeded")

    def run_native_responses_loop(
        self,
        ctx: AgentToolContext,
        model_turn: ResponsesNativeToolModelTurn,
        *,
        event_sink: EventSink | None = None,
        retry_failure_point: dict[str, Any] | None = None,
    ) -> ToolLoopResult:
        events: list[dict[str, Any]] = []

        def emit(event: dict[str, Any]) -> None:
            event.setdefault("mode", "native_responses")
            events.append(event)
            if event_sink:
                event_sink(event)

        instructions = self.build_native_instructions(is_co_pilot=ctx.is_co_pilot)
        retry_model_input = _retry_failed_model_input(retry_failure_point, "native_responses")
        retry_input_items = _coerce_dict_list(retry_model_input.get("input_items")) if retry_model_input else []
        if retry_input_items:
            instructions = str(retry_model_input.get("instructions") or instructions)
            input_items = retry_input_items
            manual_context_items = list(retry_input_items)
            previous_response_id = str(retry_model_input.get("previous_response_id") or "")
        else:
            bootstrap_results = self._run_native_bootstrap_tools(ctx, emit) if not retry_failure_point else []
            initial_input: list[dict[str, Any]] = [
                {
                    "role": "user",
                    "content": (
                        "Optimize this resume for the target JD using the provided function tools. "
                        "Do not invent facts. Ask the user if required facts are missing.\n\n"
                        f"[Resume]\n{ctx.resume_text}\n\n[JD]\n{ctx.jd_text}"
                        + (
                            "\n\n[Verified user answer]\n"
                            + ctx.human_context
                            + "\nUse this answer as confirmed evidence for the pending question."
                            if ctx.human_context
                            else ""
                        )
                    ),
                }
            ]
            retry_replay = self._replay_retry_tool(ctx, retry_failure_point, emit)
            if retry_replay:
                initial_input.append({
                    "role": "user",
                    "content": (
                        "Retry context: the same failed tool has just been replayed with the same arguments. "
                        "Continue from this result without restarting unrelated work.\n"
                        + json.dumps({"retry_tool_result": retry_replay}, ensure_ascii=False, default=str)
                    ),
                })
            elif bootstrap_results:
                initial_input.append({
                    "role": "user",
                    "content": json.dumps({
                        "bootstrap_tool_results": bootstrap_results,
                        "instruction": (
                            "These safe bootstrap tools have already prepared live workspace evidence. "
                            "Use the extracted sections to call replace_resume_section with precise edits. "
                            "Do not return the rewritten resume as final text."
                        ),
                    }, ensure_ascii=False, default=str),
                })
            input_items = list(initial_input)
            manual_context_items = list(initial_input)
            previous_response_id = ""

        for turn_index in range(1, self.max_turns + 1):
            emit({"type": "model_turn_start", "turn": turn_index})
            on_stream_delta, flush_stream_delta = _make_model_stream_delta_emitter(
                emit,
                turn=turn_index,
                mode="native_responses",
            )
            try:
                result = model_turn.create(
                    input_items,
                    instructions=instructions,
                    previous_response_id=previous_response_id,
                    on_delta=on_stream_delta,
                )
            except Exception as exc:
                error = str(exc)
                emit({
                    "type": "error",
                    "stage": "model_turn",
                    "turn": turn_index,
                    "error": error,
                    "retryable": True,
                    "failed_model_input": {
                        "mode": "native_responses",
                        "input_items": copy.deepcopy(input_items),
                        "instructions": instructions,
                        "previous_response_id": previous_response_id,
                    },
                    "last_successful_tool_result": _last_successful_tool_result(events),
                })
                return ToolLoopResult(status="failed", turns=turn_index, events=events, error=error)
            finally:
                flush_stream_delta()
            if result.text:
                emit({"type": "model_delta", "turn": turn_index, "content": result.text})
            provider_usage = getattr(model_turn, "last_provider_usage", None)
            if isinstance(provider_usage, dict) and provider_usage:
                emit({"type": "provider_usage", "turn": turn_index, **provider_usage})

            function_calls = _extract_native_function_calls(result.response)
            if not function_calls:
                final_text = str(result.text or "")
                if final_text:
                    if not self._resume_artifacts_ready(events, ctx):
                        feedback = self._resume_artifacts_feedback(events)
                        emit({"type": "error", "turn": turn_index, "error": feedback, "retryable": True})
                        feedback_item = {"role": "user", "content": feedback}
                        if result.response_id:
                            previous_response_id = result.response_id
                            input_items = [feedback_item]
                        else:
                            manual_context_items.extend(
                                _coerce_response_item(item)
                                for item in _response_output_items(result.response)
                            )
                            manual_context_items.append(feedback_item)
                            input_items = list(manual_context_items)
                        continue
                    emit({"type": "done", "turn": turn_index, "content": final_text})
                    return ToolLoopResult(status="completed", final_text=final_text, turns=turn_index, events=events)

                error = "Native Responses turn produced neither final text nor function calls."
                emit({"type": "error", "turn": turn_index, "error": error, "retryable": True})
                feedback = {"role": "user", "content": "Return a final answer or call one available function tool."}
                if result.response_id:
                    previous_response_id = result.response_id
                    input_items = [feedback]
                else:
                    manual_context_items.extend(_coerce_response_item(item) for item in _response_output_items(result.response))
                    manual_context_items.append(feedback)
                    input_items = list(manual_context_items)
                continue

            tool_outputs: list[dict[str, Any]] = []
            for function_call in function_calls:
                tool_name = str(function_call.get("name") or "").strip()
                call_id = str(function_call.get("call_id") or "").strip()
                raw_arguments = function_call.get("arguments")
                if not call_id:
                    error = f"Native function call for tool '{tool_name}' did not include call_id."
                    emit({"type": "error", "turn": turn_index, "error": error, "retryable": False})
                    return ToolLoopResult(status="failed", turns=turn_index, events=events, error=error)

                try:
                    arguments = _parse_native_tool_arguments(raw_arguments)
                except Exception as exc:
                    arguments = {}
                    tool_result = {
                        "tool_name": tool_name,
                        "ok": False,
                        "result": None,
                        "error": str(exc),
                        "duration_ms": 0,
                        "preview": str(exc),
                        "read_only": False,
                        "requires_confirmation": False,
                    }
                    emit({
                        "type": "tool_call",
                        "turn": turn_index,
                        "tool_name": tool_name,
                        "arguments": raw_arguments,
                        "call_id": call_id,
                    })
                    emit({"type": "tool_result", "turn": turn_index, **tool_result})
                    tool_outputs.append(_function_call_output(call_id, tool_result))
                    continue

                emit({
                    "type": "tool_call",
                    "turn": turn_index,
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "call_id": call_id,
                })
                try:
                    tool_result = self.registry.execute(tool_name, arguments, ctx)
                except Exception as exc:
                    tool_result = {
                        "tool_name": tool_name,
                        "ok": False,
                        "result": None,
                        "error": str(exc),
                        "duration_ms": 0,
                        "preview": str(exc),
                        "read_only": False,
                        "requires_confirmation": False,
                    }
                emit({"type": "tool_result", "turn": turn_index, **tool_result})
                tool_outputs.append(_function_call_output(call_id, tool_result))

                if tool_name == "ask_user_for_fact":
                    question = str(arguments.get("question") or tool_result.get("preview") or tool_result.get("error") or "")
                    return ToolLoopResult(
                        status="needs_human",
                        final_text=question,
                        turns=turn_index,
                        events=events,
                    )

            if result.response_id:
                previous_response_id = result.response_id
                input_items = tool_outputs
            else:
                manual_context_items.extend(_coerce_response_item(item) for item in _response_output_items(result.response))
                manual_context_items.extend(tool_outputs)
                input_items = list(manual_context_items)

        emit({"type": "error", "turn": self.max_turns, "error": "Agentic tool loop exceeded max_turns.", "retryable": True})
        return ToolLoopResult(status="max_turns", turns=self.max_turns, events=events, error="max_turns exceeded")
