from nonebot_plugin_ai_group import extract_plain_text, summary


def test_private_summary_command_parsing() -> None:
    result = summary.command().parse("总结 855634423 10m")

    assert result.matched
    assert result.query("target") == 855634423
    assert extract_plain_text(result.query("parameter")) == "10m"


def test_group_summary_command_parsing() -> None:
    result = summary.command().parse("总结 100 主题")

    assert result.matched
    assert result.query("target") == 100
    assert extract_plain_text(result.query("parameter")) == "主题"


def test_private_command_without_duration_reaches_validation() -> None:
    result = summary.command().parse("总结 855634423")

    assert result.matched
    assert result.query("target") == 855634423
    assert result.query("parameter") is None
