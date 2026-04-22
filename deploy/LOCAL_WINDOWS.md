# Local Windows Run

This mode keeps the desktop integration available on the same machine.

## 1. Configure `.env`

Create the project root `.env` and set:

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`
- Optional `LLM_TIMEOUT`
- `APP_PASSWORD` or `APP_PASSWORD_HASH`
- Optional `PRACTICE_APP_PATH`

Example:

```env
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
APP_PASSWORD=change_me
PRACTICE_APP_PATH=C:\Path\To\AiSmartDrill.App.exe
```

## 2. Start the app

```powershell
.\deploy\run_local.ps1
```

Default URL:

`http://127.0.0.1:8501`

## 3. Optional port override

```powershell
$env:LOCAL_PORT=8503
.\deploy\run_local.ps1
```
