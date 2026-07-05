from typing import Any
from database import Database

class HumanInteractionRequired(Exception):
    """
    当智能体运行过程中需要人类介入（Co-Pilot 模式交互）时抛出的自定义异常。
    """
    def __init__(self, question: str):
        self.question = question
        super().__init__(question)

def ask_human_question(task_id: str, user_id: Any, question: str, step_index: int | None = None) -> None:
    """
    挂起当前任务并将待提问的问题录入数据库，随后抛出 HumanInteractionRequired 异常中止当前执行流。

    Args:
        task_id (str): 任务 ID。
        user_id (Any): 用户 ID。
        question (str): 待人类解答的问题。
        step_index (int | None): 当前执行步骤，用于多轮对话追踪。

    Raises:
        HumanInteractionRequired: 总是抛出此异常以中止当前异步任务执行。
    """
    # 实例化数据库连接
    db = Database()

    # 更新任务状态为等待人类反馈，并写入提问内容
    db.update_agent_resume_task_status(
        task_id=task_id,
        user_id=user_id,
        status="WAITING_FOR_HUMAN",
        pending_question=question
    )
    try:
        db.add_agent_resume_turn(
            task_id=task_id,
            user_id=user_id,
            step_index=step_index,
            role="assistant",
            content=question,
        )
    except Exception as exc:
        print(f"[HITL] Failed to record assistant turn: {exc}")

    # 抛出异常挂起执行线程
    raise HumanInteractionRequired(question)
