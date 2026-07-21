import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from math import ceil
from pathlib import Path

from nonebot import get_bot, require
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, Message, MessageSegment

from ..Config import config
from ..Store import Data, Store
from .queue_request import (
    queue_summary_request,
)

require("nonebot_plugin_apscheduler")
from nonebot_plugin_apscheduler import scheduler  # noqa: E402


def get_css_path() -> Path:
    """获取css路径"""
    return Path(__file__).parent.parent / "assert" / "github-markdown-dark.css"


if config.summary_in_png:
    require("nonebot_plugin_htmlrender")
    from nonebot_plugin_htmlrender import md_to_pic  # type: ignore

    async def generate_image(summary: str) -> bytes:
        return await md_to_pic(summary, css_path=str(get_css_path()))


cool_down = defaultdict(lambda: datetime.now())


def validate_group_event(event) -> bool:
    return isinstance(event, GroupMessageEvent)


def validate_message_count(num: int) -> bool:
    """验证消息数量是否在合法范围内"""
    return num >= config.summary_min_length and num <= config.summary_max_length


def validate_cool_down(user_id: int) -> bool | int:
    """验证是否冷却"""
    if config.summary_cool_down > 0:
        if (last_time := cool_down[user_id]) > datetime.now():
            return ceil((last_time - datetime.now()).total_seconds())
        cool_down[user_id] = datetime.now() + timedelta(
            seconds=config.summary_cool_down
        )
    return False


async def process_message(
    messages,
    bot: Bot,
    group_id: int,
    remove_last_message: bool = False,
) -> list[dict[str, str]]:
    # 预先收集所有被@的QQ号，同时过滤掉非法消息
    qq_set: set[str] = set()
    for msg in messages:
        valid_segments = [
            segment for segment in msg["message"] if isinstance(segment, dict)
        ]
        qq_set.update(
            segment["data"]["qq"]
            for segment in valid_segments
            if segment["type"] == "at" and segment["data"]["qq"].isdigit()
        )
        msg["message"] = valid_segments

    # 将所有被@的QQ号转换为其群昵称
    qq_name = await fetch_member_nicknames(bot, group_id, qq_set)

    result: list[dict[str, str]] = []
    for message in messages:
        text_segments = []
        for segment in message["message"]:
            if segment["type"] == "text":
                text = segment["data"]["text"].strip()
                if text:  # 只添加非空文本
                    text_segments.append(text)
            elif (
                segment["type"] == "at" and segment["data"]["qq"] in qq_name
            ):  # 处理@消息，替换为昵称
                text_segments.append(f"@{qq_name[segment['data']['qq']]}")

        if text_segments:  # 只处理有内容的消息
            sender: str = message["sender"]["card"] or message["sender"]["nickname"]
            result.append({sender: "".join(text_segments)})

    if remove_last_message and result:
        result.pop()  # 去除请求总结的命令

    return result


async def fetch_member_nicknames(
    bot: Bot, group_id: int, qq_set: set[str]
) -> dict[str, str]:
    """批量获取群成员的昵称"""
    qq_name: dict[str, str] = {}
    if qq_set:
        member_infos = await asyncio.gather(
            *(
                bot.get_group_member_info(group_id=group_id, user_id=qq)  # type: ignore 传 str | int 均可
                for qq in qq_set
            ),
            return_exceptions=True,
        )
        qq_name.update(
            {
                str(info["user_id"]): info["card"] or info["nickname"]  # type: ignore
                for info in member_infos
                if not isinstance(info, Exception)
            }
        )

    return qq_name


async def get_group_msg_history(
    bot: Bot, group_id: int, count: int
) -> list[dict[str, str]]:
    """获取群聊消息记录"""
    messages = (await bot.get_group_msg_history(group_id=group_id, count=count))[
        "messages"
    ]

    return await process_message(messages, bot, group_id, remove_last_message=True)


async def messages_summary(
    messages: list[dict[str, str]], content: str | None = None
) -> str:
    """使用模型对历史消息进行总结"""
    prompt = (
        f"请根据以下群聊记录，主要描述与“{content}”相关的事件经过，要求条理清晰、内容完整，用中文输出总结。"
        if content
        else "请根据以下群聊记录，详细讲述主要事件经过，要有什么人讲了什么，最后对主要参与者进行简短评价，要求条理清晰、内容完整，用中文输出总结。"
    )
    return await queue_summary_request(messages, prompt)


async def send_summary(bot: Bot, group_id: int, summary: str):
    """发送总结"""
    if config.summary_in_png:
        img = await generate_image(summary)
        await bot.send_group_msg(
            group_id=group_id, message=Message(MessageSegment.image(img))
        )
    else:
        await bot.send_group_msg(group_id=group_id, message=summary.strip())


async def scheduler_send_summary(group_id: int, least_message_count: int):
    """最近 24 小时消息数达到阈值时发送定时总结。"""
    bot = get_bot()
    messages = (
        await bot.get_group_msg_history(group_id=group_id, count=least_message_count)
    )["messages"]

    deadline = (datetime.now() - timedelta(hours=24)).timestamp()
    messages = [message for message in messages if message["time"] > deadline]

    if len(messages) < least_message_count:
        return

    messages = await process_message(messages, bot, group_id)  # type: ignore
    if not messages:
        return

    summary = await messages_summary(messages)

    await send_summary(bot, group_id, summary)  # type: ignore


def get_scheduler_job_id(group_id: int) -> str:
    return f"summary_group_{group_id}"


def schedule_summary(group_id: int, data: Data) -> None:
    """新增或更新一个群的定时总结任务。"""
    scheduler.add_job(
        scheduler_send_summary,
        "cron",
        hour=data["time"],
        args=(group_id, data["least_message_count"]),
        id=get_scheduler_job_id(group_id),
        replace_existing=True,
    )


def remove_summary_schedule(group_id: int) -> None:
    """移除一个群的定时总结任务。"""
    job_id = get_scheduler_job_id(group_id)
    if scheduler.get_job(job_id) is not None:
        scheduler.remove_job(job_id)


def set_scheduler() -> None:
    """从持久化配置恢复全部定时任务。"""
    store = Store()
    for group_id, data in store.data.items():
        schedule_summary(int(group_id), data)
