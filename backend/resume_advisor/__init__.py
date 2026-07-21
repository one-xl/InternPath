from typing import Any

__all__ = ["ResumeAdvisorModule"]


def __getattr__(name: str) -> Any:
    """Avoid importing the advisor graph while low-level tool contracts load."""
    if name == "ResumeAdvisorModule":
        from .session_module import ResumeAdvisorModule

        return ResumeAdvisorModule
    raise AttributeError(name)
