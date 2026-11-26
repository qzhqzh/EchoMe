"""Select a few applicable, active habits without semantic search or network calls."""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from echome.core.gate_safety import contains_sensitive_input

MAX_HABITS = 3
MAX_CHARACTERS = 2500
_WEB = re.compile(
    r"(?<![a-z0-9])(?:web|website|frontend|front-end|html|css)(?![a-z0-9])|网页|网站|前端",
    re.IGNORECASE,
)
_WEB_SURFACE = re.compile(
    r"\b(?:web|website|frontend|front-end|html|css|vue|react|svelte|nextjs|ui|landing page)\b|"
    r"网页|网站|前端|页面|界面|样式|配色|布局|按钮|控件|组件|登录页|首页|导航|菜单|表单|手机端|移动端",
    re.IGNORECASE,
)
_WEB_CHANGE = re.compile(
    r"修改|更新|完善|改动|优化|修复|制作|生成|设计|搭建|新增|添加|调整|重构|改进|改成|改为|适配|实现|开发|发布|部署|上线|"
    r"空白|错位|打不开|无法|不能|失败|不生效|不正常|有问题|"
    r"\b(?:build|implement|fix|improve|update|create|change|deploy|publish|ship|broken)\b",
    re.IGNORECASE,
)
_PREVIEW_REQUEST = re.compile(
    r"预览(?:链接|地址|网址|页面)?|(?:访问|展示|验收)(?:链接|地址|网址)|"
    r"\b(?:preview|live url|preview link)\b",
    re.IGNORECASE,
)
_DOMAIN_DELIVERY = re.compile(
    r"(?:应用|\bapp(?:lication)?\b).{0,16}(?:部署|发布|上线|\bdeploy\b).{0,16}(?:域名|\bdomain\b|https?://)|"
    r"(?:部署|发布|上线|\bdeploy\b).{0,16}(?:应用|\bapp(?:lication)?\b).{0,16}(?:域名|\bdomain\b|https?://)",
    re.IGNORECASE,
)
_PREVIEW_HABIT = re.compile(
    r"预览|交付|改动后|修改后|完成.{0,20}(?:改动|开发)|"
    r"\b(?:preview|delivery|deliver|after.{0,30}changes?)\b",
    re.IGNORECASE,
)
_ENGLISH_STOP = {
    "after",
    "always",
    "before",
    "change",
    "changes",
    "current",
    "every",
    "for",
    "from",
    "habit",
    "please",
    "project",
    "projects",
    "should",
    "task",
    "tasks",
    "that",
    "the",
    "then",
    "this",
    "use",
    "using",
    "when",
    "with",
    "work",
    "your",
}
_GENERIC_TAGS = {
    "core",
    "default",
    "delivery",
    "general",
    "preview",
    "quality",
    "stable",
    "style",
    "workflow",
}
_CHINESE_STOP = re.compile(
    r"(?:在|当|每次|完成|开始|之前|之后|前|后|时|需要|进行|处理|使用|关于|相关|"
    r"项目|任务|工作|用户|当前|这个|所有|任何|内容|修改|输出|提供|要求|情况下)"
)
_SHORT_TOPICS = {
    "视频",
    "剧本",
    "分镜",
    "建模",
    "网络",
    "绘图",
    "部署",
    "写作",
    "翻译",
    "测试",
    "提交",
}


def _field(content: str, names: tuple[str, ...]) -> str:
    for line in content.splitlines():
        match = re.match(r"^\s*([^:：]+)[:：]\s*(.*?)\s*$", line)
        if match and match.group(1).strip().casefold() in names:
            return match.group(2)
    return ""


def _contains_term(text: str, term: str) -> bool:
    if re.fullmatch(r"[a-z0-9][a-z0-9_+.-]*", term):
        # In particular, "ai" must never match "detail" or "email".
        return re.search(r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])", text) is not None
    return term in text


def _scope_terms(when: str, tags: set[str]) -> set[str]:
    terms = {
        term
        for term in re.findall(r"[a-z][a-z0-9_+.-]{2,}", when.casefold())
        if term not in _ENGLISH_STOP
    }
    for chunk in _CHINESE_STOP.split(when):
        terms.update(re.findall(r"[\u4e00-\u9fff]{4,24}", chunk))
    terms.update(topic for topic in _SHORT_TOPICS if topic in when)
    terms.update(
        tag
        for tag in tags
        if ":" not in tag and len(tag) >= 3 and tag not in _ENGLISH_STOP | _GENERIC_TAGS
    )
    return terms


