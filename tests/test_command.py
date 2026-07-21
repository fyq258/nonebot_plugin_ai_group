import pytest

from nonebot_plugin_ai_group import (
    extract_plain_text,
    resolve_command_prefixes,
    summary,
    summary_remove,
    summary_set,
)


def test_private_summary_command_parsing() -> None:
    result = summary.command().parse("/总结 855634423 10m")

    assert result.matched
    assert result.query("target") == 855634423
    assert extract_plain_text(result.query("parameter")) == "10m"


def test_group_summary_command_parsing() -> None:
    result = summary.command().parse("/总结 100 主题")

    assert result.matched
    assert result.query("target") == 100
    assert extract_plain_text(result.query("parameter")) == "主题"


def test_private_command_without_duration_reaches_validation() -> None:
    result = summary.command().parse("/总结 855634423")

    assert result.matched
    assert result.query("target") == 855634423
    assert result.query("parameter") is None


@pytest.mark.parametrize(
    ("matcher", "command"),
    [
        (summary, "/总结 855634423 10m"),
        (summary_set, "/总结定时 12 50"),
        (summary_remove, "/总结定时取消"),
    ],
)
def test_commands_accept_nonebot_command_start(matcher, command: str) -> None:
    assert matcher.command().parse(command).matched


def test_commands_reject_missing_prefix_by_default() -> None:
    assert not summary.command().parse("总结 855634423 10m").matched


def test_prefix_can_be_optional() -> None:
    prefixes = resolve_command_prefixes({"/"}, require_prefix=False)
    command = summary.command().__class__(prefixes, "测试")

    assert prefixes == ["/", ""]
    assert command.parse("/测试").matched
    assert command.parse("测试").matched
