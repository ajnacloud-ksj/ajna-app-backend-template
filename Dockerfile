FROM public.ecr.aws/lambda/python:3.12-arm64

# Install uv for fast package management
RUN pip install uv

# Copy SDK wheel (downloaded by CI) + requirements
COPY ajna_cloud-*.whl requirements.txt ${LAMBDA_TASK_ROOT}/

# Install dependencies
RUN uv pip install --system --no-cache ${LAMBDA_TASK_ROOT}/ajna_cloud-*.whl && \
    uv pip install --system --no-cache -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Copy source code
COPY src/ ${LAMBDA_TASK_ROOT}/src/

CMD ["src.app.lambda_handler"]
