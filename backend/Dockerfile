# NetBuddy Backend — Multi-Stage-Build mit uv (gepinntes Python 3.12).
# Stage 1: Dependencies + Projekt in ein venv installieren. Stage 2: schlankes Runtime-Image.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

# Erst nur die Lock-Dateien → Layer-Cache für Dependencies, solange sich nichts ändert.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# Dann der Quellcode (inkl. profiles/, cli_templates/, data/oui.csv unter src/ — uv_build packt
# diese Paketdaten automatisch ins venv) und das Projekt selbst.
COPY . ./
RUN uv sync --frozen --no-dev


FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app
# Nicht-root Benutzer (read-only-Tool, aber Prinzip der geringsten Rechte).
RUN useradd --create-home --uid 10001 app

# Venv + Quellcode (für alembic.ini / alembic/ beim Entrypoint-Migrate).
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

COPY docker-entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

USER app
EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
# Default: API-Server. Der Worker überschreibt das CMD im Compose.
CMD ["uvicorn", "netbuddy.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
