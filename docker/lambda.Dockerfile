# One image for every pipeline Lambda; Terraform selects the handler per function via
# image_config.command (e.g. apple_supply_chain.lambdas.handlers.build_silver).
# Built (not pushed) in CI as a smoke test; pushed to ECR only by deploy.yml via OIDC.
FROM public.ecr.aws/lambda/python:3.12-arm64

COPY --from=ghcr.io/astral-sh/uv:0.10.2 /uv /usr/local/bin/uv

WORKDIR ${LAMBDA_TASK_ROOT}
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
# Install the locked runtime dependencies (no dev/athena groups) into the task root.
RUN uv export --frozen --no-dev --no-emit-project --format requirements-txt > /tmp/requirements.txt \
 && uv pip install --system --no-cache --target "${LAMBDA_TASK_ROOT}" -r /tmp/requirements.txt \
 && uv pip install --system --no-cache --no-deps --target "${LAMBDA_TASK_ROOT}" . \
 && rm -rf /root/.cache

COPY dbt ./dbt
ENV ASC_DBT_DIR=/var/task/dbt \
    ASC_DATA_DIR=/tmp/asc \
    DBT_TARGET=dev \
    DBT_LOG_PATH=/tmp/asc/dbt-logs \
    DBT_TARGET_PATH=/tmp/asc/dbt-target \
    ASC_LOG_FORMAT=json

CMD ["apple_supply_chain.lambdas.handlers.extract_sec_edgar"]
