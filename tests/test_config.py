import pytest
from pydantic import ValidationError

from nonebot_plugin_ai_group.Config import Config


ACCOUNT = {
    "provider": "openai",
    "nickname": "test",
    "base_url": "https://example.com/v1",
    "api_key": "test-key",
    "model": "test-model",
}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("summary_min_length", 0),
        ("summary_max_length", 0),
        ("summary_cool_down", -1),
        ("summary_max_queue_size", 0),
        ("summary_queue_timeout", 0),
        ("summary_queue_workers", 0),
    ],
)
def test_config_rejects_invalid_numeric_limits(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Config(ai_accounts=[ACCOUNT], **{field: value})


def test_config_rejects_minimum_greater_than_maximum() -> None:
    with pytest.raises(ValidationError, match="summary_min_length"):
        Config(
            ai_accounts=[ACCOUNT],
            summary_min_length=101,
            summary_max_length=100,
        )
