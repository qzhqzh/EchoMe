"""Habit selection is deterministic, scoped, and preserves complete instructions."""

import json
from copy import deepcopy
from typing import Any
from uuid import UUID

import pytest

from echome.core.habit_context import select_habit_context


def habit(index: int = 1, **changes: Any) -> dict[str, Any]:
    item = {
        "id": str(UUID(int=index)),
        "title": "功能展示",
        "content": "适用时机：Web 项目完成可预览的代码、界面或服务改动后。\n"
        "执行习惯：优先提供验证过的完整域名网址。\n"
        "不要做：不要把旧生产域名当作尚未发布改动的预览。\n"
        "交付检查：确认监听、关键资源和登录说明。",
        "tags": ["card:habit", "delivery", "preview", "web"],
        "status": "active",
        "priority": 9,
        "scope": {"global": True, "projects": [], "exclude_projects": []},
        "updated_at": "2026-10-05T02:19:43.986628Z",
    }
    item.update(changes)
    return item


def test_existing_feature_preview_habit_keeps_full_content_and_revision() -> None:
    card = habit()
    before = deepcopy(card)

    result = select_habit_context([card], "修复登录页面", web_project=True)

    assert result["cards"][0]["content"] == card["content"]
    assert result["cards"][0]["revision"] == f"{card['id']}@{card['updated_at']}"
    assert result["references"] == []
    assert card == before


@pytest.mark.parametrize("prompt", ["改进网站配色", "Build a web landing page", "修改Web页面"])
def test_explicit_web_task_can_match_without_repository_detection(prompt: str) -> None:
    assert len(select_habit_context([habit()], prompt)["cards"]) == 1


def test_web_habit_does_not_match_non_web_creation_or_generic_delivery_words() -> None:
    assert select_habit_context([habit()], "用 Blender 建模并提供 preview") == {
        "cards": [],
        "references": [],
    }


@pytest.mark.parametrize(
    "prompt",
    [
        "检查我们项目最近的调用方式和日志",
        "整理我的家庭网络架构",
        "为 WireGuard 新网络分配 IP",
        "用 Blender 构建3D鲸鱼娘",
        "查询数据库慢的原因",
        "解释一下 Vue 和 React 的区别",
        "部署 WireGuard 服务到正式域名",
        "检查网络域名的 DNS 分流日志",
        "发布 npm 包",
    ],
)
def test_web_repository_alone_does_not_trigger_preview_habit(prompt: str) -> None:
    assert select_habit_context([habit()], prompt, web_project=True) == {
        "cards": [],
        "references": [],
    }


@pytest.mark.parametrize(
    "prompt",
    [
        "优化手机端刷卡布局",
        "修复按钮样式",
        "调整这个控件的间距",
        "登录页面是空白，为什么",
        "实现一个知识库界面",
        "给我预览链接",
        "修复首页导航",
        "Improve CSS spacing",
        "Build a web landing page",
        "更新登录页面",
        "完善表单校验",
        "改动按钮的样式",
        "把当前应用部署到正式域名",
        "部署当前应用到正式域名",
    ],
)
def test_ui_fixes_and_preview_requests_still_receive_habit(prompt: str) -> None:
    assert select_habit_context([habit()], prompt, web_project=True)["cards"]


@pytest.mark.parametrize(
    "change",
    [
        {"status": "ai_review"},
        {"status": "archived"},
        {"tags": ["card:skill", "trigger:always"]},
        {"scope": {"global": False, "projects": [], "exclude_projects": []}},
        {"scope": {"global": True, "projects": ["other/project"], "exclude_projects": []}},
        {"scope": {"global": True, "projects": [], "exclude_projects": ["other/project"]}},
        {"scope": {"global": True}},
        {"updated_at": "not-a-date"},
        {"id": "not-a-uuid"},
        {"superseded_by": str(UUID(int=2))},
        {"content": "Unstructured legacy habit with no applicability or action fields."},
    ],
)
def test_unsafe_or_ineligible_habits_are_not_injected(change: dict[str, Any]) -> None:
    assert select_habit_context([habit(**change)], "修改网站", web_project=True) == {
        "cards": [],
        "references": [],
    }


