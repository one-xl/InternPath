from database import Database
from backend.resume_advisor.repository import ResumeAdvisorRepository


def test_global_fact_can_be_revoked_and_no_longer_appears_in_session_memory(tmp_path):
    db = Database(str(tmp_path / "memory.db"))
    user_id = db.create_user("memory@example.com", "password123")
    repository = ResumeAdvisorRepository(db)
    session = repository.create_session(
        user_id=user_id,
        resume_id="resume-1",
        resume_content_hash="a" * 64,
        jd_text="需要 Redis",
    )
    fact_id = repository.record_fact(
        user_id=user_id,
        session_id=session["id"],
        claim_key="redis",
        claim_value="使用 Redis 缓存热点查询。",
        source_type="user_message",
        source_id="turn-1",
        status="confirmed",
        scope="global",
    )

    assert repository.list_global_facts(user_id)[0]["id"] == fact_id
    assert any(item["id"] == fact_id for item in repository.list_confirmed_facts(user_id, session["id"]))

    assert repository.revoke_global_fact(user_id=user_id, fact_id=fact_id) is True
    assert repository.list_global_facts(user_id) == []
    assert all(item["id"] != fact_id for item in repository.list_confirmed_facts(user_id, session["id"]))
