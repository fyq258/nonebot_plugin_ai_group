from pydantic import HttpUrl

from nonebot_plugin_ai_group.Model import OpenAI


def test_openai_base_url_has_no_trailing_slash() -> None:
    model = OpenAI(
        account_name="test",
        openai_base_url=HttpUrl("https://example.com/v1/"),
        openai_api_key="test-key",
        summary_model="test-model",
        timeout=60,
        proxy=None,
    )

    assert model.openai_base_url == "https://example.com/v1"
