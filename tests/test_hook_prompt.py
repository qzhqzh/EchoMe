"""Task semantics survive known client envelopes without generic text filtering."""

import json

import pytest

from echome.core.hook_prompt import normalize_hook_prompt


@pytest.mark.parametrize(
    "ambient",
    [
        '<in-app-browser-context source="ambient-ui-state">\n'
        "This block is automatically supplied ambient UI state.\n"
        "# In app browser:\n- Current URL: https://bwm.example.test/login\n"
        "</in-app-browser-context>",
        '<external_codex_apps_open_page>{"page_id":null}</external_codex_apps_open_page>',
        "<environment_context>\n<cwd>/workspace/unrelated</cwd>\n</environment_context>",
    ],
)
def test_known_ambient_is_removed_but_user_url_and_entities_remain(ambient: str) -> None:
    task = "本项目是否有统一登录，我通过 http://192.168.124.2:18830/login 没有看到"
    assert normalize_hook_prompt(ambient + "\n\n## My request:\n" + task) == task


def test_multiple_ambient_blocks_leave_all_user_topics() -> None:
    task = "更新 Runtime 和 Studio 安装包；保留 OSS 资源及 WDL 路径映射，不触发远程流水线。"
    raw = (
        "<environment_context>project</environment_context>\n"
        "<in-app-browser-context>browser page context</in-app-browser-context>\n"
        "## My request:\n" + task
    )
    assert normalize_hook_prompt(raw) == task


def test_question_reply_keeps_question_and_answer_but_not_client_ids() -> None:
    body = json.dumps(
        [
            {
                "questionItemId": "CLIENT_ONLY_ID",
                "question": "客户机当前部署版本和参考库目录是什么？",
                "answer": "rc.8，CTAT/GRCh37/ctat_genome_lib_build_dir，保留历史数据",
            },
            {"question": "使用哪个入口？", "answer": "https://customer.example.test/"},
        ],
        ensure_ascii=False,
    )
    result = normalize_hook_prompt(
        "<send_user_message_question_reply>\n" + body + "\n</send_user_message_question_reply>"
    )
    assert "CLIENT_ONLY_ID" not in result
    assert "问题： 客户机当前部署版本和参考库目录是什么？" in result
    assert "回答： rc.8，CTAT/GRCh37/ctat_genome_lib_build_dir，保留历史数据" in result
    assert "https://customer.example.test/" in result


@pytest.mark.parametrize(
    "text",
    [
        "请修改 <service>https://host.example.test/</service> 配置",
        "```xml\n<environment_context>需要保留的示例</environment_context>\n```",
        "~~~xml\n<in-app-browser-context>保留</in-app-browser-context>\n~~~",
        "`<environment_context>行内示例</environment_context>`",
        "<send_user_message_question_reply>无法解析但有业务内容</send_user_message_question_reply>",
        "<in-app-browser-context>不完整包装中的用户内容",
        "## My request:\n用户自己写的普通标题",
    ],
)
def test_unknown_or_literal_markup_is_preserved(text: str) -> None:
    assert normalize_hook_prompt(text) == text


@pytest.mark.parametrize("task", ["请继续", "重新查询我的家庭网络记忆", "配置 FlClash 与公司 VPN"])
def test_explicit_recall_refresh_and_continuation_survive_browser_wrapper(task: str) -> None:
    assert (
        normalize_hook_prompt(
            "<in-app-browser-context>browser URL</in-app-browser-context>\n## My request:\n" + task
        )
        == task
    )
