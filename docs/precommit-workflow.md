# Pre-Commit Workflow (Local)

This repo enforces a heavy, **fully local** pre-commit pipeline. Every `git commit` runs a deterministic sequence of tasks to ensure the repository is consistent, tested, and ready to ship.

## Setup (One Time)

```bash
./scripts/setup_git_hooks.sh
```

This sets `core.hooksPath` to `.githooks/` so the pre-commit hook always runs.

## Versioning (Single Source of Truth)

- The canonical version lives in the root `VERSION` file.
- `scripts/sync_versions.py` ensures **all artifacts** use that version:
  - `backend/pyproject.toml`
  - `voltsnip-skill/SKILL.md` (frontmatter version)
  - `voltsnip-skill/package.json`
  - `.agent/skills/voltsnip/SKILL.md`

If any file is out of sync, it is updated **before** the rest of the pipeline continues.

## Pre-Commit Pipeline (Runs on Every Commit)

The hook executes `scripts/precommit.sh`, which performs the steps below **in order**:

1. **Tooling checks**
   - Ensures required tools are available locally: `git`, `python`, `uv`, `docker`, `node`, `npm`, `npx`, `curl`.

2. **Version sync**
   - Ensures all versioned files match `VERSION`.

3. **Backend tests**
   - Runs:
     ```bash
     ./scripts/ci_check.sh
     ```
   - Includes syntax check, Ruff, and pytest.

4. **OpenAPI spec generation**
   - Runs:
     ```bash
     uv run --project backend python scripts/generate_openapi.py
     ```
   - Writes spec to:
     - `voltsnip-skill/references/openapi-spec.json`

5. **Client generation (Python + TypeScript)**
   - Runs:
     ```bash
     ./scripts/generate_clients.sh
     ```
   - Internally calls `scripts/openapi-spec-generator.sh`.
   - Outputs generated clients to:
     - `clients/python`
     - `clients/npm`

6. **Skill package build**
   - Runs:
     ```bash
     ./scripts/build_skill_package.sh
     ```
   - Uses `npm pack` and writes the tarball to `dist/skills/`.

7. **Docker image build**
   - Runs:
     ```bash
     ./scripts/build_backend_image.sh
     ```
   - Builds backend image using `backend/Dockerfile`.

8. **Client tests**
   - Runs:
     ```bash
     ./scripts/test_clients.sh
     ```
   - Verifies:
     - Python client imports correctly.
     - TypeScript client packs into a tarball.

9. **Skill tests**
   - Runs:
     ```bash
     ./scripts/test_skill.sh
     ```
   - Verifies:
     - `SKILL.md` frontmatter required fields.
     - OpenAPI spec JSON is valid.
     - `voltsnip_client.py` exists.

10. **Docker run test**
    - Runs:
      ```bash
      ./scripts/test_docker_image.sh
      ```
    - Starts the built image, waits for `/health`, then shuts down.

11. **Stage generated artifacts**
    - The hook stages updated/generated files automatically:
      - `VERSION`
      - `backend/pyproject.toml`
      - `voltsnip-skill/SKILL.md`
      - `voltsnip-skill/package.json`
      - `voltsnip-skill/references/openapi-spec.json`
      - `clients/python`
      - `clients/npm`

If any step fails, the commit is blocked.

## Environment Variables

These allow you to tweak the workflow without editing scripts:

- `OPENAPI_SPEC_GENERATOR`: Path to your preferred OpenAPI generator CLI.
  - If unset, the scripts use `openapi-generator-cli` if installed, otherwise `npx @openapitools/openapi-generator-cli`.

- `IMAGE_NAME`, `IMAGE_TAG`: Override the Docker image name/tag used by build and test.

- `DATABASE_URL`: Used by the Docker run test. Defaults to:
  ```
  postgresql+asyncpg://postgres:postgres@host.docker.internal:5432/postgres
  ```

- `DOCKER_TEST_PORT`: Overrides the health check port (default `18000`).

## Notes

- The pipeline is intentionally heavy and **must pass** before any commit is accepted.
- Generated artifacts are staged so the commit stays consistent.
- Build artifacts are stored under `dist/` and are **gitignored**.
