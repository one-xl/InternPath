# InternPath AI Service

This service provides the first-stage RAG retrieval, evidence verification, and hallucination-control APIs used by InternPath.

## Install

```powershell
cd C:\Users\a1028\Desktop\vibecoding\实习通\InternPath\ai-service
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Copy `.env.example` to `.env` if you want to configure LLM settings. The first-stage implementation defaults to BM25 and does not require FAISS or sentence-transformers.

## Run

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Expected response:

```json
{
  "status": "ok",
  "service": "internpath-ai-service"
}
```

## APIs

- `GET /health`
- `POST /ai/rag/search`
- `POST /ai/verify-report`
- `POST /ai/analyze-jd`

## Tests

```powershell
python -m pytest tests -q
```
