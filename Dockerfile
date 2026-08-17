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

# ── deps: resolve app requirements with uv, in a stage that is THROWN AWAY ────
# `${BASE_IMAGE}-build` is the base's build tag: identical contents plus the uv binary. No extra
# build-arg is needed — BASE_IMAGE ends in the tag, so the suffix lands on the tag.
#
# uv is a 47.6 MiB static Rust binary and it is BUILD tooling: it installs requirements.txt and
# is then never used again. It used to live in the base's runtime layer, so it shipped to
# production in every Lambda image and could not be removed downstream (deleting a file from a
# parent layer only writes a whiteout — the bytes still ship). Resolving deps here and copying
# only the result forward is what keeps it out. See ajna-cloud-sdk#248.
FROM ${BASE_IMAGE}-build AS deps

# App-specific dependencies only — ajna-cloud + the common libs are prebaked in the base image.
#
# --target, NOT --system: this installs ONLY what requirements.txt adds. Copying the whole
# site-packages forward instead DUPLICATES the base's ~118MB copy, because the parent layer still
# ships — measured on the first app to try it, that produced a LARGER image than the one it
# replaced. Copying just the delta is the entire point.
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN uv pip install --target /app-deps --no-cache -r ${LAMBDA_TASK_ROOT}/requirements.txt

# ── base: shared SDK (from ajna-lambda-base) + the app deps resolved above ────
FROM ${BASE_IMAGE} AS base
COPY --from=deps /app-deps /app-deps
# The base sets PYTHONPATH=/var/task; extend it rather than replace it.
#
# Everything on PYTHONPATH precedes site-packages in sys.path, so /app-deps SHADOWS the base for
# any package present in both. That is the desired direction — an app that pins a dependency
# should get its pin — but it differs from the old `uv pip install --system`, which merged into
# the base's site-packages and left an already-satisfied requirement alone. An app pinning
# something OLDER than the base now actually gets the older version, so keep requirements.txt to
# genuine app-specific deps.
ENV PYTHONPATH=/var/task:/app-deps

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
