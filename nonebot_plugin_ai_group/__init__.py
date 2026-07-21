from arclet.alconna import AllParam
from nonebot import get_driver, require
from nonebot.adapters.onebot.v11 import (
    Bot,
    Event,
    GroupMessageEvent,
    PrivateMessageEvent,
)
from nonebot.permission import SUPERUSER
from nonebot.plugin import PluginMetadata

from .Config import Config, config
from .Store import Data, Store
from .utils.utils import (
    can_user_access_group,
    get_group_msg_history,
    get_group_msg_history_by_duration,
    messages_summary,
    parse_duration,
    remove_summary_schedule,
    schedule_summary,
    send_private_summary,
    send_summary,
    set_scheduler,
    validate_cool_down,
    validate_group_event,
    validate_message_count,
    validate_summary_event,
)

require("nonebot_plugin_alconna")
from nonebot_plugin_alconna import (  # noqa: E402
    Alconna,
    Args,
    CommandMeta,
    Match,
    on_alconna,
)
from nonebot_plugin_alconna.uniseg.segment import At  # noqa: E402

__plugin_meta__ = PluginMetadata(
    name="AI 群聊总结",
    description="使用 AI 分析群聊记录，支持群内按条数和私聊按时间段总结。",
    usage=(
        "1.群聊：/总结 [消息数量] [内容]\n"
        "2.私聊：/总结 [群号] [时间段]，例如：/总结 855634423 10m\n"
        "3./总结定时 [时间] [最少消息数量]\n"
        "4./总结定时取消"
    ),
    type="application",
    homepage="https://github.com/fyq258/nonebot_plugin_ai_group",
    config=Config,
    supported_adapters={"~onebot.v11"},
)


def resolve_command_prefixes(
    command_start: set[str], require_prefix: bool
) -> list[str]:
    prefixes = sorted(prefix for prefix in command_start if prefix)
    if not prefixes:
        prefixes = ["/"]
    if not require_prefix:
        prefixes.append("")
    return prefixes


driver = get_driver()
command_prefixes = resolve_command_prefixes(
    set(driver.config.command_start),
    config.ai_group_require_command_prefix,
)

summary = on_alconna(
    Alconna(
        command_prefixes,
        "总结",
        Args["target", int],
        Args["parameter", AllParam, None],
        meta=CommandMeta(
            compact=True,
            description="在群聊按消息数总结，或在私聊按群号和时间段总结",
            usage=(
                "群聊：/总结 [消息数量] [内容]\n"
                "私聊：/总结 [群号] [时间段]\n"
                "时间段支持 1m、1h、1.5h、1d"
            ),
        ),
    ),
    rule=validate_summary_event,
    priority=5,
    block=True,
)
summary_set = on_alconna(
    Alconna(
        command_prefixes,
        "总结定时",
        Args[
            "time",
            "re:(0?[0-9]|1[0-9]|2[0-3])",
        ],
        Args["minimum_messages", int, config.ai_group_max_messages],
        meta=CommandMeta(
            compact=True,
            description="定时生成消息数量的内容总结",
            usage="/总结定时 [时间] [最少消息数量]\n时间：0~23\n最少消息数量：默认为单次最大消息数",
        ),
    ),
    rule=validate_group_event,
    priority=5,
    block=True,
    permission=SUPERUSER,
)

summary_remove = on_alconna(
    Alconna(
        command_prefixes,
        "总结定时取消",
        meta=CommandMeta(
            description="取消本群的定时内容总结",
            usage="/总结定时取消",
        ),
    ),
    rule=validate_group_event,
    priority=5,
    block=True,
    permission=SUPERUSER,
)


@driver.on_startup
async def subscribe_jobs():
    set_scheduler()


def extract_plain_text(value: object | None) -> str:
    if value is None:
        return ""

    segments = value if isinstance(value, (list, tuple)) else [value]
    parts: list[str] = []
    for segment in segments:
        if isinstance(segment, str):
            parts.append(segment)
        elif hasattr(segment, "text"):
            parts.append(str(segment.text))
        else:
            parts.append(str(segment))
    return "".join(parts).strip()


