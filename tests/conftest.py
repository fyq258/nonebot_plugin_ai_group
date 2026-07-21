import nonebot
from nonebot.adapters.onebot.v11 import Adapter


nonebot.init(
    _env_file=None,
    driver="~none",
    ai_group_accounts=[
        {
            "provider": "openai",
            "name": "test",
            "base_url": "https://example.com/v1",
            "api_key": "test-key",
            "model": "test-model",
        }
    ],
    ai_group_render_image=False,
)
nonebot.get_driver().register_adapter(Adapter)
