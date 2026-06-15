# Built on the shared Ajna Lambda base image (ajna-lambda-base) — the SDK + common deps are
# PREBAKED (ajna-cloud, fastapi, uvicorn, boto3, requests, python-jose, python-dotenv, uv). The
# build passes BASE_IMAGE = <this account's ECR>/ajna-lambda-base:<tag>; bumping that tag is the
# single SDK-version lever (no private CodeArtifact wheel download — the SDK travels in the image).
ARG BASE_IMAGE=public.ecr.aws/lambda/python:3.12-arm64
FROM ${BASE_IMAGE}

# App-specific dependencies only — ajna-cloud + the common libs are prebaked in the base image.
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN command -v uv >/dev/null 2>&1 || pip install --no-cache-dir uv
RUN uv pip install --system --no-cache -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Copy source code
COPY src/ ${LAMBDA_TASK_ROOT}/src/

CMD ["src.app.lambda_handler"]
