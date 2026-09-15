# AGENTS.md

Working notes so any opencode session can pick up where the last one left off.

## Project

**Galen** — voice knowledge bank for pharmaceutical manufacturing. Built for the
**AssemblyAI Voice Agent Hackathon** (lablab.ai). Submission deadline:
**Sep 30, 2026 6:00 PM EAT**.

- Live demo: https://galen-kb.vercel.app
- Repo (public): https://github.com/MarkNwilliam/galen

## First actions every session

1. `python -m pytest` (11 tests, must pass).
2. Read `memory.md` — it holds ALL project details AND secrets (AWS, AssemblyAI,
   Vercel token, URLs, deploy commands, caveats). Never paste secrets into chat
   or files unnecessarily, and NEVER commit `memory.md` (it is gitignored).
3. Read `docs/DEPLOYMENT.md`, `docs/SUBMISSION.md`, `docs/RECORDING.md` while
   relevant to the task — they encode the live architecture and the video script.
4. Verify the backend is alive before making claims you did not test:
   `curl https://3strtwnmd0.execute-api.us-east-1.amazonaws.com/prod/health`.

## Current handoff status

DONE (do not redo without reason):
- Backend live: AWS Lambda `galen-backend` + API Gateway `galen-api` (id
  `3strtwnmd0`, stage `prod`) + DynamoDB `galen-kb`. All API flows verified.
- Frontend live: Vercel, project `ui` (public), alias **galen-kb.vercel.app**
  points at the current deployment. Frontend calls the backend directly via
  `ui/static/config.js` (CORS `*`) — Vercel external rewrites do not forward
  POST bodies.
- GitHub pushed: latest commit is safe to assume (`main`).
- Docs: `docs/RECORDING.md`, `docs/DEPLOYMENT.md`, `docs/SUBMISSION.md`,
  `docs/slides/galen-slides.pdf` (8 slides 16:9), `docs/cover.png`.
- Slides are committed.

REMAINING (what a new session should continue):
1. **Rotate AssemblyAI API key** (current key is in `memory.md`, rotation
   pending). User rotates in the AssemblyAI dashboard → update `.env` →
   `python -m scripts.deploy_aws` to refresh the Lambda env var.
2. **Record the ~4-min demo video** per `docs/RECORDING.md` (the USER records;
   the assistant writes/tunes the script only).
3. **Submit on lablab.ai** before the deadline: repo, demo URL
   https://galen-kb.vercel.app, video MP4 ≤100 MB, cover `docs/cover.png`,
   slides `docs/slides/galen-slides.pdf`. Description/tags in
   `docs/SUBMISSION.md`.

## Conventions

- Tooling: Python 3.11 (locally via pyenv 3.9.7 in use for tests), pytest.
- Storage abstraction lives in `agent/repo.py` (SQLite local, DynamoDB prod,
  switched by `STORAGE_BACKEND`).
- LLM calls go through AssemblyAI LLM Gateway, model `qwen3.5-4b-32k-fast`
  (prompt-JSON + `json-repair`, no `response_format`).
- Deploy commands (from repo root):
  - `python -m scripts.build_lambda` then `python -m scripts.deploy_aws`
  - `./scripts/deploy_vercel.sh` (deploy + make public + re-alias)
- `.env`, `memory.md`, `galen_lambda.zip`, `data/`, `ui/.vercel` are gitignored.
  This repo is PUBLIC — never commit keys.
- Verify changes with `python -m pytest` and, when touching deployment, a live
  curl of the affected endpoint.

## Known pitfalls (see memory.md for full list)

- `galen.vercel.app` is owned elsewhere — never use it.
- AWS Function URLs are blocked at the account level → API Gateway.
- Fresh Vercel projects default to SSO-protected deployments → patch
  `ssoProtection: null` after each deploy.
- Root `vercel.json` with FastAPI in requirements.txt trips Vercel "services"
  detection → keep `ui/vercel.json` (no framework key).
- `vercel git connect` fails (no GitHub app) → CLI uploads + `--name` only.