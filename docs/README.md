# gdev-agent MVP

Minimal FastAPI webhook agent skeleton for support triage.

## Structure

- `app/main.py` - FastAPI app and endpoints
- `app/schemas.py` - Pydantic request/response models
- `app/agent.py` - classify/extract/propose/approve/execute logic
- `app/tools/` - integration stubs
- `app/logging.py` - JSON structured logging
- `eval/` - tiny eval dataset and runner

## Endpoints

- `POST /webhook` - main entry for n8n/Make
- `POST /approve` - approve/reject pending action
- `GET /health` - healthcheck

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn pydantic pydantic-settings
uvicorn app.main:app --reload --port 8000
```

## Eval

```bash
python -m eval.runner
```

## Manual approval behavior

If request is risky (category/urgency/confidence/keyword checks), `/webhook` returns:

- `status: "pending"`
- `pending.pending_id`
- proposed action and draft response

Then call `/approve` with `pending_id` and `approved=true` to execute.
