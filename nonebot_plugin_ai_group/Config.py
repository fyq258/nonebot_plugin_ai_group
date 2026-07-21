from typing import Annotated, Any, Literal, Union

from nonebot import get_plugin_config
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    field_validator,
    model_validator,
)


class BaseProviderConfig(BaseModel):
    """所有AI服务商账户共有的基础配置"""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="账户的唯一名称")
    api_key: str = Field(description="该账户的 API Key")
    model: str = Field(description="该账户要使用的模型名称")
    proxy: str | None = Field(None, description="为该账户单独设置代理")
    timeout: int = Field(60, gt=0, description="该账户的 API 请求超时时间(秒)")


class OpenAIConfig(BaseProviderConfig):
    """OpenAI 账户特定配置"""

    provider: Literal["openai"] = "openai"
    base_url: HttpUrl = Field(
        description="OpenAI API 兼容格式的访问地址",
    )


class GeminiConfig(BaseProviderConfig):
    """Gemini 账户特定配置"""

    provider: Literal["gemini"] = "gemini"


AIProviderConfig = Annotated[
    Union[OpenAIConfig, GeminiConfig], Field(discriminator="provider")
]


class Config(BaseModel):
    """插件主配置"""

    # --- 通用功能设置 (与具体账户无关) ---
    ai_group_max_messages: int = Field(
        1000, ge=1, description="单次总结允许读取的最大消息数"
    )
    ai_group_min_messages: int = Field(
        50, ge=1, description="单次总结允许读取的最小消息数"
    )
    ai_group_cooldown: int = Field(
        0, ge=0, description="单个用户调用总结功能的冷却时间(秒)"
    )
    ai_group_render_image: bool = Field(
        True, description="是否将总结结果渲染为图片发送"
    )

    # --- 异步任务队列设置 ---
    ai_group_queue_size: int = Field(
        10, ge=1, description="等待处理的总结任务队列最大数量"
    )
    ai_group_request_timeout: int = Field(
        300, gt=0, description="任务入队及处理的总超时时间(秒)"
    )
    ai_group_workers: int = Field(2, ge=1, description="同时处理总结任务的最大并发数")

    # --- AI 账户列表 ---
    ai_group_accounts: list[AIProviderConfig] = Field(
        min_length=1,
        validate_default=True,  # 确保至少配置了一个账户
        description="AI服务商账户配置列表",
    )
    # --- 默认账户 ---
    ai_group_default_account: str | None = Field(
        None, description="默认使用的账户名称。如果未设置，将使用列表中的第一个账户。"
    )

    @field_validator("ai_group_accounts", mode="before")
    @classmethod
    def transform_dict_to_list(cls, v: Any) -> list[AIProviderConfig]:
        """
        在验证前，将从 .env 解析出的字典 {'0': {...}, '1': {...}} 转换成列表 [{...}, {...}]
        如果输入已经是列表 (来自 .toml/.json)，则直接返回。
        """
        result = v
        if isinstance(result, dict):
            # 按 '0', '1', '2'... 排序并提取值
            result = [v[k] for k in sorted(v.keys(), key=int)]
        return result

    @model_validator(mode="after")
    def check_accounts_and_default(self) -> "Config":
        if self.ai_group_min_messages > self.ai_group_max_messages:
            raise ValueError(
                "配置项 'ai_group_min_messages' 不能大于 'ai_group_max_messages'。"
            )

        # 检查账户名称是否唯一
        names = [account.name for account in self.ai_group_accounts]
        if len(names) != len(set(names)):
            raise ValueError("配置项 'ai_group_accounts' 中的 'name' 必须是唯一的。")

        # 如果设置了默认账户，检查它是否存在
        if self.ai_group_default_account and self.ai_group_default_account not in names:
            raise ValueError(
                f"设置的默认账户 '{self.ai_group_default_account}' "
                f"在 'ai_group_accounts' 列表中不存在。"
            )
        return self


config = get_plugin_config(Config)
