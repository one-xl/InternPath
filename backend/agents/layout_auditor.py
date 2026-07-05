import os
import json
import base64
import asyncio
import logging
from typing import List, Dict, Any
from openai import OpenAI
from config import Config
from backend.agents.base import BaseAgent
from backend.agents.schemas import LayoutAuditOutput, parse_json_model

logger = logging.getLogger(__name__)

class LayoutAuditor(BaseAgent):
    """
    LayoutAuditor 是一个多模态智能体，继承自 BaseAgent。
    专门审计简历在视觉排版上是否存在格式问题（如：明显的重叠、空白页、字体崩塌、超出单页、行距太挤等）。
    强制使用多模态模型 Gemini 1.5 Flash。
    """
    def __init__(
        self,
        agent_id: str = "layout_auditor",
        role: str = "layout_auditor",
        model: str = "gemini-1.5-flash",
        openai_client: Any = None
    ):
        # 如果未提供 openai_client，使用配置好的 GEMINI_API_KEY 实例化 OpenAI 客户端
        if not openai_client:
            api_key = (Config.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY") or "").strip()
            if not api_key:
                api_key = "DUMMY_KEY"
            base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
            openai_client = OpenAI(
                api_key=api_key,
                base_url=base_url
            )
        super().__init__(agent_id=agent_id, role=role, model=model, openai_client=openai_client)

        self.system_prompt = (
            "你是一个大厂简历版面排版专家，专门审计生成的简历图片在视觉排版上是否存在格式问题。\n"
            "你需要检查排版是否整洁、是否有明显的重叠、空白页、字体崩塌、超出单页、行距太挤等视觉和排版格式问题。\n"
            "请对用户提供的简历页面图片进行全面的视觉审计。\n"
            "你必须严格返回一个符合以下结构的 JSON 格式字符串，不需要返回 markdown 格式块，直接返回 JSON 纯文本即可：\n"
            "{\n"
            "  \"score\": 95,\n"
            "  \"is_passed\": true,\n"
            "  \"issues\": [\"排版整洁，未发现跨页溢出。\"]\n"
            "}\n"
            "注意：\n"
            "1. 评分标准：满分 100 分。如果存在严重格式崩溃、文字重叠、明显的空白页、或者溢出单页等问题，得分必须低于 80 分，且 is_passed 应为 false。\n"
            "2. 你的输出结果必须是一个有效的 JSON 字符串，包含 score(int), is_passed(bool), issues(list of str) 三个字段。\n"
            "3. 回复中只包含 JSON 字符串本身，不要用 markdown 的 ```json 包裹。"
        )

    async def _call_llm_multimodal(self, system_prompt: str, content_list: List[Dict[str, Any]], temperature: float = 0.2) -> str:
        """
        支持多模态输入（文本 + 图片）的异步大模型调用。
        """
        if not self.openai_client:
            raise ValueError(f"Agent [{self.agent_id}] 未配置有效的 openai_client，无法调用大模型。")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content_list}
        ]

        try:
            # 封装为异步线程调用，避免阻塞事件循环
            response = await asyncio.to_thread(
                self.openai_client.chat.completions.create,
                model=self.model,
                messages=messages,
                temperature=temperature
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            raise RuntimeError(f"调用多模态大模型失败: {str(e)}") from e

    async def audit_layout(self, page_image_paths: List[str]) -> Dict[str, Any]:
        """
        使用 Gemini 1.5 Flash 对输入的简历页面图片列表进行排版审计。

        Args:
            page_image_paths (list[str]): 简历页面图片的绝对路径列表。

        Returns:
            dict: 结构化 JSON 结果，包含 score, is_passed, issues 字段。
        """
        if not page_image_paths:
            return {
                "score": 100,
                "is_passed": True,
                "issues": ["未提供页面图片，默认通过。"]
            }

        # 构造多模态请求的 user content
        content = [
            {
                "type": "text",
                "text": "请根据系统提示词，对以下简历页面图片进行视觉审计。请务必输出有效的 JSON 字符串。"
            }
        ]

        for path in page_image_paths:
            if not os.path.exists(path):
                logger.warning(f"审计图片路径不存在: {path}")
                continue
            try:
                with open(path, "rb") as image_file:
                    encoded_string = base64.b64encode(image_file.read()).decode("utf-8")
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{encoded_string}"
                    }
                })
            except Exception as e:
                logger.error(f"读取图片并转换为 base64 失败: {path}, 错误: {e}")

        try:
            raw_res = await self._call_llm_multimodal(self.system_prompt, content)

            # 清理可能被 markdown 代码块包裹的 JSON 字符串，清洗前后缀并去除空格以提升解析鲁棒性
            clean_res = raw_res.strip()
            if clean_res.startswith("```") or clean_res.endswith("```"):
                lines = clean_res.splitlines()
                if lines and lines[0].strip().startswith("```"):
                    lines.pop(0)
                if lines and lines[-1].strip().endswith("```"):
                    lines.pop()
                clean_res = "\n".join(lines).strip()

            return parse_json_model(clean_res, LayoutAuditOutput, "版面审计结果").model_dump()
        except Exception as e:
            logger.error(f"解析多模态版面审计结果失败: {e}")
            raise RuntimeError(f"多模态版面审计失败: {e}") from e
