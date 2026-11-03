# The API image: the trading_os package and api/ from this repo, run with uvicorn.
FROM python:3.12-slim

ARG GH_VERSION=2.63.2
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates curl \
 && curl -fsSL "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_amd64.tar.gz" \
    | tar -xz -C /tmp \
 && mv "/tmp/gh_${GH_VERSION}_linux_amd64/bin/gh" /usr/local/bin/gh \
 && rm -rf /tmp/gh_* /var/lib/apt/lists/* \
 && git config --system --add safe.directory /data
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --group api --no-install-project
COPY trading_os ./trading_os
COPY config ./config
COPY api ./api
COPY docs/GUIDE.md ./docs/GUIDE.md
RUN uv sync --frozen --no-dev --group api

RUN useradd --create-home --uid 1000 app
USER app
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
