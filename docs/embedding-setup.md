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

## 二、在 GPU 服务器上安装（uv）

### 方法 A：uv init 项目（推荐）

```bash
# 1. 安装 uv（如果还没有）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 创建项目目录
mkdir -p /opt/echome-embed && cd /opt/echome-embed

# 3. 初始化项目并安装依赖
uv init --python 3.11
uv add fastapi "uvicorn[standard]" sentence-transformers torch numpy pydantic

# 4. 创建 server.py
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

# 5. 下载模型（首次需要，~2GB）
export HF_ENDPOINT=https://huggingface.co
uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-m3')"

# 6. 启动
uv run server.py
```

> **注意**：下载模型需要设置 `HF_ENDPOINT=https://huggingface.co`，如果网络不通可换镜像源。

### 方法 B：uv 一行跑（快速验证，无需 init）

```bash
uv run --with fastapi --with "uvicorn[standard]" --with sentence-transformers --with torch --with numpy --with pydantic server.py
```

### 方法 C：systemd 守护进程（生产环境）

```ini
# /etc/systemd/system/echome-embed.service
[Unit]
Description=EchoMe Embedding Service
After=network.target

[Service]
Type=simple
User=your-user
WorkingDirectory=/opt/echome-embed
ExecStart=/opt/echome-embed/.venv/bin/python server.py
Restart=always
RestartSec=10
Environment=CUDA_VISIBLE_DEVICES=0
Environment=HF_ENDPOINT=https://huggingface.co

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now echome-embed
```

---

## 三、对接 EchoMe Hub

Hub 的 `.env` 加一行即可：

```env
ECHOME_EMBEDDING_URL=http://<你的GPU服务器IP>:20002
```

如果 Hub 和 embedding 在同一台机器：`http://localhost:20002`
如果 Hub 在 Docker 中、embedding 在宿主机：`http://host.docker.internal:20002`

---

## 四、验证

```bash
# 测试 embedding 服务本身
curl http://your-server:20002/health
curl -X POST http://your-server:20002/embed \
  -H "Content-Type: application/json" \
  -d '{"texts": ["hello world"]}'

# 通过 Hub 测试语义搜索
curl -X POST http://localhost:20000/api/v1/memories/search \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "代码规范"}'
```

---

## 五、更换模型

| 模型 | 维度 | 适用场景 |
|------|------|---------|
| `BAAI/bge-m3` | 1024 | 中英多语言，**推荐** |
| `BAAI/bge-large-zh-v1.5` | 1024 | 纯中文场景 |
| `nomic-ai/nomic-embed-text-v1.5` | 768 | 轻量英文 |
| `intfloat/multilingual-e5-large` | 1024 | 多语言 |

维度变了需要改 Hub 配置 + 模型定义，详见 `hub/app/models/memory.py` 中的 `Vector(1024)`。

---

## 六、降级机制

embedding 服务不可用时 EchoMe **不会崩溃**：
- 写入正常，embedding 字段为 NULL
- 搜索降级为关键词匹配
- Hub 日志输出 WARNING
