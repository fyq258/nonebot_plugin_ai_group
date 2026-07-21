from abc import abstractmethod

import httpx
from nonebot.log import logger
from pydantic import HttpUrl

from .Config import AIProviderConfig, config


class Model:
    name: str

    @abstractmethod
    async def summary_history(self, messages: list[dict[str, str]], prompt: str) -> str:
        pass


class Gemini(Model):
    def __init__(
        self,
        account_name: str,
        gemini_key: str,
        summary_model: str,
        timeout: int,
        proxy: str | None,
    ):
        self.name = account_name
        self.gemini_key = gemini_key
        self.summary_model = summary_model
        self.proxy = proxy
        self.timeout = timeout

    async def summary_history(self, messages: list[dict[str, str]], prompt: str) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.summary_model}:generateContent"
        headers = {
            "Content-Type": "application/json",
            "X-goog-api-key": self.gemini_key,
        }
        data = {
            "contents": [
                {"parts": [{"text": prompt}], "role": "user"},
                {"parts": [{"text": str(messages)}], "role": "user"},
            ]
        }

        async with httpx.AsyncClient(proxy=self.proxy, timeout=self.timeout) as client:
            response = await client.post(url, json=data, headers=headers)
            response.raise_for_status()

            result = response.json()

            return result["candidates"][0]["content"]["parts"][0]["text"]


class OpenAI(Model):
    def __init__(
        self,
        account_name: str,
        openai_base_url: HttpUrl,
        openai_api_key: str,
        summary_model: str,
        timeout: int,
        proxy: str | None,
    ):
        self.name = account_name
        self.openai_base_url = str(openai_base_url).rstrip("/")
        self.openai_api_key = openai_api_key
        self.summary_model = summary_model
        self.proxy = proxy
        self.timeout = timeout

    async def summary_history(self, messages: list[dict[str, str]], prompt: str) -> str:
        url = f"{self.openai_base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.openai_api_key}",
        }
        data = {
            "model": self.summary_model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": str(messages)},
            ],
        }

        async with httpx.AsyncClient(proxy=self.proxy, timeout=self.timeout) as client:
            response = await client.post(url, json=data, headers=headers)
            response.raise_for_status()

            result = response.json()

            return result["choices"][0]["message"]["content"]


def detect_model() -> Model:
    """根据插件配置中的账户列表返回一个带回退能力的模型实例。

    会构造每个配置账户对应的 Model 实例，并按优先顺序（默认账户优先）包装成 `FallbackModel`。
    """
    accounts = config.ai_group_accounts

    # 若有默认账户名称，则将其放到首位
    default_account = config.ai_group_default_account
    ordered_accounts: list[AIProviderConfig] = []
    if default_account:
        for acc in accounts:
            if acc.name == default_account:
                ordered_accounts.append(acc)
                break
    # 追加其它账户（保持原始顺序）
    for acc in accounts:
        if acc not in ordered_accounts:
            ordered_accounts.append(acc)

    models: list[Model] = []
    for acc in ordered_accounts:
        account_name = acc.name
        acc_api_key = acc.api_key
        acc_provider = acc.provider
        acc_model = acc.model
        acc_proxy = acc.proxy
        account_timeout = acc.timeout

        if acc_provider == "gemini":
            m = Gemini(account_name, acc_api_key, acc_model, account_timeout, acc_proxy)
        elif acc_provider == "openai":
            base_url: HttpUrl = getattr(acc, "base_url")
            m = OpenAI(
                account_name,
                base_url,
                acc_api_key,
                acc_model,
                account_timeout,
                acc_proxy,
            )
        else:
            logger.warning(f"跳过未知账户类型: {acc_provider}。")
            continue

        if m:
            models.append(m)

    class FallbackModel(Model):
        """包装多个 Model 实例，按顺序尝试直到有成功的响应。"""

        def __init__(self, models: list[Model]):
            self.models = models

        async def summary_history(
            self, messages: list[dict[str, str]], prompt: str
        ) -> str:
            for idx, m in enumerate(self.models):
                logger.debug(f"尝试使用第 {idx + 1} 个模型: {m.name}")
                try:
                    res = await m.summary_history(messages, prompt)
                except Exception as e:
                    # 记录模型调用失败的异常
                    logger.warning(f"模型 {m.name} 返回错误，尝试下一个账户: {str(e)}")
                    continue

                # 成功返回
                return res

            # 所有模型都失败，返回最后一个错误信息
            raise RuntimeError("所有 AI 模型调用均失败")

    return FallbackModel(models)
