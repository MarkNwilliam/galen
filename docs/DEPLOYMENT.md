# Deployment

Galen runs live **today**:

- Frontend (Vercel, public): **https://galen-kb.vercel.app**
- Backend (AWS API Gateway + Lambda + DynamoDB):
  https://3strtwnmd0.execute-api.us-east-1.amazonaws.com/prod
  (`GET /health` → `{"status":"ok","app":"galen","storage":"dynamodb"}`)

The app is split so the **frontend lives on Vercel** and the **backend on AWS**.
The backend is HTTP-only: the browser connects directly to AssemblyAI's streaming
WebSocket, so no ingress WebSocket support is required on the backend host.

```
        Vercel (static UI)                    AWS (Lambda + API Gateway)
   ┌────────────────────────┐          ┌───────────────────────────────┐
   │  index / capture / ask │          │  app.main via Mangum           │
   │  /static/*  config.js  │          │  DynamoDB (table galen-kb)     │
   │                        │  direct  │  AssemblyAI token + LLM calls  │
   │  ──────────────────────┼─────────▶   (CORS "*", no rewrite)       │
   └────────────────────────┘          └───────────────┬───────────────┘
        browser ─────────────────────────────────────▶ AssemblyAI streaming WS
```

The frontend calls `window.GALEN_API_BASE` (set in `ui/static/config.js`) straight
to the API Gateway URL. There is **no server-side rewrite of POST bodies**, so the
UI never depends on Vercel proxying `/api`; it talks to the backend directly and
relies on the backend's `CORS_ORIGINS=*` (browser preflight is handled by FastAPI's
CORSMiddleware).

## 1. Backend on AWS (as deployed)

Serverless Lambda + API Gateway + DynamoDB — no always-on host, no EC2.

```bash
pip install -r requirements.txt
python -m scripts.build_lambda        # -> galen_lambda.zip (manylinux wheels)
python -m scripts.deploy_aws          # S3 relay -> Lambda -> API Gateway
```

`scripts/deploy_aws.py` creates/updates:

- Lambda `galen-backend` (python3.11, handler `app.lambda_handler.handler`,
  60s timeout, 1024 MB) with env `STORAGE_BACKEND=dynamodb`,
  `DYNAMO_TABLE=galen-kb`, `ASSEMBLYAI_API_KEY`, `LLM_MODEL`, `CORS_ORIGINS=*`.
- DynamoDB table `galen-kb` (single-table: `pk`/`sk`, seeded via
  `DYNAMO_TABLE=galen-kb python -m scripts.seed_demo`).
- REST API Gateway `galen-api` with a `{proxy+}` ANY route on the prod stage.

Local dev keeps the SQLite backend: `STORAGE_BACKEND` is the single swap point in
`agent/repo.py` (both a SQLite and a DynamoDB backend implement the same API).

## 2. Frontend on Vercel

```bash
./scripts/deploy_vercel.sh
```

That script:

1. Uploads the `ui/` directory with `vercel --prod` (project name `galen-app`).
2. PATCHes `ssoProtection: null` on the project — Vercel defaults every fresh
   project to SSO-protected deployments, which otherwise hides the site behind a
   "Redirecting..." login wall.
3. Points the stable alias `galen-kb.vercel.app` at the new deployment.

`ui/vercel.json` only uses `cleanUrls`; it contains no `framework` key and no
rewrite, because a root `vercel.json` with `"framework":"other"` plus a detected
FastAPI dependency triggers Vercel's "services" conflict error. Keep the config
inside `ui/`, and deploy with `--name` so the project identity stays
deterministic.

## Alternative: single host / local

For a one-click judge demo or local dev you can run everything on Replit
(`.replit` is included) or any Docker host; FastAPI serves the UI directly,
and `ui/static/config.js` falls back to same-origin when `GALEN_API_BASE` is set
to the backend.

```bash
STORAGE_BACKEND=sqlite uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

## Environment variables

| Variable | Purpose |
| --- | --- |
| `ASSEMBLYAI_API_KEY` | **Required.** Realtime STT, batch STT, LLM Gateway. |
| `LLM_MODEL` | LLM Gateway model (account-dependent availability). |
| `STORAGE_BACKEND` | `sqlite` (default local) or `dynamodb` (Lambda). |
| `DYNAMO_TABLE` | DynamoDB table name (`galen-kb`). |
| `CORS_ORIGINS` | Comma-separated allowed origins (`*` on the live backend). |
| `HOST` / `PORT` | Bind address for uvicorn. |
| `AWS_*`, `S3_BUCKET` | Credentials + relay bucket for `scripts/deploy_aws.py`. |