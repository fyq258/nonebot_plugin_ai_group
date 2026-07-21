from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from nonebot_plugin_ai_group.Config import Config


ACCOUNT = {
    "provider": "openai",
    "name": "test",
    "base_url": "https://example.com/v1",
    "api_key": "test-key",
    "model": "test-model",
}


def test_command_prefix_is_required_by_default() -> None:
    config = Config(ai_group_accounts=[ACCOUNT])

    assert config.ai_group_require_command_prefix is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ai_group_min_messages", 0),
        ("ai_group_max_messages", 0),
        ("ai_group_cooldown", -1),
        ("ai_group_queue_size", 0),
        ("ai_group_request_timeout", 0),
        ("ai_group_workers", 0),
    ],
)
def test_config_rejects_invalid_numeric_limits(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        Config(ai_group_accounts=[ACCOUNT], **{field: value})


def test_config_rejects_minimum_greater_than_maximum() -> None:
    with pytest.raises(ValidationError, match="ai_group_min_messages"):
        Config(
            ai_group_accounts=[ACCOUNT],
            ai_group_min_messages=101,
            ai_group_max_messages=100,
        )


def test_account_uses_name_and_timeout_fields() -> None:
    account = {**ACCOUNT, "timeout": 30}

    config = Config(
        ai_group_accounts=[account],
        ai_group_default_account="test",
    )

    assert config.ai_group_accounts[0].name == "test"
    assert config.ai_group_accounts[0].timeout == 30


def test_account_rejects_legacy_field_names() -> None:
    account = {key: value for key, value in ACCOUNT.items() if key != "name"}
    account.update({"nickname": "test", "time_out": 30})

    with pytest.raises(ValidationError):
        Config(ai_group_accounts=[account])


def test_accounts_accept_environment_mapping_shape() -> None:
    config = Config(ai_group_accounts={"0": ACCOUNT})

    assert [account.name for account in config.ai_group_accounts] == ["test"]


def test_nonebot_loads_new_configuration_from_dotenv(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                'AI_GROUP_ACCOUNTS__0__PROVIDER="openai"',
                'AI_GROUP_ACCOUNTS__0__NAME="env-test"',
                'AI_GROUP_ACCOUNTS__0__BASE_URL="https://example.com/v1"',
                'AI_GROUP_ACCOUNTS__0__API_KEY="test-key"',
                'AI_GROUP_ACCOUNTS__0__MODEL="test-model"',
                "AI_GROUP_ACCOUNTS__0__TIMEOUT=45",
                "AI_GROUP_RENDER_IMAGE=false",
                "AI_GROUP_REQUIRE_COMMAND_PREFIX=false",
            ]
        ),
        encoding="utf-8",
    )
    script = """
import sys
import nonebot
from nonebot.adapters.onebot.v11 import Adapter

nonebot.init(driver="~none", _env_file=sys.argv[1])
nonebot.get_driver().register_adapter(Adapter)
from nonebot_plugin_ai_group.Config import config

assert config.ai_group_accounts[0].name == "env-test"
assert config.ai_group_accounts[0].timeout == 45
assert config.ai_group_render_image is False
assert config.ai_group_require_command_prefix is False
"""

    result = subprocess.run(
        [sys.executable, "-c", script, str(env_file)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
