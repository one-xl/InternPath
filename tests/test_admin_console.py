import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from backend.main import create_app
from config import Config
from database import Database
from models import JobAnalysis
from service import CareerPathAIService

class _FakeAnalyzer:
    def extract_skills(self, jd_text: str, *args, **kwargs) -> JobAnalysis:
        return JobAnalysis(
            skills=["Python", "FastAPI"],
            difficulty="中等",
            job_summary="后端实习岗位",
        )

class _FailingAiServiceClient:
    def analyze_jd(self, **kwargs):
        raise RuntimeError("ai-service unavailable in test")

def _make_app(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(Config, "USER_DB_DIR", str(tmp_path / "user_data"))
    monkeypatch.setattr(Config, "DB_PATH", str(tmp_path / "career_path.db"))
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)
    service = object.__new__(CareerPathAIService)
    service.ai_analyzer = _FakeAnalyzer()
    service.ai_service_client = _FailingAiServiceClient()
    db = Database(str(tmp_path / "auth.db"))
    app = create_app(service=service, auth_db=db)
    return TestClient(app), db

def _register(client: TestClient, username: str, password: str = "Password123!") -> str:
    resp = client.post("/api/auth/register", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]

def _login(client: TestClient, username: str, password: str = "Password123!") -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["token"]

