# Local Windows Run

This mode starts the React workbench, FastAPI backend, and optional ai-service on the same machine.

## 1. Configure `.env`

Create the project root `.env` and set:

- `LLM_API_KEY`
- `LLM_BASE_URL`
- `LLM_MODEL`
- Optional `LLM_TIMEOUT`
- Optional `PRACTICE_APP_PATH`

Example:

```env
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
AI_SERVICE_BASE_URL=http://127.0.0.1:8000
PRACTICE_APP_PATH=C:\Path\To\AiSmartDrill.App.exe
```

## 2. Install frontend dependencies

```powershell
cd frontend
npm install
cd ..
```

## 3. Start the app

```powershell
.\start_internpath.cmd
```

Stop local services:

```powershell
.\stop_internpath.cmd
```

Restart local services:

```powershell
.\restart_internpath.cmd
```

Default URLs:

- React workbench: `http://127.0.0.1:5173`
- FastAPI backend: `http://127.0.0.1:8787`
- ai-service: `http://127.0.0.1:8000`

## 4. Optional port override

```powershell
$env:INTERNPATH_WEB_PORT=5174
$env:INTERNPATH_BACKEND_PORT=8788
.\deploy\run_local.ps1
```
