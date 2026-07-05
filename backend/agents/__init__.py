# 初始化 agents 模块
# 所有 agents 共享的包

from backend.agents.base import BaseAgent
from backend.agents.hr_critic import HRCritic
from backend.agents.job_decoder import JobDecoder
from backend.agents.resume_copywriter import ResumeCopywriter


def __getattr__(name: str):
    if name == "Orchestrator":
        from backend.agents.orchestrator import Orchestrator
        return Orchestrator
    raise AttributeError(name)

__all__ = [
    "BaseAgent",
    "HRCritic",
    "JobDecoder",
    "ResumeCopywriter",
    "Orchestrator"
]
