"""Exercise user intent rather than matching the implementation's patterns."""

import pytest

from echome.core.hook_freshness import classify_freshness


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("请重新检查项目的 Git 状态", "normal"),
        ("只剪枝重建并原子刷新 SHA256SUMS", "normal"),
        ("重新计算校验值，按记忆里的部署约定执行", "normal"),
        ("读取最新 Git 配置文件", "normal"),
        ("重新生成偏好分析报告", "normal"),
        ("更新偏好设置页面", "normal"),
        ("请重新检查记忆服务的日志", "normal"),
        ("不要读取记忆服务日志，查一下记忆里的部署约定", "normal"),
        ("不要使用偏好设置页面，按我之前的部署约定操作", "normal"),
        ("如何刷新记忆？", "normal"),
        ("刷新记忆是什么原理？", "normal"),
        ("请查一下记忆中的部署约定", "normal"),
        ("不要刷新记忆，重新检查 Git 状态", "normal"),
        ("recalculate checksum again", "normal"),
        ("请刷新记忆", "force"),
        ("重新查询记忆中的家庭网络配置", "force"),
        ("请重新查一下我们之前的部署约定", "force"),
        ("按刚更新的偏好继续", "force"),
        ("读取最新家庭网络配置", "force"),
        ("检查习惯更新后的 Web 预览规则", "force"),
        ("请按新保存的记忆修改页面", "force"),
        ("先重新检查 Git，然后重新查询记忆中的部署约定", "force"),
        ("不要刷新旧记忆，重新读取最新记忆", "force"),
        ("不要读取旧记忆，请重新读取最新记忆", "force"),
        ("重新审视我刚保存的记忆", "force"),
        ("refresh my memory", "force"),
        ("请不要读取记忆，只重新检查 Git 状态", "skip"),
        ("不要参考我的记忆，修复项目页面", "skip"),
        ("不要调用 EchoMe，重新检查状态", "skip"),
        ("不使用历史上下文，请处理当前文件", "skip"),
        ("不用查记忆了", "skip"),
        ("不要读取任何记忆，请重新读取最新记忆", "skip"),
        ("Don't read my memory; check Git again", "skip"),
    ],
)
def test_freshness_is_about_the_memory_not_just_a_refresh_word(text: str, expected: str) -> None:
    assert classify_freshness(text) == expected
