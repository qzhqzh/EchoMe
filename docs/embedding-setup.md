# Embedding 服务独立部署指南

EchoMe 的语义搜索依赖一个独立的 embedding HTTP 服务。你需要在自己的 GPU 服务器上部署。

---

## 一、接口规范

Hub 调用 embedding 服务只用到 **一个端点**：

### `POST /embed`

```bash
curl -X POST http://your-server:20002/embed \
  -H "Content-Type: application/json" \
  -d '{"texts": ["Python 代码规范\n使用 black 格式化, isort 排序"]}'
```

**Request:**
```json
{
  "texts": ["标题\n正文", "标题2\n正文2"]
}
```

**Response:**
```json
{
  "embeddings": [[0.012, -0.034, ...], [0.078, ...]],
  "dimension": 1024,
  "model": "BAAI/bge-m3"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `texts` | `string[]` | 1~100 条，每条格式: `title + "\n" + content` |
| `embeddings` | `float[][]` | 对应每条文本的向量，长度 = dimension |
| `dimension` | `int` | 向量维度，必须与 Hub 配置一致 |

### `GET /health`（推荐）

```json
{"status": "ok", "model": "BAAI/bge-m3", "dimension": 1024}
```

---

## 二、在 GPU 服务器上安装

### 方法 A：直接运行（推荐开发）

```bash
# 1. 创建环境
conda create -n echome-embed python=3.11 -y
conda activate echome-embed

# 2. 安装依赖
pip install fastapi uvicorn[standard] sentence-transformers torch numpy pydantic

# 3. 创建 server.py
cat > server.py << 'EOF'
"""EchoMe Embedding Service - standalone deployment."""
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer

logger = logging.getLogger("embedding")
model: SentenceTransformer | None = None

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    global model
    logger.info("Loading BGE-M3 model...")
    model = SentenceTransformer("BAAI/bge-m3")
    logger.info(f"Model loaded. Dimension: {model.get_sentence_embedding_dimension()}")
    yield
    del model

app = FastAPI(title="EchoMe Embedding", lifespan=lifespan)

class EmbedRequest(BaseModel):
    texts: list[str] = Field(..., min_length=1, max_length=100)

@app.get("/health")
async def health():
    if model is None:
        raise HTTPException(503, "Model not loaded")
    return {"status": "ok", "model": "BAAI/bge-m3", "dimension": model.get_sentence_embedding_dimension()}

@app.post("/embed")
async def embed(req: EmbedRequest):
    if model is None:
        raise HTTPException(503, "Model not loaded")
    embeddings = model.encode(req.texts, normalize_embeddings=True, show_progress_bar=False)
    return {"embeddings": embeddings.tolist(), "dimension": len(embeddings[0]), "model": "BAAI/bge-m3"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=20002)
EOF

# 4. 启动
python server.py
# 或后台运行:
# nohup python server.py > embed.log 2>&1 &
```

### 方法 B：systemd 服务（推荐生产）

```bash
sudo cat > /etc/systemd/system/echome-embed.service << EOF
[Unit]
Description=EchoMe Embedding Service
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/opt/echome-embed
ExecStart=/opt/echome-embed/venv/bin/python server.py
Restart=always
RestartSec=10
Environment=CUDA_VISIBLE_DEVICES=0

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable echome-embed
sudo systemctl start echome-embed
```

### 方法 C：Docker（如果你偏好容器）

```dockerfile
FROM python:3.11-slim
RUN pip install fastapi uvicorn[standard] sentence-transformers torch numpy pydantic
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"
COPY server.py /app/server.py
WORKDIR /app
CMD ["python", "server.py"]
```

```bash
docker build -t echome-embed .
docker run -d --gpus all -p 20002:20002 --name echome-embed echome-embed
```

---

## 三、对接 EchoMe Hub

在 Hub 的 `.env` 文件中配置：

```env
# 指向你的 embedding 服务地址
ECHOME_EMBEDDING_URL=http://192.168.1.100:20002

# 向量维度（必须与模型输出一致）
ECHOME_EMBEDDING_DIMENSIONS=1024
```

如果 Hub 和 embedding 在同一台机器：
```env
ECHOME_EMBEDDING_URL=http://localhost:20002
```

如果通过 docker-compose 运行 Hub，embedding 在宿主机：
```env
ECHOME_EMBEDDING_URL=http://host.docker.internal:20002
```

---

## 四、验证对接

```bash
# 1. 测试 embedding 服务
curl http://your-server:20002/health

# 2. 测试生成向量
curl -X POST http://your-server:20002/embed \
  -H "Content-Type: application/json" \
  -d '{"texts": ["测试文本"]}'

# 3. 创建一条 memory，观察 Hub 日志是否调用了 embedding
curl -X POST http://localhost:20000/api/v1/memories \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title": "测试", "content": "测试内容", "type": "knowledge", "layer": "L2"}'

# 4. 测试语义搜索
curl -X POST http://localhost:20000/api/v1/memories/search \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "测试"}'
```

---

## 五、更换模型

如果你不用 BGE-M3（1024维），换成其他模型：

| 模型 | 维度 | 适用场景 |
|------|------|---------|
| `BAAI/bge-m3` | 1024 | 中英多语言，推荐 |
| `BAAI/bge-large-zh-v1.5` | 1024 | 纯中文场景 |
| `nomic-ai/nomic-embed-text-v1.5` | 768 | 轻量英文 |
| `intfloat/multilingual-e5-large` | 1024 | 多语言 |

**如果维度变了** (如 768)，需要：

1. `.env` 改 `ECHOME_EMBEDDING_DIMENSIONS=768`
2. `hub/app/models/memory.py` 改 `Vector(1024)` → `Vector(768)`
3. 清空旧向量：`UPDATE memories SET embedding = NULL;`
4. Hub 会在后续操作中自动重新生成

---

## 六、降级机制

如果 embedding 服务不可用（宕机/网络不通），EchoMe 不会崩溃：

- 创建/更新 memory：正常工作，`embedding` 字段为 NULL
- 搜索：自动降级为**关键词匹配**（不用向量，效果差一些）
- Hub 日志会打印 WARNING: `Embedding service unavailable: ...`
