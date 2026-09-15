# Deployment

The app is split so the **frontend can live on Vercel** and the **backend on AWS**.
The backend is HTTP-only: the browser connects directly to AssemblyAI's streaming
WebSocket, so no ingress WebSocket support is required on the backend host.

```
        Vercel (static UI)                    AWS (FastAPI backend)
   ┌────────────────────────┐          ┌───────────────────────────────┐
   │  index / capture / ask │          │  uvicorn app.main:app          │
   │  /static/*             │  /api/*  │  SQLite (data/knowledge.db)    │
   │                        │ ───────▶ │  AssemblyAI token + LLM calls  │
   └────────────────────────┘  rewrite └───────────────┬───────────────┘
                                                       │
                                       browser ──────▶ AssemblyAI streaming WS
```

## 1. Backend on AWS

Any persistent host works. The simplest is **Lightsail** (or EC2) running Docker.

```bash
# on the instance
git clone https://github.com/MarkNwilliam/galen && cd galen
cp .env.example .env      # add ASSEMBLYAI_API_KEY
docker build -t galen .
docker run -d --name galen -p 80:8000 --env-file .env galen
```

Open port 80 in the instance firewall. Verify:

```bash
curl http://<instance-ip>/health      # {"status":"ok","app":"galen",...}
```

The container seeds the demo dataset on first boot, so judges land on a populated
dashboard.

> **Serverless / scale-out note.** `agent/storage.py` is the single storage
> swap-point. Setting `STORAGE_BACKEND=dynamodb` is the intended path for
> Lambda/App Runner, where the filesystem is ephemeral. The demo ships with the
> SQLite backend for zero-config persistence on a single host.

## 2. Frontend on Vercel

1. Edit `vercel.json` and replace `REPLACE_WITH_BACKEND_HOST` with the backend
   host from step 1 (no scheme, e.g. `galen-backend.aws.example`).
2. Deploy:

```bash
vercel --prod
```

Vercel serves the static pages and proxies `/api/*` to the AWS backend, so the
browser sees same-origin requests and there are no CORS surprises.

Set `CORS_ORIGINS=https://<your-app>.vercel.app` on the backend to lock it down.

## Alternative: single host

For a one-click judge demo you can run everything on Replit (`.replit` is
included) or any Docker host; the UI is served by FastAPI directly at `/`.

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Environment variables

| Variable | Purpose |
| --- | --- |
| `ASSEMBLYAI_API_KEY` | **Required.** Realtime STT, batch STT, LLM Gateway. |
| `LLM_MODEL` | LLM Gateway model (account-dependent availability). |
| `STORAGE_BACKEND` | `sqlite` (default) or `dynamodb`. |
| `CORS_ORIGINS` | Comma-separated allowed origins for the API. |
| `HOST` / `PORT` | Bind address for uvicorn. |
| `AWS_*`, `DYNAMO_TABLE`, `S3_BUCKET` | For the DynamoDB/S3 prod path. |
