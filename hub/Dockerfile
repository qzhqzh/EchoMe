FROM python:3.11-slim

WORKDIR /app

# Install uv without keeping a compiler toolchain in the runtime image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Configure uv to use Tsinghua mirror
ENV UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# Copy project definition and install deps
COPY pyproject.toml .
RUN uv pip install --system .

# Copy application code
COPY . .

EXPOSE ${ECHOME_PORT:-20000}

CMD uvicorn app.main:app --host 0.0.0.0 --port ${ECHOME_PORT:-20000}
