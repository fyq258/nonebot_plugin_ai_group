import nonebot
from nonebot.adapters.onebot.v11 import Adapter


nonebot.init(
    _env_file=None,
    driver="~none",
    ai_accounts=[
        {
            "provider": "openai",
            "nickname": "test",
            "base_url": "https://example.com/v1",
            "api_key": "test-key",
            "model": "test-model",
        }
    ],
    summary_in_png=False,
)
nonebot.get_driver().register_adapter(Adapter)
