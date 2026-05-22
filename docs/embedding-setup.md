# Embedding 服务部署指南

EchoMe 的语义搜索依赖 BGE-M3 embedding 服务，通过 docker-compose 集成或独立部署。

---

## 一、docker-compose 集成（推荐）

embedding 服务已集成在 `docker-compose.yaml` 中，直接启动即可：

```bash
docker compose up -d
```

**首次启动**会在构建镜像时通过 ModelScope 下载 BGE-M3 模型（~2GB），后续启动秒级。

模型存储在 `embedding-models` volume 中，重建容器不会重复下载。

### 前提条件

- Docker + Docker Compose
- NVIDIA GPU + [nvidia-container-toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)

### 无 GPU 运行

如果没有 GPU，去掉 `docker-compose.yaml` 中 embedding 服务的 `deploy.resources` 部分即可用 CPU 跑（速度慢但能用）。

---

## 二、独立部署（uv + modelscope）

如果 embedding 服务部署在单独的 GPU 服务器上：

```bash
# 1. 安装 uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. 创建目录
mkdir -p /opt/echome-embed && cd /opt/echome-embed

# 3. 初始化 + 安装依赖
uv init --python 3.11
uv add fastapi "uvicorn[standard]" sentence-transformers torch numpy pydantic modelscope

# 4. 下载模型（通过 ModelScope，国内快）
uv run python -c "
from modelscope import snapshot_download
snapshot_download('BAAI/bge-m3', cache_dir='./models')
"

# 5. 复制 server.py（从仓库 embedding/server.py）
# 修改 MODEL_DIR 指向本地模型路径
export MODEL_DIR=./models/BAAI/bge-m3

# 6. 启动
uv run python server.py
```

### systemd 守护进程

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
Environment=MODEL_DIR=/opt/echome-embed/models/BAAI/bge-m3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now echome-embed
```

---

## 三、接口规范

### `POST /embed`

```json
// Request
{"texts": ["标题\n正文", "标题2\n正文2"]}

// Response
{"embeddings": [[0.012, ...], [0.078, ...]], "dimension": 1024, "model": "BAAI/bge-m3"}
```

### `GET /health`

```json
{"status": "ok", "model": "BAAI/bge-m3", "dimension": 1024}
```

---

## 四、Hub 对接配置

docker-compose 模式下无需额外配置（自动连接 `http://embedding:20002`）。

独立部署时，在 Hub 的 `.env` 中设置：

```env
ECHOME_EMBEDDING_URL=http://<GPU服务器IP>:20002
```

---

## 五、验证

```bash
# 健康检查
curl http://localhost:20002/health

# 测试向量生成
curl -X POST http://localhost:20002/embed \
  -H "Content-Type: application/json" \
  -d '{"texts": ["hello world"]}'

# 测试语义搜索（通过 Hub）
curl -X POST http://localhost:20000/api/v1/memories/search \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "代码规范"}'
```

---

## 六、更换模型

| 模型 | 维度 | 适用场景 |
|------|------|---------|
| `BAAI/bge-m3` | 1024 | 中英多语言，**推荐** |
| `BAAI/bge-large-zh-v1.5` | 1024 | 纯中文场景 |
| `nomic-ai/nomic-embed-text-v1.5` | 768 | 轻量英文 |
| `intfloat/multilingual-e5-large` | 1024 | 多语言 |

维度变了需要同步修改 `hub/app/models/memory.py` 中 `Vector(1024)` 和 `.env` 中 `ECHOME_EMBEDDING_DIMENSIONS`。

---

## 七、降级机制

embedding 服务不可用时 EchoMe **不会崩溃**：
- 写入正常，embedding 字段为 NULL
- 搜索降级为关键词匹配
- Hub 日志输出 WARNING
