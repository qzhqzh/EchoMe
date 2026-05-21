FROM python:3.11-slim

WORKDIR /app

# Switch apt to Aliyun mirror
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources

# Install system deps for asyncpg and pgvector
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Switch pip to Tsinghua mirror and install uv
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip install --no-cache-dir uv

# Configure uv to use Tsinghua mirror
ENV UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# Copy project definition and install deps
COPY pyproject.toml .
RUN uv pip install --system .

# Copy application code
COPY . .

EXPOSE ${ECHOME_PORT:-20000}

CMD uvicorn app.main:app --host 0.0.0.0 --port ${ECHOME_PORT:-20000}
