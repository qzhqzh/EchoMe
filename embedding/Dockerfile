FROM python:3.11-slim

WORKDIR /app

# Switch apt to Aliyun mirror
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ git \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Configure uv to use Tsinghua PyPI mirror
ENV UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# Copy project files
COPY pyproject.toml .
COPY server.py .
COPY download_model.py .

# Install dependencies via uv
RUN uv sync

# Download model from ModelScope at build time (so container starts fast)
ENV MODEL_DIR=/app/models
RUN uv run python download_model.py

EXPOSE 20002

CMD ["uv", "run", "python", "server.py"]
