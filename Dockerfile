# syntax=docker/dockerfile:1.7

FROM ghcr.io/astral-sh/uv:0.13.5 AS uv
FROM python:3.14-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app app \
    && mkdir -p /app /var/lib/stock-predictor \
    && chown -R 10001:10001 /app /var/lib/stock-predictor

WORKDIR /app
COPY --from=uv /uv /usr/local/bin/uv

# The production image is intentionally lockfile-gated. Generate and commit uv.lock before
# building a release image; see docs/operations/dependency-lock.md.
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
COPY src ./src

RUN uv sync --locked --no-dev --no-editable \
    && uv cache clean

USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["stock-predictor", "doctor"]
ENTRYPOINT ["stock-predictor"]
CMD ["doctor"]
