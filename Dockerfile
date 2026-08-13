# check=skip=InvalidDefaultArgInFrom
# ^ BASE_IMAGE is intentionally defaulted-less (see below); this silences the lint that
#   would otherwise warn on every legitimate build.
# Built on the shared Ajna Lambda base image (ajna-lambda-base) — the SDK + common deps are
# PREBAKED (ajna-cloud, fastapi, uvicorn, boto3, requests, python-jose, python-dotenv, uv). The
# build passes BASE_IMAGE = <this account's ECR>/ajna-lambda-base:<tag>; bumping that tag is the
# single SDK-version lever (no private CodeArtifact wheel download — the SDK travels in the image).
#
# MULTI-STAGE — one Dockerfile serves both local dev and prod (no Dockerfile.local):
#   - deploy (CodeBuild): `docker build .`  → default = LAST stage (`prod`) = Lambda.
#   - local  (compose):   build.target: dev → uvicorn hot-reload, src/ bind-mounted.
# BASE_IMAGE is injected by the build: CodeBuild passes this account's ECR ref; local
# docker-compose.local.yml passes the ghcr mirror. Same image + tag → dev == prod SDK.
# Deliberately NO default. A fallback to public.ecr.aws/lambda/python here is worse than a
# broken build: it silently produces an off-base image that reinstalls the whole SDK stack, so
# the app's ECR repo stores a full private copy of every layer instead of sharing the base —
# and since ECR deduplicates only within a repository, that copy is billed and pulled forever.
# An unset BASE_IMAGE must fail loudly ("base name should not be blank") so the build gets fixed.
ARG BASE_IMAGE

# ── base: shared SDK (from ajna-lambda-base) + app-specific deps ──────────────
FROM ${BASE_IMAGE} AS base

# App-specific dependencies only — ajna-cloud + the common libs are prebaked in the base image.
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN command -v uv >/dev/null 2>&1 || pip install --no-cache-dir uv
RUN uv pip install --system --no-cache -r ${LAMBDA_TASK_ROOT}/requirements.txt

# ── dev: local hot-reload. src/ + local_dev.py are bind-mounted by
#    docker-compose.local.yml (not COPY'd), so edits reload with no rebuild.
#    Selected via `--target dev`. Never deployed.
FROM base AS dev
ENTRYPOINT []
CMD ["python", "-m", "uvicorn", "local_dev:app", "--host", "0.0.0.0", "--port", "8000", "--reload", "--reload-dir", "/var/task/src"]

# ── prod: AWS Lambda. LAST stage, so the deploy build (no --target) picks it by
#    default → the buildspec needs no change. ─────────────────────────────────
FROM base AS prod

# Copy source code
COPY src/ ${LAMBDA_TASK_ROOT}/src/

CMD ["src.app.lambda_handler"]