def test_admin_console_flow(tmp_path, monkeypatch):
    client, db = _make_app(tmp_path, monkeypatch)
    
    # 1. Non-admin cannot access admin console APIs
    token_a = _register(client, "user_a@test.com")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    
    resp = client.get("/api/admin/users", headers=headers_a)
    assert resp.status_code == 403
    assert "权限不足" in resp.json()["detail"]
    
    # 2. Seed and login as admin, then access users list
    db.seed_db()
    token_admin = _login(client, "admin@example.com", "ChangeMe123!")
    headers_admin = {"Authorization": f"Bearer {token_admin}"}
    
    resp = client.get("/api/admin/users", headers=headers_admin)
    assert resp.status_code == 200
    users_list = resp.json()["users"]
    assert any(u["username"] == "user_a@test.com" for u in users_list)
    assert any(u["username"] == "admin@example.com" for u in users_list)

    # 3. Admin can create admin-managed config
    resp = client.post("/api/admin/model-configs", headers=headers_admin, json={
        "provider": "gemini",
        "modelId": "gemini-2.5-flash",
        "name": "Admin Gemini Config",
        "apiKey": "sk-admin-gemini-key-12345678",
        "enabled": True,
        "config_json": {"temperature": 0.5}
    })
    assert resp.status_code == 200
    admin_config_id = resp.json()["id"]

    # 4. Admin assigns configuration to User A
    resp = client.post(f"/api/admin/model-configs/{admin_config_id}/assign", headers=headers_admin, json={
        "userIds": [users_list[0]["id"]] # User A's ID
    })
    assert resp.status_code == 200

    # 5. User A lists configs. It must contain the admin assigned config
    resp = client.get("/api/configs", headers=headers_a)
    assert resp.status_code == 200
    user_a_configs = resp.json()["configs"]
    
    matching_config = next((c for c in user_a_configs if c["id"] == admin_config_id), None)
    assert matching_config is not None
    assert matching_config["source"] == "admin_assigned"
    assert matching_config["editable"] is False
    assert matching_config["apiKey"] == "服务器托管" # Decrypted key not returned

    # 6. User A cannot edit or delete this assigned config
    resp = client.post("/api/configs", headers=headers_a, json={
        "id": admin_config_id,
        "provider": "gemini",
        "modelId": "gemini-2.5-flash",
        "name": "User A trying to rename admin config",
        "apiKey": "",
        "enabled": True
    })
    assert resp.status_code == 403
    assert "无权修改管理员托管的配置" in resp.json()["detail"]

    resp = client.delete(f"/api/configs/{admin_config_id}", headers=headers_a)
    assert resp.status_code == 403
    assert "无权删除管理员托管的配置" in resp.json()["detail"]

    # 7. User A cannot see the raw API key
    assert "sk-admin" not in str(matching_config)

    # 8. User B cannot see the config assigned only to User A
    token_b = _register(client, "user_b@test.com")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    
    resp = client.get("/api/configs", headers=headers_b)
    assert resp.status_code == 200
    user_b_configs = resp.json()["configs"]
    assert not any(c["id"] == admin_config_id for c in user_b_configs)

    # 9. User A can use the config through backend resolution (e.g. test-connection)
    # We mock or test connection with resolved config. It should resolve key correctly.
    # We pass the configId in request to verify key resolution.
    resp = client.post("/api/models/test-connection", headers=headers_a, json={
        "provider": "gemini",
        "modelId": "gemini-2.5-flash",
        "type": "chat",
        "configId": admin_config_id
    })
    # Since we are using an invalid/mock api key (sk-admin-gemini-key-12345678), it will connect to Gemini and fail.
    # But it must try to connect and return Gemini failure (upstreamStatus != 200) instead of "No API Key found" (500)
    assert resp.status_code == 200
    assert resp.json()["ok"] is False
    assert "Gemini 连接失败" in resp.json()["message"] or "upstreamStatus" in resp.json()

    # 10. Normal user cannot assign config to anyone
    resp = client.post(f"/api/admin/model-configs/{admin_config_id}/assign", headers=headers_a, json={
        "userIds": [users_list[0]["id"]]
    })
    assert resp.status_code == 403

    # 11. Admin can revoke assignment
    resp = client.post(f"/api/admin/model-configs/{admin_config_id}/revoke", headers=headers_admin, json={
        "userIds": [users_list[0]["id"]]
    })
    assert resp.status_code == 200

    # 12. After revoke, User A can no longer see or use the config
    resp = client.get("/api/configs", headers=headers_a)
    assert resp.status_code == 200
    user_a_configs_after = resp.json()["configs"]
    assert not any(c["id"] == admin_config_id for c in user_a_configs_after)

    resp = client.post("/api/models/test-connection", headers=headers_a, json={
        "provider": "gemini",
        "modelId": "gemini-2.5-flash",
        "type": "chat",
        "configId": admin_config_id
    })
    # Since it is revoked, it won't resolve. It falls back to default env key or raises 500
    assert resp.status_code == 500 or (resp.status_code == 200 and resp.json()["ok"] is False and "未找到" in resp.json()["message"])

    # 13. Usage log is created for model call
    resp = client.get("/api/admin/model-usage/logs", headers=headers_admin)
    assert resp.status_code == 200
    logs_data = resp.json()
    assert logs_data["totalCount"] > 0
    test_log = logs_data["logs"][0]
    assert test_log["provider"] == "gemini"
    assert test_log["modelId"] == "gemini-2.5-flash"

    # 14. Admin can view usage summary
    resp = client.get("/api/admin/model-usage/summary", headers=headers_admin)
    assert resp.status_code == 200
    summary_data = resp.json()["summary"]
    assert summary_data["totalCalls"] > 0
    assert any(item["modelId"] == "gemini-2.5-flash" for item in summary_data["byModel"])

    # 15. Usage logs do not contain prompt/resume/JD/API key
    # Inspect schema columns to make sure they do not store sensitive text
    for log in logs_data["logs"]:
        assert "prompt" not in log
        assert "resume" not in log
        assert "jd" not in log
        assert "api_key" not in log
        assert "apiKey" not in log


