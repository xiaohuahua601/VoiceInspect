# VoiceInspect Internal Pilot Runbook

## Start

1. Copy `.env.example` to `.env` and replace `ACCESS_TOKEN_SECRET` and demo passwords.
2. Start Ollama on the host and verify the configured LLM, embedding model, and optional vision model.
3. Apply migrations and start the services:

```powershell
.\.venv\Scripts\alembic.exe upgrade head
docker compose up -d --build api web
docker compose up -d worker
```

Worker and API use the same `voiceinspect-api` image and the shared `data/` volume. The API accepts requests; the Worker consumes diagnosis and report jobs.

## Health checks

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/v1/health/live
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/v1/health
docker compose ps
docker compose logs --tail 100 api worker
```

`/health.worker.available` is based on the heartbeat file in the shared volume. Missing model capabilities degrade only the affected task and are shown in the UI.

## Job troubleshooting

Diagnosis and report endpoints return `job_id`. Use `GET /api/v1/jobs/{job_id}` to inspect status; failed jobs can be retried and running jobs can be cancelled. Stage events are persisted so a disconnected client can resume through the session events endpoint.

If a job stays in `running`, inspect Worker logs and `data/logs/worker-heartbeat.json`. A lease older than five minutes is recovered to `queued`; restart the Worker if it is not consuming jobs.

## Backup and restore

Stop API and Worker before backing up these paths:

- `data/db/voiceinspect.db`
- `data/uploads/`
- `data/knowledge/`
- `data/qdrant/`
- `data/logs/`
- `data/exports/`

```powershell
docker compose stop api worker
.\.venv\Scripts\python.exe scripts/backup_data.py
.\.venv\Scripts\python.exe scripts/restore_data.py data/backups/<backup-directory> --confirm
.\.venv\Scripts\alembic.exe upgrade head
docker compose up -d api worker
```

After restore, check database integrity, `/health/live`, `/health`, a knowledge citation, and one text diagnosis job. `.env`, model weights, and real credentials are not backup deliverables.

## Boundary

This release targets an internal Windows Docker pilot. It does not claim field diagnostic accuracy, enterprise SSO, CMMS/MES/ERP integration, or multi-node high availability. Before field rollout, add vendor manuals, field image/audio evaluation, access review, and a restore drill.