@summary.handle()
async def _(
    bot: Bot,
    event: Event,
    target: Match[int],
    parameter: Match[object],
):
    target_get = target.result

    if isinstance(event, PrivateMessageEvent):
        duration_text = extract_plain_text(parameter.result)
        try:
            duration = parse_duration(duration_text)
        except ValueError:
            await summary.finish("时间格式不正确，请使用 1m、1h、1.5h、1d 这样的格式。")

        if not await can_user_access_group(bot, target_get, event.user_id):
            await summary.finish("无法读取该群。请确认你和机器人都在目标群中。")

        if cool_time := validate_cool_down(event.user_id):
            await summary.finish(f"请等待 {cool_time} 秒后再次使用。")

        try:
            messages, truncated = await get_group_msg_history_by_duration(
                bot, target_get, duration
            )
        except Exception:
            await summary.finish("获取群聊记录失败，请确认群号和机器人权限。")

        if not messages:
            await summary.finish("该时间段内没有可总结的文本消息。")

        summary_text = await messages_summary(messages)
        limit_notice = (
            f"> 该时间段消息达到 {config.ai_group_max_messages} 条读取上限，"
            "更早的消息可能未包含。\n\n"
            if truncated
            else ""
        )
        result = (
            f"## 群 {target_get} 最近 {duration_text.lower()} 的总结\n\n"
            f"{limit_notice}{summary_text}"
        )
        await send_private_summary(bot, event.user_id, result)
        return

    if not isinstance(event, GroupMessageEvent):
        return

    message_count_get = target_get
    if content_get := parameter.result:
        # 将内容转换为消息段列表
        text_parts = []
        segments = (
            content_get if isinstance(content_get, (list, tuple)) else [content_get]
        )

        # 获取群成员信息将@转换为昵称
        for seg in segments:
            if isinstance(seg, At):
                try:
                    info = await bot.get_group_member_info(
                        group_id=event.group_id, user_id=int(seg.target)
                    )
                    text_parts.append(
                        f"@{info.get('card') or info.get('nickname', seg.target)}"
                    )
                except Exception:
                    # 如果获取群成员信息失败，直接使用QQ号
                    text_parts.append(f"@{seg.target}")
            elif isinstance(seg, str):
                # 只有当字符串不为空且不只包含空白字符时才添加
                stripped = seg.strip()
                if stripped:
                    text_parts.append(stripped)
            elif hasattr(seg, "target"):  # 处理其他可能的@类型消息段
                text_parts.append(f"@{seg.target}")
            elif hasattr(seg, "text"):  # 处理其他可能的文本类型消息段
                stripped = str(seg.text).strip()
                if stripped:
                    text_parts.append(stripped)
            else:
                # 其他类型的消息段，尝试转换为字符串
                try:
                    text = str(seg).strip()
                    if text:
                        text_parts.append(text)
                except Exception:
                    continue
        content_get = "".join(text_parts).strip()

    # 消息数量检查
    if not validate_message_count(message_count_get):
        await summary.finish(
            f"总结消息数量应在 {config.ai_group_min_messages} 到 "
            f"{config.ai_group_max_messages} 之间。",
            at_sender=True,
        )

    # 冷却时间，针对人，而非群
    if cool_time := validate_cool_down(event.user_id):
        await summary.finish(f"请等待 {cool_time} 秒后再次使用。", at_sender=True)

    group_id = event.group_id
    messages = await get_group_msg_history(bot, group_id, message_count_get)
    if not messages:
        await summary.finish("未能获取到聊天记录。", at_sender=True)

    summary_text = await messages_summary(messages, content_get)
    await send_summary(bot, group_id, summary_text)


@summary_set.handle()
async def _(
    event: GroupMessageEvent,
    time: Match[str],
    minimum_messages: Match[int],
):
    group_id = event.group_id
    minimum_messages_get = minimum_messages.result
    if not validate_message_count(minimum_messages_get):
        await summary_set.finish(
            f"最低消息数量应在 {config.ai_group_min_messages} 到 "
            f"{config.ai_group_max_messages} 之间。",
            at_sender=True,
        )

    store = Store()
    data = Data(hour=int(time.result), minimum_messages=minimum_messages_get)
    store.set(group_id, data)
    schedule_summary(group_id, data)
    await summary_set.finish(
        f"已设置定时总结，将在每天 {time.result} 时检查最近 24 小时消息，"
        f"达到 {minimum_messages_get} 条时生成总结。",
        at_sender=True,
    )


@summary_remove.handle()
async def _(event: GroupMessageEvent):
    group_id = event.group_id
    store = Store()
    store.remove(group_id)
    remove_summary_schedule(group_id)
    await summary_remove.finish("已取消本群定时总结。", at_sender=True)
