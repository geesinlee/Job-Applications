# Production Storage Setup

## Source of truth

- PostgreSQL is canonical for applications, stages, history, follow-ups,
  profile data, and CV metadata.
- `tracker.json`, `profile.json`, and `cv_records.json` are development or
  migration/recovery formats only.
- Application artefacts and interview notes live on a tenant-owned persistent
  filesystem volume outside Git.

## Required environment

```dotenv
JOB_APP_STORAGE_BACKEND=postgres
DATABASE_URL=postgresql://job_app:<PASSWORD>@<POSTGRES_HOST>:5432/job_applications
JOB_APP_BASE_DIR=/path/to/persistent/data
JOB_APP_ARTEFACTS_DIR=/path/to/persistent/data
JOB_APP_BASE_CV_PATH=/path/to/persistent/data/base_cv/Reference_CV.md
```

Run the Prisma migrations under `prisma/migrations/` before starting the MCP
service. Store the environment file outside the checkout and restrict its file
permissions.

## Verification

```bash
.venv/bin/python -m pytest -q test_mcp_server.py
```

Then start the service and call `list_applications`. A new deployment should
return an empty result until tenant-owned data is explicitly imported or
created through owner tools.
