# InternPath

InternPath is a Streamlit-based JD analysis tool for internship and job preparation. It extracts skills from a job description with an LLM, recommends matching Bilibili courses, stores analysis history, and can generate launch payloads for a local AiSmartDrill client.

## Features

- Analyze a JD and extract skills, difficulty, and a short summary
- Save analysis history and rename records
- Create a new draft analysis before saving it to history
- Search and rank Bilibili courses for the extracted skills
- Persist records locally with SQLite
- Generate `aismartdrill://` launch links or local skill package files
- Protect the web UI with a configured password

## Stack

- Python
- Streamlit
- OpenAI-compatible SDK
- HTTPX
- Pydantic v2
- SQLite

## Project Structure

```text
app.py                  Streamlit UI
service.py              Application service layer
ai_analyzer.py          LLM-based JD analysis
crawler_api.py          Bilibili course search
ranker.py               Course ranking logic
database.py             SQLite persistence
models.py               Pydantic models
practice_app.py         AiSmartDrill payload/export helpers
config.py               Environment-driven configuration
deploy/                 Local and server deployment helpers
```

## Requirements

- Python 3.9+
- An LLM API key compatible with the configured `LLM_BASE_URL`

## Quick Start

1. Install dependencies.

```bash
pip install -r requirements.txt
```

2. Create `.env` from the example and fill in your own values.

```bash
cp .env.example .env
```

Example:

```env
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
APP_PASSWORD=change_me
PRACTICE_APP_PATH=C:\Path\To\AiSmartDrill.App.exe
```

3. Run the app.

```bash
streamlit run app.py
```

Default local URL:

`http://127.0.0.1:8501`

## Configuration

Key environment variables:

- `LLM_API_KEY`: required
- `LLM_BASE_URL`: optional, defaults to `https://api.deepseek.com`
- `LLM_MODEL`: optional, defaults to `deepseek-chat`
- `LLM_TIMEOUT`: optional, request timeout in seconds
- `APP_PASSWORD`: plain-text login password for development or private deployments
- `APP_PASSWORD_HASH`: PBKDF2 hash for safer deployments
- `PRACTICE_APP_PATH`: local Windows path to the AiSmartDrill executable

If both `APP_PASSWORD` and `APP_PASSWORD_HASH` are empty, login will not succeed until one of them is configured.

## Running Modes

### Local Windows

Use the helper script:

```powershell
.\deploy\run_local.ps1
```

See [deploy/LOCAL_WINDOWS.md](deploy/LOCAL_WINDOWS.md) for details.

### Linux / Debian Server

Use `requirements.server.txt` and `deploy/server_install.sh`.

See [deploy/DEPLOY_DEBIAN.md](deploy/DEPLOY_DEBIAN.md) for a generic deployment flow.

## Tests

Available tests in this repository currently cover parts of the API integration and skill package generation:

```bash
pytest
```

## Privacy and Repository Hygiene

This repository is intended to stay safe for public hosting:

- `.env` is ignored
- SQLite databases are ignored
- local editor settings such as `.vscode/` are ignored
- deployment scripts no longer contain a fixed server address
- example files use placeholder API keys, passwords, and executable paths

Before pushing your own changes, confirm that no real API keys, passwords, private hostnames, or local user paths were added to tracked files.
