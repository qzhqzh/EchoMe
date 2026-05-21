# EchoMe Embedding Service Contract

EchoMe Hub 需要一个外部 HTTP embedding 服务来支持语义搜索。你可以使用任何模型（BGE-M3、OpenAI、Nomic 等），只要暴露以下接口。

## API 接口

### `POST /embed`

生成文本向量。

**Request:**
```json
{
  "texts": [
    "记忆标题\n记忆正文内容",
    "另一条记忆的标题\n另一条记忆的内容"
  ]
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `texts` | `string[]` | 1~100 条文本，每条是 `title + "\n" + content` |

**Response:**
```json
{
  "embeddings": [
    [0.012, -0.034, 0.056, ...],
    [0.078, -0.012, 0.045, ...]
  ],
  "dimension": 1024,
  "model": "BAAI/bge-m3"
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `embeddings` | `float[][]` | 每条文本对应一个向量，长度 = dimension |
| `dimension` | `int` | 向量维度（必须与 Hub 配置一致） |
| `model` | `string` | 模型名称（仅信息性） |

### `GET /health`（可选）

```json
{"status": "ok", "model": "BAAI/bge-m3", "dimension": 1024}
```

## Hub 配置

```env
# .env
ECHOME_EMBEDDING_URL=http://your-gpu-server:20002
ECHOME_EMBEDDING_DIMENSIONS=1024
```

**重要：** `ECHOME_EMBEDDING_DIMENSIONS` 必须与模型输出维度一致，否则 pgvector 会报错。

## 常见模型维度参考

| 模型 | 维度 | 语言 | 备注 |
|------|------|------|------|
| BAAI/bge-m3 | 1024 | 中英多语言 | 推荐，当前默认 |
| BAAI/bge-large-zh | 1024 | 中文 | |
| text-embedding-3-small | 1536 | 多语言 | OpenAI API |
| nomic-embed-text | 768 | 英文为主 | 开源轻量 |
| mxbai-embed-large | 1024 | 多语言 | |

## 更换模型维度

如果你的模型维度 ≠ 1024（当前默认），需要：

1. 修改 `.env`：`ECHOME_EMBEDDING_DIMENSIONS=<新维度>`
2. 清空现有 embedding 数据：
   ```sql
   UPDATE memories SET embedding = NULL;
   ```
3. 修改 `hub/app/models/memory.py` 中 `Vector(1024)` 为新维度
4. 重新生成全部 embedding（Hub 会在下次访问 memory 时自动重算）

## 本地开发参考

`embedding/main.py` 提供了一个基于 BGE-M3 + sentence-transformers 的参考实现，可直接使用：

```bash
cd embedding
pip install -r requirements.txt
python main.py  # 启动在 :20002
```

需要 GPU 或较大内存（BGE-M3 约 2GB）。
