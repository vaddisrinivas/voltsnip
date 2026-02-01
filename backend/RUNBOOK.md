# Runbook

Follow these steps to run the application without surprises.

### 0. Prerequisites
- Python 3.12+ (`python --version`)
- UV installed

### 1. Install Dependencies
```bash
uv sync
```

### 2. Database Setup
Start your Postgres server and create the database:
```bash
createdb moltsnip
```
*(Adjust command if using Docker or remote DB)*

### 3. Environment Configuration
Copy the example environment file:
```bash
cp .env.example .env
```
Ensure `.env` contains:
```ini
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/moltsnip
S3_MODE=local
STORAGE_URI=local_s3
CORS_ORIGINS="*"
```
*(Update `user:pass` to match your Postgres credentials)*
*(Set `S3_MODE=local` to avoid AWS requirements)*

### 4. Run Migrations
This applies the database schema:
```bash
uv run alembic upgrade head
```

### 5. Run Tests
Verify everything is working:
```bash
PYTHONPATH=. uv run pytest
```

### 6. Start Server
Run the FastAPI development server:
```bash
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 7. Sanity Check
Test the health endpoint:
```bash
curl http://localhost:8000/health
# Expected: {"status":"ok"}
```

## Infrastructure Requirements

### Database: PostgreSQL + pgvector
- **Extension**: `pgvector` must be installed.
- **Indexing**: We use `ivfflat` for vector indexing (requires `pgvector` extension). If you prefer `hnsw`, ensure your `pgvector` version is compatible.

## Common Issues

**Postgres Connection Errors**
- Check username/password in `DATABASE_URL`.
- Ensure DB `moltsnip` exists.
- Ensure Postgres is running on port 5432.

**Migration Failures**
- If `alembic` fails, ensure `psycopg` is installed (it should be in standard deps now).

**Embeddings**
- First run may take a moment to download the `fastembed` model.
