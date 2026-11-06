# syntax=docker/dockerfile:1
# Kontekst to korzeń repozytorium (workspace uv): docker build -f chaos/Dockerfile .

FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv

FROM python:3.13.16-slim@sha256:cf50a4f6ac4f026458b08d5222023d700ac806410dff5e9ca8728fa44f2b850f AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
# Najpierw same zależności: ta warstwa zmienia się tylko razem z uv.lock.
COPY pyproject.toml uv.lock ./
# Każdy członek workspace'u z pyproject.toml w korzeniu, inaczej `uv sync --frozen` się przerywa.
COPY chaos/pyproject.toml chaos/
COPY libs/observability/pyproject.toml libs/observability/
COPY services/frontend/pyproject.toml services/frontend/
COPY services/orders/pyproject.toml services/orders/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace --package chaos
COPY chaos chaos
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package chaos

FROM python:3.13.16-slim@sha256:cf50a4f6ac4f026458b08d5222023d700ac806410dff5e9ca8728fa44f2b850f
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY --from=build /app/.venv /app/.venv
USER 10001:10001
# Kontener czeka; polecenia wydaje `kubectl exec ... -- fault-runner <polecenie>`.
CMD ["fault-runner", "idle"]
RUN false