def test_admin_temporary_and_lifecycle_management_flow(tmp_path, monkeypatch):
    client, db = _make_app(tmp_path, monkeypatch)
    db.seed_db()
    token_admin = _login(client, "admin@example.com", "ChangeMe123!")
    headers_admin = {"Authorization": f"Bearer {token_admin}"}

    # 1. Non-admin cannot generate temp users
    token_user = _register(client, "normal@user.com")
    headers_user = {"Authorization": f"Bearer {token_user}"}
    resp = client.post("/api/admin/users/generate-temp", headers=headers_user, json={"duration_hours": 12.0, "quantity": 2})
    assert resp.status_code == 403

    # 2. Admin can generate temp users
    resp = client.post("/api/admin/users/generate-temp", headers=headers_admin, json={"duration_hours": 1.0, "quantity": 2})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    accounts = data["generated_accounts"]
    assert len(accounts) == 2
    assert "@internpath.temp" in accounts[0]["username"]
    assert len(accounts[0]["password"]) >= 8

    # 3. Temp user can login successfully
    temp_email = accounts[0]["username"]
    temp_pass = accounts[0]["password"]
    temp_token = _login(client, temp_email, temp_pass)
    headers_temp = {"Authorization": f"Bearer {temp_token}"}

    # Verify temp user profile details
    resp = client.get("/api/me", headers=headers_temp)
    assert resp.status_code == 200
    profile = resp.json()
    assert profile["username"] == temp_email
    assert profile["is_active"] is True
    assert profile["expires_at"] is not None

    # Fetch User from db to get user_id
    user_in_db = db.get_user_by_username(temp_email)
    assert user_in_db is not None
    user_id = user_in_db.id

    # 4. Admin updates user expiry to a date in the past
    from datetime import datetime, timedelta
    past_expiry = (datetime.now() - timedelta(minutes=5)).isoformat()
    resp = client.patch(f"/api/admin/users/{user_id}/expiry", headers=headers_admin, json={"expires_at": past_expiry})
    assert resp.status_code == 200

    # 5. User tries to access api: self-healing check triggers, updates user status in DB, and throws 401
    resp = client.get("/api/me", headers=headers_temp)
    assert resp.status_code == 401
    assert "过期" in resp.json()["detail"] or "已停用" in resp.json()["detail"]

    # Verify user record is now is_active = False in database
    user_after = db.get_user_by_id(user_id)
    assert user_after.is_active is False

    # 6. Admin updates status to True and sets expiry to permanent (None)
    resp = client.patch(f"/api/admin/users/{user_id}/status", headers=headers_admin, json={"is_active": True})
    assert resp.status_code == 200
    resp = client.patch(f"/api/admin/users/{user_id}/expiry", headers=headers_admin, json={"expires_at": None})
    assert resp.status_code == 200

    # User can login again
    new_token = _login(client, temp_email, temp_pass)
    headers_new = {"Authorization": f"Bearer {new_token}"}
    resp = client.get("/api/me", headers=headers_new)
    assert resp.status_code == 200
    assert resp.json()["is_active"] is True
    assert resp.json()["expires_at"] is None

    # 7. Admin manually disables user
    resp = client.patch(f"/api/admin/users/{user_id}/status", headers=headers_admin, json={"is_active": False})
    assert resp.status_code == 200

    # User login or API request rejected
    resp = client.get("/api/me", headers=headers_new)
    assert resp.status_code == 401

    # 8. Admin cannot lock themselves out
    admin_user = db.get_user_by_username("admin@example.com")
    assert admin_user is not None
    resp = client.patch(f"/api/admin/users/{admin_user.id}/status", headers=headers_admin, json={"is_active": False})
    assert resp.status_code == 400
    assert "不能禁用/修改自己的" in resp.json()["detail"]

    resp = client.patch(f"/api/admin/users/{admin_user.id}/expiry", headers=headers_admin, json={"expires_at": past_expiry})
    assert resp.status_code == 400
    assert "不能修改自己的账户过期时间" in resp.json()["detail"]


def test_user_config_idor_prevention(tmp_path, monkeypatch):
    client, db = _make_app(tmp_path, monkeypatch)
    
    # 1. Register User A and User B
    token_a = _register(client, "user_a@test.com")
    headers_a = {"Authorization": f"Bearer {token_a}"}
    
    token_b = _register(client, "user_b@test.com")
    headers_b = {"Authorization": f"Bearer {token_b}"}
    
    # 2. User A creates a model config
    resp = client.post("/api/configs", headers=headers_a, json={
        "provider": "openai-compatible",
        "modelId": "gpt-4o",
        "name": "User A Private Config",
        "apiKey": "sk-user-a-secret-12345678",
        "enabled": True
    })
    assert resp.status_code == 200
    config_id = resp.json()["id"]
    
    # 3. User B tries to update User A's config (IDOR attack)
    resp = client.post("/api/configs", headers=headers_b, json={
        "id": config_id,
        "provider": "openai-compatible",
        "modelId": "gpt-4o",
        "name": "User B Hacked Name",
        "apiKey": "sk-user-b-evil-key",
        "enabled": False
    })
    assert resp.status_code == 403
    assert "无权修改其他用户的配置" in resp.json()["detail"]
    
    # 4. Verify User A's config is untouched
    resp = client.get("/api/configs", headers=headers_a)
    assert resp.status_code == 200
    user_a_configs = resp.json()["configs"]
    cfg = next(c for c in user_a_configs if c["id"] == config_id)
    assert cfg["name"] == "User A Private Config"
    assert cfg["enabled"] is True


