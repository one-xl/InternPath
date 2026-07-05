import asyncio
from abc import ABC, abstractmethod
from typing import Any, Optional, List, Dict

class BaseAgent(ABC):
    """
    智能体（Agent）的抽象基类，定义了通用的初始化接口、上下文重置以及 LLM 调用方法。
    """
    def __init__(
        self,
        agent_id: str,
        role: str,
        model: str,
        openai_client: Optional[Any] = None
    ):
        """
        初始化 BaseAgent 实例。

        Args:
            agent_id (str): 智能体的唯一标识。
            role (str): 智能体的角色名称（如 'hr_critic'）。
            model (str): 所使用的大模型名称（如 'gpt-4o-mini' 或 'deepseek-chat'）。
            openai_client (Any, optional): 传入的 OpenAI 客户端实例。
        """
        self.agent_id = agent_id
        self.role = role
        self.model = model
        self.openai_client = openai_client
        self.system_prompt = ""
        self.context: List[Dict[str, str]] = []

    def reset_context(self, user_id: str, query: str) -> None:
        """
        重置智能体的历史上下文，只保留初始 System Prompt。
        具备明确简历段落语义的 Agent 会自行从 PostgreSQL PreferenceDB 注入偏好规则。

        Args:
            user_id (str): 用户唯一标识。
            query (str): 当前用户的输入查询。
        """
        few_shot_rules: List[str] = []

        # 拼接 System Prompt 与 Few-shot 偏好规则
        full_system_prompt = self.system_prompt
        if few_shot_rules:
            rules_str = "\n".join(few_shot_rules)
            full_system_prompt += f"\n\n[用户偏好规则与 Few-shot 示例]\n{rules_str}"

        self.context = [
            {"role": "system", "content": full_system_prompt}
        ]

    async def _call_llm(self, system_prompt: str, user_prompt: str, temperature: float = 0.3) -> str:
        """
        统一的异步 LLM 调用底层方法，支持包装同步的 openai_client 以防阻塞事件循环。

        Args:
            system_prompt (str): 系统提示词。
            user_prompt (str): 用户提示词。
            temperature (float): 采样温度，默认为 0.3。

        Returns:
            str: 大模型返回的文本内容。
        """
        if not self.openai_client:
            raise ValueError(f"Agent [{self.agent_id}] 未配置有效的 openai_client，无法调用大模型。")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        try:
            # 使用 asyncio.to_thread 进行异步封装，避免同步的 chat.completions.create 阻塞主事件循环
            response = await asyncio.to_thread(
                self.openai_client.chat.completions.create,
                model=self.model,
                messages=messages,
                temperature=temperature
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            # 向上层抛出异常，供主工作流捕获并记录日志
            raise RuntimeError(f"调用大模型失败: {str(e)}") from e
