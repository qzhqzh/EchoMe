FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps (use Tsinghua mirror)
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple \
    && pip install --no-cache-dir \
    fastapi \
    uvicorn[standard] \
    sentence-transformers \
    torch --index-url https://download.pytorch.org/whl/cu121 \
    numpy \
    pydantic

# Pre-download model at build time (so container starts faster)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

COPY main.py .

EXPOSE 20002

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "20002"]
