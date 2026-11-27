"""Conservative local intent checks for the automatic memory-read hook.

These checks do not execute a user instruction or inspect memory contents.
"""

from __future__ import annotations

import re
from typing import Literal

Freshness = Literal["normal", "force", "skip"]

# Only inspect the relevant clause when associating an action with its object.
_GAP = r"[^，,。；;！!？?\n]"
_SPLIT = re.compile(r"[，,。；;！!？?\n]+")
_MEMORY = r"(?:记忆(?:库)?|偏好|习惯(?:卡)?)(?!服务|系统|项目|页面|设置页|文件|文档|报告|分析)"
_HISTORY = (
    r"(?:之前|以前|上次|历史|过往|先前|刚才|刚刚|刚保存|刚更新|刚写入|新保存|新记录)"
    + _GAP
    + r"{0,12}(?:约定|决策|配置|方案|经验|规则|记录)"
)
_TARGET = rf"(?:{_MEMORY}|{_HISTORY}|(?:项目|长期)(?:历史|约定|决策|经验|上下文))"
_READ = r"(?:查一查|查一下|查询|查找|查看|读取|检索|搜索|获取|调取|拉取|回忆|查|读)"
_NEGATION = r"(?:不要|不用|不必|无需|别|禁止|不需要|不得|不)"
_NO_READ = re.compile(
    _NEGATION
    + r"(?:再|去|继续)?(?:查询|查找|查看|读取|检索|搜索|使用|调用|参考|借助|利用|加载|查|读|用)\s*"
    + r"(?:我的|我们的|任何|这些|这次的|本次的|EchoMe的)?\s*"
    + rf"(?:{_MEMORY}|EchoMe|历史(?:记忆|对话|上下文))",
    re.I,
)
_OLD_NO_READ = re.compile(
    _NEGATION
    + r"(?:再|去|继续)?(?:读取|查询|查|读|使用)(?:旧|过时的?|之前的?)"
    + r"(?:记忆|偏好|习惯)",
    re.I,
)
_NO_REFRESH = re.compile(
    _NEGATION
    + r"(?:再|去|继续|强制)?(?:刷新|更新|重新(?:读取|查询|查|读)|再次(?:读取|查询|查|读))"
    + _GAP
    + r"{0,8}"
    + _MEMORY,
    re.I,
)
_ENGLISH_NO_READ = re.compile(
    r"\b(?:do not|don't|never|do not use|don't use|no)\s+(?:read|retrieve|search|use|access)?\s*"
    r"(?:my\s+|any\s+|the\s+)?(?:memories|memory)\b",
    re.I,
)
_META = re.compile(
    r"(?:如何|怎么|怎样|为什么|解释|介绍|说明|区别)"
    + _GAP
    + r"{0,12}(?:刷新|重新|再次|读取|检索|查询)"
    + r"|(?:刷新|重新查|读取)"
    + _GAP
    + r"{0,16}(?:是什么原理|是什么意思|有什么区别|怎么实现|如何实现|怎么做的)",
    re.I,
)
_LOCAL_OBJECT = re.compile(
    r"\b(?:git|sha256sums|commit|checksum|hash)\b|校验|文件|文档|目录|镜像|网页|页面|报告|日志|服务状态",
    re.I,
)
_FORCE = tuple(
    re.compile(pattern, re.I)
    for pattern in (
        rf"(?:重新|再次|再|强制)(?:帮我|给我|请)?{_READ}{_GAP}{{0,16}}{_TARGET}",
        rf"(?:刷新|更新){_GAP}{{0,5}}{_MEMORY}",
        rf"{_TARGET}{_GAP}{{0,12}}(?:重新|再次|再){_READ}",
        rf"(?:刚刚|刚才|已经|新近|新)?(?:更新|修改|保存|记录|添加|新增|写入|变更){_GAP}{{0,12}}{_MEMORY}",
        rf"{_MEMORY}{_GAP}{{0,12}}(?:刚刚|刚才|已经)?(?:更新|修改|保存|添加|新增|变更)",
        rf"(?:按|按照|依照|依据|使用|读取|查询|查找|检索|查看){_GAP}{{0,6}}"
        rf"(?:最新|新保存的|刚更新的|刚保存的){_GAP}{{0,8}}(?:记忆|偏好|习惯|约定|决策|经验|规则)",
        r"\b(?:refresh|reload|re-read|requery|update)\b"
        + _GAP
        + r"{0,24}\b(?:memory|memories|preferences?|habits?)\b",
    )
)
_RECENT_SAVED = re.compile(
    rf"(?:刚刚|刚才|刚|新)(?:保存|写入|记录|新增)(?:了|的)?{_GAP}{{0,12}}"
    r"(?:约定|决策|偏好|习惯|经验|规则)(?!文件|文档|页面)",
    re.I,
)
_LATEST_CONTEXT = re.compile(
    rf"{_READ}{_GAP}{{0,5}}最新{_GAP}{{0,16}}(?:配置|约定|决策|规则|方案|经验)", re.I
)
_FRESH_CUE = re.compile(
    r"重新|刷新|再次|最新|刚(?:刚|才)?.{0,10}(?:更新|保存|新增|修改)|"
    r"\b(?:refresh|reload|again|latest|newly)\b",
    re.I,
)
_MEMORY_CUE = re.compile(
    _MEMORY + r"|历史(?:约定|决策|规则|配置)|previous (?:memory|preferences)", re.I
)


def classify_freshness(text: str) -> Freshness:
    """Return whether the current prompt forbids, requires, or normally permits a read.

    A plain Git/file refresh is not a memory refresh. An ambiguous refresh with a
    memory cue is conservative unless its object is clearly a local artifact.
    General explicit prohibitions win over positive instructions; a prohibition
    limited to old memories does not block an explicit request for fresh memory.
    """
    clauses = [part.strip() for part in _SPLIT.split(text) if part.strip()]
    for part in clauses:
        if _NO_READ.search(part) or _ENGLISH_NO_READ.search(part):
            return "skip"

    active = [
        part
        for part in clauses
        if not _META.search(part) and not _OLD_NO_READ.search(part) and not _NO_REFRESH.search(part)
    ]
    for part in active:
        if any(pattern.search(part) for pattern in _FORCE):
            return "force"
        if not _LOCAL_OBJECT.search(part) and (
            _LATEST_CONTEXT.search(part) or _RECENT_SAVED.search(part)
        ):
            return "force"
        if _FRESH_CUE.search(part) and _MEMORY_CUE.search(part) and not _LOCAL_OBJECT.search(part):
            return "force"
    return "normal"