def _applicability(when: str, tags: set[str], prompt: str, web_project: bool) -> int:
    if "trigger:always" in tags:
        return 300
    if "trigger:web" in tags or _WEB.search(when):
        is_preview = bool(tags & {"preview", "delivery"}) or bool(_PREVIEW_HABIT.search(when))
        applies = (
            web_preview_applicable(prompt, web_project=web_project)
            if is_preview
            else web_project or bool(_WEB.search(prompt))
        )
        return (250 if "trigger:web" in tags else 200) if applies else 0
    matched = [term for term in _scope_terms(when, tags) if _contains_term(prompt.casefold(), term)]
    return min(100 + sum(min(len(term), 16) for term in matched), 190) if matched else 0


def web_preview_applicable(prompt: str, *, web_project: bool = False) -> bool:
    """A repository manifest alone never implies a preview deliverable.

    Keep explicit UI fixes and previews, including symptoms without an imperative.
    This selects a delivery habit only; it must not suppress memory discovery.
    """
    surface = bool(_WEB_SURFACE.search(prompt))
    if web_project and _DOMAIN_DELIVERY.search(prompt):
        return True
    if _PREVIEW_REQUEST.search(prompt):
        return surface or web_project
    return surface and bool(_WEB_CHANGE.search(prompt))


def _eligible(item: dict[str, Any]) -> tuple[dict[str, Any], str, set[str]] | None:
    scope = item.get("scope")
    tags = item.get("tags")
    if (
        item.get("status") != "active"
        or not isinstance(scope, dict)
        or scope.get("global") is not True
        or scope.get("projects") != []
        or scope.get("exclude_projects") != []
        or not isinstance(tags, list)
        or any(not isinstance(tag, str) for tag in tags)
        or "card:habit" not in tags
        or item.get("superseded_by") is not None
    ):
        return None
    values = [item.get(key) for key in ("id", "title", "content", "updated_at")]
    if any(not isinstance(value, str) or not value.strip() for value in values):
        return None
    memory_id, title, content, updated_at = (str(value) for value in values)
    try:
        memory_id = str(UUID(memory_id))
        datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if contains_sensitive_input("\n".join([title, content, *tags])):
        return None
    when = _field(content, ("适用时机", "when"))
    action = _field(content, ("执行习惯", "do"))
    # Unstructured legacy cards remain readable, but cannot become automatic rules.
    if not when or not action:
        return None
    return (
        {
            "id": memory_id,
            "title": title,
            "content": content,
            "updated_at": updated_at,
            "revision": f"{memory_id}@{updated_at}",
        },
        when,
        {tag.casefold() for tag in tags},
    )


def select_habit_context(
    memories: list[dict[str, Any]],
    prompt: str,
    *,
    web_project: bool = False,
    max_cards: int = MAX_HABITS,
    max_chars: int = MAX_CHARACTERS,
) -> dict[str, list[dict[str, Any]]]:
    """Return complete cards or explicit references within one JSON character budget.

    Input is the ``items`` from the full REST memory list, not truncated MCP card
    summaries. Scope is deliberately global-only until the client resolves project
    identities. These saved preferences never override the current user's request.
    """
    result: dict[str, list[dict[str, Any]]] = {"cards": [], "references": []}
    if not 0 <= max_cards <= MAX_HABITS or not 32 <= max_chars <= MAX_CHARACTERS:
        raise ValueError("Habit limits must be 0-3 cards and 32-2500 characters")
    if not prompt.strip() or contains_sensitive_input(prompt) or max_cards == 0:
        return result
    candidates = []
    for item in memories:
        eligible = _eligible(item)
        if eligible is None:
            continue
        card, when, tags = eligible
        score = _applicability(when, tags, prompt, web_project)
        if not score:
            continue
        priority = item.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            priority = 0
        candidates.append((score, priority, card["updated_at"], card["id"], card))
    candidates.sort(key=lambda row: row[:4], reverse=True)

    def fits() -> bool:
        return len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) <= max_chars

    seen = set()
    for _, _, _, memory_id, card in candidates:
        if memory_id in seen:
            continue
        seen.add(memory_id)
        if len(result["cards"]) + len(result["references"]) >= max_cards:
            break
        result["cards"].append(card)
        if fits():
            continue
        result["cards"].pop()
        reference = {
            "id": memory_id,
            "title": card["title"],
            "revision": card["revision"],
            "needs_expansion": True,
        }
        result["references"].append(reference)
        if not fits():
            reference.pop("title")
        if not fits():
            result["references"].pop()
    return result


def eligible_habit_revisions(memories: list[dict[str, Any]]) -> dict[str, str]:
    """Revision-only inventory, independent of current-task applicability.

    An undispatched eligible card must prevent the Hook from caching the entire
    catalog: the next task may be exactly the task that needs that card.
    """
    revisions = {}
    for item in memories:
        eligible = _eligible(item)
        if eligible is not None:
            card = eligible[0]
            revisions[str(card["id"])] = str(card["revision"])
    return revisions
