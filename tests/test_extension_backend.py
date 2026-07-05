import json
import sys
import pytest
from pathlib import Path
from uuid import uuid4
from unittest.mock import MagicMock
from fastapi.testclient import TestClient

# Add backend directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from config import Config
from database import Database
from backend.main import create_app

TEST_DB_DIR = Path(__file__).resolve().parent.parent / ".test_dbs" / "extension_backend"


@pytest.fixture
def local_tmp_dir():
    path = TEST_DB_DIR / uuid4().hex
    path.mkdir(parents=True, exist_ok=True)
    yield path
    for candidate in sorted(path.rglob("*"), reverse=True):
        if candidate.is_file():
            candidate.unlink()
        else:
            candidate.rmdir()
    path.rmdir()


class MockChatCompletions:
    def __init__(self):
        pass

    def create(self, *args, **kwargs):
        data = {
            "self_evaluation": "这是一个针对岗位特别定制的自我评价文案。",
            "projects": "这是一个针对岗位重写优化的项目经历描述。"
        }
        mock_choice = MagicMock()
        mock_choice.message.content = json.dumps(data)
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response


@pytest.fixture
def test_env(local_tmp_dir, monkeypatch):
    db_path = str(local_tmp_dir / "career_path.db")
    monkeypatch.setattr(Config, "DB_PATH", db_path)
    monkeypatch.setattr(Config, "USER_DB_DIR", str(local_tmp_dir / "user_data"))
    monkeypatch.setattr(Config, "EMAIL_VERIFICATION_REQUIRED", False)

    # Instantiate DB
    test_db = Database(db_path)

    # Monkeypatch the module-level instances in background_analyzer
    from backend import background_analyzer
    monkeypatch.setattr(background_analyzer, "db", test_db)

    mock_analyzer = MagicMock()
    monkeypatch.setattr(background_analyzer, "analyzer", mock_analyzer)

    # Initialize app client
    app = create_app(auth_db=test_db)
    client = TestClient(app)

    return {
        "db": test_db,
        "analyzer": mock_analyzer,
        "client": client,
        "background_analyzer": background_analyzer
    }


def test_tailor_form_fields_api_success(test_env):
    db = test_env["db"]
    mock_analyzer = test_env["analyzer"]
    client = test_env["client"]

    # 1. Register a user and retrieve authorization token
    register_response = client.post(
        "/api/auth/register",
        json={"username": "test_ext@example.com", "password": "secure_password123"},
    )
    assert register_response.status_code == 200
    token = register_response.json()["token"]
    user_id = register_response.json()["user"]["id"]

    # 2. Save a mock parsed resume in DB with extracted profile details
    resume_file_id = "mock-resume-file-id"
    parsed_resume = {
        "file": {
            "name": "resume.pdf",
            "size": 1024,
            "type": "application/pdf"
        },
        "cleanedText": "Python developer. Graduate of Peking University.",
        "extractedProfile": {
            "name": "张三",
            "phone": "13800138000",
            "email": "zhangsan@example.com",
            "education": {
                "school": "北京大学",
                "major": "计算机科学与技术",
                "degree": "硕士"
            }
        },
        "chunks": [{"id": "chunk-1", "content": "Developer"}]
    }
    db.save_user_resume(
        user_id=user_id,
        resume_id=resume_file_id,
        file_name="resume.pdf",
        file_size=1024,
        file_type="application/pdf",
        parsed_resume=parsed_resume
    )

    # 3. Setup mock LLM chat completions
    mock_chat_client = MagicMock()
    mock_chat_client.chat = MagicMock()
    mock_chat_client.chat.completions = MockChatCompletions()

    mock_analyzer._client.return_value = (
        mock_chat_client,
        "resolved-chat-config-id",
        "mock-provider",
        "mock-model"
    )

    # 4. Trigger form tailoring API request
    payload = {
        "resume_file_id": resume_file_id,
        "jd_text": "Python Backend Engineer. Must be a graduate of top universities.",
        "fields": ["self_evaluation", "projects"]
    }
    response = client.post(
        "/api/analysis/tailor-form-fields",
        headers={"Authorization": f"Bearer {token}"},
        json=payload
    )

    # 5. Assertions
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True

    # Assert tailored AI strings
    tailored = body["tailored_data"]
    assert tailored["self_evaluation"] == "这是一个针对岗位特别定制的自我评价文案。"
    assert tailored["projects"] == "这是一个针对岗位重写优化的项目经历描述。"

    # Assert personal profile fields extracted correctly
    profile = body["profile"]
    assert profile["name"] == "张三"
    assert profile["phone"] == "13800138000"
    assert profile["email"] == "zhangsan@example.com"
    assert profile["school"] == "北京大学"
    assert profile["major"] == "计算机科学与技术"
    assert profile["degree"] == "硕士"


def test_tailor_form_fields_with_presets(test_env):
    db = test_env["db"]
    client = test_env["client"]

    # 1. Register a user and retrieve authorization token
    register_response = client.post(
        "/api/auth/register",
        json={"username": "test_ext_presets@example.com", "password": "secure_password123"},
    )
    assert register_response.status_code == 200
    token = register_response.json()["token"]
    user_id = register_response.json()["user"]["id"]

    # 2. Save a mock profile preset to user_settings
    presets = {
        "profile": {
            "name": "李四",  # Overrides resume
            "gender": "男",
            "birthDate": "2000-01-01",
            "politicalStatus": "中共党员",
            "hometown": "山东省",
            "expectedSalary": "15k",
            "wechat": "lisi_wechat",
            "gpa": "3.9/4.0",
            "education": "清华大学 软件工程 本科"  # Overrides resume edu string
        }
    }
    db.save_settings(user_id, presets)

    # 3. Save a mock parsed resume in DB with extracted profile details
    resume_file_id = "mock-resume-file-id-presets"
    parsed_resume = {
        "file": {
            "name": "resume.pdf",
            "size": 1024,
            "type": "application/pdf"
        },
        "cleanedText": "Python developer.",
        "extractedProfile": {
            "name": "张三",
            "phone": "13800138000",
            "email": "zhangsan@example.com",
            "education": {
                "school": "北京大学",
                "major": "计算机科学与技术",
                "degree": "硕士"
            }
        },
        "chunks": []
    }
    db.save_user_resume(
        user_id=user_id,
        resume_id=resume_file_id,
        file_name="resume.pdf",
        file_size=1024,
        file_type="application/pdf",
        parsed_resume=parsed_resume
    )

    # 4. Trigger form tailoring API request with no AI fields
    payload = {
        "resume_file_id": resume_file_id,
        "jd_text": "Python Backend Engineer.",
        "fields": []
    }
    response = client.post(
        "/api/analysis/tailor-form-fields",
        headers={"Authorization": f"Bearer {token}"},
        json=payload
    )

    # 5. Assertions
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True

    profile = body["profile"]
    # Check overrides
    assert profile["name"] == "李四"
    assert profile["school"] == "清华大学"
    assert profile["major"] == "软件工程"
    assert profile["degree"] == "本科"
    # Check presets
    assert profile["gender"] == "男"
    assert profile["birth_date"] == "2000-01-01"
    assert profile["political_status"] == "中共党员"
    assert profile["hometown"] == "山东省"
    assert profile["expected_salary"] == "15k"
    assert profile["wechat"] == "lisi_wechat"
    assert profile["gpa"] == "3.9/4.0"
    # Check fallback fields from resume
    assert profile["phone"] == "13800138000"
    assert profile["email"] == "zhangsan@example.com"

