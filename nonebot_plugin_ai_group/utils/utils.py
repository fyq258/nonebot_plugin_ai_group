import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from math import ceil
from pathlib import Path
import re

from nonebot import get_bot, require
from nonebot.adapters.onebot.v11 import (
    Bot,
    GroupMessageEvent,
    Message,
    MessageSegment,
    PrivateMessageEvent,
)
from nonebot.log import logger

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


if config.ai_group_render_image:
    require("nonebot_plugin_htmlrender")
    from nonebot_plugin_htmlrender import md_to_pic  # type: ignore

    async def generate_image(summary: str) -> bytes:
        return await md_to_pic(summary, css_path=str(get_css_path()))


cool_down = defaultdict(lambda: datetime.now())
duration_pattern = re.compile(r"^(\d+(?:\.\d+)?)([mhd])$", re.IGNORECASE)
duration_seconds = {
    "m": Decimal(60),
    "h": Decimal(60 * 60),
    "d": Decimal(24 * 60 * 60),
}
clock_pattern = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


@dataclass(frozen=True)
class SummaryPeriod:
    start: datetime
    end: datetime
    label: str


def validate_group_event(event) -> bool:
    return isinstance(event, GroupMessageEvent)


def validate_summary_event(event) -> bool:
    return isinstance(event, (GroupMessageEvent, PrivateMessageEvent))


def parse_duration(value: str) -> timedelta:
    """解析 1m、1h、1.5h、1d 格式的时间段。"""
    match = duration_pattern.fullmatch(value.strip())
    if match is None:
        raise ValueError("时间格式无效")

    amount = Decimal(match.group(1))
    if amount <= 0:
        raise ValueError("时间必须大于 0")

    seconds = amount * duration_seconds[match.group(2).lower()]
    try:
        return timedelta(seconds=float(seconds))
    except OverflowError as error:
        raise ValueError("时间范围过大") from error


def parse_summary_period(value: str, now: datetime | None = None) -> SummaryPeriod:
    """解析相对时长或当天的 HH:MM 时间区间。"""
    current = now or datetime.now()
    normalized = value.strip()

    try:
        duration = parse_duration(normalized)
    except ValueError:
        duration = None

    if duration is not None:
        try:
            start = current - duration
        except OverflowError as error:
            raise ValueError("时间范围过大") from error
        return SummaryPeriod(start, current, f"最近 {normalized.lower()}")

    values = normalized.split()
    if len(values) not in (1, 2):
        raise ValueError("时间格式无效")

    def parse_clock(clock: str) -> datetime:
        match = clock_pattern.fullmatch(clock)
        if match is None:
            raise ValueError("时间格式无效")
        return current.replace(
            hour=int(match.group(1)),
            minute=int(match.group(2)),
            second=0,
            microsecond=0,
        )

    start = parse_clock(values[0])
    end = current if len(values) == 1 else parse_clock(values[1])
    if end > current:
        raise ValueError("结束时间不能晚于当前时间")
    if start >= end:
        raise ValueError("开始时间必须早于结束时间")

    label = (
        f"今日 {start:%H:%M} 至现在"
        if len(values) == 1
        else f"今日 {start:%H:%M}-{end:%H:%M}"
    )
    return SummaryPeriod(start, end, label)


def validate_message_count(num: int) -> bool:
    """验证消息数量是否在合法范围内"""
    return config.ai_group_min_messages <= num <= config.ai_group_max_messages


def validate_cool_down(user_id: int) -> bool | int:
    """验证是否冷却"""
    if config.ai_group_cooldown > 0:
        if (last_time := cool_down[user_id]) > datetime.now():
            return ceil((last_time - datetime.now()).total_seconds())
        cool_down[user_id] = datetime.now() + timedelta(
            seconds=config.ai_group_cooldown
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
    messages.sort(key=lambda message: message["time"])

    return await process_message(messages, bot, group_id, remove_last_message=True)


async def can_user_access_group(bot: Bot, group_id: int, user_id: int) -> bool:
    """确认私聊请求者是目标群成员，并且机器人能够访问该群。"""
    try:
        await bot.get_group_member_info(group_id=group_id, user_id=user_id)
    except Exception:
        return False
    return True


async def get_group_msg_history_by_duration(
    bot: Bot,
    group_id: int,
    duration: timedelta,
) -> tuple[list[dict[str, str]], bool]:
    """获取指定时间范围的群消息，并返回是否可能因数量上限而截断。"""
    now = datetime.now()
    return await get_group_msg_history_by_time_range(
        bot,
        group_id,
        now - duration,
        now,
    )


async def get_group_msg_history_by_time_range(
    bot: Bot,
    group_id: int,
    start: datetime,
    end: datetime,
) -> tuple[list[dict[str, str]], bool]:
    """获取指定起止时间内的群消息，并返回是否可能因数量上限而截断。"""
    limit = config.ai_group_max_messages
    messages = (await bot.get_group_msg_history(group_id=group_id, count=limit))[
        "messages"
    ]
    messages.sort(key=lambda message: message["time"])

    start_timestamp = start.timestamp()
    end_timestamp = end.timestamp()
    truncated = (
        len(messages) >= limit
        and bool(messages)
        and messages[0]["time"] >= start_timestamp
    )
    messages = [
        message
        for message in messages
        if start_timestamp <= message["time"] <= end_timestamp
    ]

    return await process_message(messages, bot, group_id), truncated


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


async def build_summary_message(summary: str) -> str | Message:
    """按配置生成总结消息，图片渲染失败时降级为文本。"""
    text = summary.strip()
    if not config.ai_group_render_image:
        return text

    try:
        img = await generate_image(summary)
        return Message(MessageSegment.image(img))
    except Exception:
        logger.exception("总结图片渲染失败，将改为发送文本。")
        return text


async def send_summary(bot: Bot, group_id: int, summary: str) -> None:
    """发送总结"""
    message = await build_summary_message(summary)
    await bot.send_group_msg(group_id=group_id, message=message)


async def send_private_summary(bot: Bot, user_id: int, summary: str) -> None:
    """向私聊请求者发送总结。"""
    message = await build_summary_message(summary)
    await bot.send_private_msg(user_id=user_id, message=message)


async def scheduler_send_summary(group_id: int, minimum_messages: int):
    """最近 24 小时消息数达到阈值时发送定时总结。"""
    bot = get_bot()
    messages = (
        await bot.get_group_msg_history(group_id=group_id, count=minimum_messages)
    )["messages"]
    messages.sort(key=lambda message: message["time"])

    deadline = (datetime.now() - timedelta(hours=24)).timestamp()
    messages = [message for message in messages if message["time"] > deadline]

    if len(messages) < minimum_messages:
        return

    messages = await process_message(messages, bot, group_id)  # type: ignore
    if not messages:
        return

    summary = await messages_summary(messages)

    await send_summary(bot, group_id, summary)  # type: ignore


def get_scheduler_job_id(group_id: int) -> str:
    return f"ai_group_{group_id}"


def schedule_summary(group_id: int, data: Data) -> None:
    """新增或更新一个群的定时总结任务。"""
    scheduler.add_job(
        scheduler_send_summary,
        "cron",
        hour=data["hour"],
        args=(group_id, data["minimum_messages"]),
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