def test_explicit_triggers_precede_text_and_unrelated_cards_stay_out() -> None:
    always = habit(1, tags=["card:habit", "trigger:always"])
    web = habit(2, tags=["card:habit", "trigger:web"])
    legacy = habit(3)
    unrelated = habit(
        4, content="适用时机：视频创作。\n执行习惯：先写剧本。", tags=["card:habit", "video"]
    )

    result = select_habit_context([legacy, unrelated, web, always], "修改网站", web_project=True)

    assert [item["id"] for item in result["cards"]] == [always["id"], web["id"], legacy["id"]]


def test_non_web_habits_match_applicability_without_searching_instruction_bodies() -> None:
    blender = habit(
        1,
        content="When: Blender modeling tasks\nDo: Check silhouettes.\nAvoid: Unverified geometry.",
        tags=["card:habit"],
    )
    video = habit(
        2,
        content="适用时机：视频创作。\n执行习惯：先写剧本，历史案例提到 Blender。",
        tags=["card:habit"],
    )

    result = select_habit_context([blender, video], "Use Blender to create a character")

    assert [item["id"] for item in result["cards"]] == [blender["id"]]
    assert select_habit_context([video], "制作一个视频")["cards"][0]["id"] == video["id"]


def test_ascii_topics_do_not_match_substrings() -> None:
    card = habit(content="When: retail tasks\nDo: Use the catalog.", tags=["card:habit", "mail"])

    assert select_habit_context([card], "Review detailed email formatting") == {
        "cards": [],
        "references": [],
    }


def test_generic_metadata_tags_do_not_make_unrelated_habits_applicable() -> None:
    card = habit(
        content="适用时机：视频创作。\n执行习惯：先写剧本。",
        tags=["card:habit", "quality", "preview", "delivery"],
    )

    assert select_habit_context([card], "Improve quality of Blender preview delivery") == {
        "cards": [],
        "references": [],
    }


@pytest.mark.parametrize("field", ["title", "content"])
def test_secret_bearing_cards_never_return_even_references(field: str) -> None:
    card = habit(**{field: "password=synthetic-invalid-secret"})

    result = select_habit_context([card], "修改网站", web_project=True)

    assert result == {"cards": [], "references": []}


def test_long_habit_is_an_explicit_reference_and_shorter_habit_still_fits() -> None:
    long = habit(
        1,
        tags=["card:habit", "trigger:always"],
        content="When: Any task\nDo: "
        + "完整行为规则。" * 500
        + "\nAvoid: Do not omit this condition.",
    )
    short = habit(2)

    result = select_habit_context([long, short], "修改网站", web_project=True)

    assert [item["id"] for item in result["cards"]] == [short["id"]]
    assert result["references"][0]["id"] == long["id"]
    assert result["references"][0]["needs_expansion"] is True
    assert "content" not in result["references"][0]
    assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) <= 2500


def test_budget_covers_all_metadata_and_never_partial_instructions() -> None:
    card = habit()
    result = select_habit_context([card, card], "修改网站", max_chars=200)

    assert result["cards"] == []
    assert len(result["references"]) == 1
    assert result["references"][0]["needs_expansion"] is True
    assert len(json.dumps(result, ensure_ascii=False, separators=(",", ":"))) <= 200


def test_sensitive_task_and_zero_limit_have_no_injection() -> None:
    assert select_habit_context(
        [habit()], "password=synthetic-invalid-secret", web_project=True
    ) == {"cards": [], "references": []}
    assert select_habit_context([habit()], "修改网站", max_cards=0) == {
        "cards": [],
        "references": [],
    }
