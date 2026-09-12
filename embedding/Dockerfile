FROM python:3.11-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Configure uv to use Tsinghua PyPI mirror
ENV UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# Copy project files
COPY pyproject.toml .
COPY uv.lock .
COPY server.py .

# Install dependencies via uv
RUN uv sync --frozen --no-dev

EXPOSE 20002

CMD ["uv", "run", "--frozen", "--no-sync", "python", "server.py"]
