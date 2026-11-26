"""Task terms for unsolicited discovery, without changing explicit search recall."""

import re

# Request scaffolding describes the conversation, not the subject to recall.
# Keep domain nouns, identifiers, paths and URLs. Do not strip arbitrary XML or
# code here: client-specific envelopes are handled by the client adapter.
_SCAFFOLDING = (
    "我们这个", "我们现在", "我们当前", "我们的", "我的", "你的", "这个", "那个",
    "这些", "那些", "一下", "一些", "一个", "哪些", "什么", "怎么", "如何",
    "是否", "有没有", "能不能", "是不是", "我现在", "现在", "当前", "之前",
    "之后", "然后", "另外", "还有", "以及", "或者", "里面", "这里", "这个里面",
    "我希望", "我关心", "希望", "关心", "帮我", "看一下", "看看", "看到", "看下",
    "请问", "需要", "应该", "可以", "已经", "正常", "情况", "对应", "相关",
    "信息", "关于", "明确", "有一个", "感觉", "本次", "先按", "给我", "现在就",
)
_PROCEDURAL = {
    "检查", "查看", "查询", "搜索", "提供", "使用", "处理", "进行", "完成", "实现",
    "支持", "记录", "功能", "测试", "修改", "更新", "配置", "生成", "问题", "方式",
    "方法", "是否", "我们", "我的", "用户", "客户", "当前", "确认", "通过", "需要",
    "项目", "系统", "数据", "工作", "流程", "结果", "内容", "时间", "文件", "目录",
    "部署", "服务", "安装", "版本", "最新", "优化", "整理", "执行", "运行",
    "好的", "是的", "一下", "可以", "还有", "不要", "应该", "不能", "希望", "please", "this", "that", "with", "from", "what", "which", "how", "our", "your",
    "project", "system", "data", "feature", "workflow", "update", "check", "current",
    "全文", "摘要", "下载", "数据库", "字段", "设计", "历史", "状态", "命令",
    "不同", "了解", "解决", "办法", "直接", "再给", "再次", "同样", "这种", "这样",
    "issue", "issues", "runtime", "studio", "database", "docker", "code", "page",
    "初始化", "安装包", "默认路径", "部署包", "本地", "的时候", "每个", "全部",
}
_EXPLICIT_RECALL = re.compile(
    r"(?:检索|搜索|查找|查一下|查一查|查看|读取|回忆|查询).{0,8}记忆"
    r"|(?:以前|之前|上次).{0,20}(?:约定|偏好|决策|结论|配置|方案)"
    r"|\b(?:search|retrieve|recall|look up)\b.{0,25}\bmemories\b",
    re.I,
)


def explicit_recall_requested(query: str) -> bool:
    return bool(_EXPLICIT_RECALL.search(query))


def discovery_named_terms(query: str) -> list[str]:
    """Literal identifiers, without inferred aliases, platforms or request verbs."""
    generic = _PROCEDURAL | {
        "windows", "linux", "macos", "android", "iphone", "http", "https",
        "fix", "implement", "create", "add", "edit", "use", "test", "tests", "need",
        "want", "can", "could", "would", "when", "where", "file", "files", "repo",
        "repository", "server", "client", "version", "latest", "preserve", "existing",
        "safely", "previous", "review", "installation", "configuration",
    }
    return list(dict.fromkeys(
        token for token in re.findall(r"[a-z0-9_+#.-]{2,64}", query.lower())
        if token not in generic and re.search(r"[a-z]", token)
    ))[:16]


def discovery_query_text(query: str) -> str:
    """Remove conversational phrases before n-grams can turn them into evidence."""
    for phrase in sorted(_SCAFFOLDING, key=len, reverse=True):
        query = query.replace(phrase, " ")
    return re.sub(r"\s+", " ", query).strip()


def discovery_query_tokens(query: str) -> list[str]:
    from app.services.memory_retrieval import QUERY_ALIASES, _term_matches

    text = discovery_query_text(query).lower()
    # Preserve short technical identifiers (IGV, ACR, wg0) before long Chinese
    # sentences consume the bounded term list. Raw sentences are not terms.
    latin = list(dict.fromkeys(re.findall(r"[a-z0-9_+#.-]{2,64}", text)))
    chinese: set[str] = set()
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", re.sub(r"[的是在和与]", " ", text)):
        if len(chunk) <= 8:
            chinese.add(chunk)
        for width in (2, 3, 4):
            chinese.update(chunk[i : i + width] for i in range(len(chunk) - width + 1))
    # Fragments of connective prose (本的/的是/我采) cannot support a topic
    # match. Semantic recall still uses the complete original task.
    chinese = {term for term in chinese if not re.search(r"[的我你这那吗了]", term)}
    ordered = latin + sorted(chinese, key=lambda term: (-len(term), term))
    specific = [term for term in ordered if term not in _PROCEDURAL]
    # Broad terms asked on their own remain searchable. With a concrete subject
    # (e.g. 文献下载), 下载 alone must not retrieve unrelated model/VPN downloads.
    tokens = specific or ordered
    for marker, aliases in QUERY_ALIASES.items():
        if _term_matches(marker, text) and marker not in _PROCEDURAL:
            tokens.extend(alias for alias in aliases if alias not in tokens)
    return tokens[:64]
