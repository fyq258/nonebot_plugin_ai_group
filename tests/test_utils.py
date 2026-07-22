from datetime import datetime, timedelta
import importlib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from nonebot_plugin_ai_group.Store import Data
from nonebot_plugin_ai_group.utils import utils

store_module = importlib.import_module("nonebot_plugin_ai_group.Store")


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs = {}

    def add_job(self, func, trigger, **kwargs) -> None:
        self.jobs[kwargs["id"]] = (func, trigger, kwargs)

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def remove_job(self, job_id) -> None:
        del self.jobs[job_id]


def make_message(text: str, created_at: datetime) -> dict:
    return {
        "time": created_at.timestamp(),
        "message": [{"type": "text", "data": {"text": text}}],
        "sender": {"card": "tester", "nickname": "tester"},
    }


def test_parse_summary_period_supports_duration_and_clock_ranges() -> None:
    now = datetime(2026, 7, 22, 12, 0, 30)

    duration = utils.parse_summary_period("1.5h", now)
    since_clock = utils.parse_summary_period("9:52", now)
    clock_range = utils.parse_summary_period("9:52 10:21", now)

    assert duration.start == datetime(2026, 7, 22, 10, 30, 30)
    assert duration.end == now
    assert duration.label == "最近 1.5h"
    assert since_clock.start == datetime(2026, 7, 22, 9, 52)
    assert since_clock.end == now
    assert since_clock.label == "今日 09:52 至现在"
    assert clock_range.start == datetime(2026, 7, 22, 9, 52)
    assert clock_range.end == datetime(2026, 7, 22, 10, 21)
    assert clock_range.label == "今日 09:52-10:21"


@pytest.mark.parametrize(
    "value",
    ["24:00", "9:60", "12:01", "10:21 9:52", "9:52 12:01"],
)
def test_parse_summary_period_rejects_invalid_clock_ranges(value: str) -> None:
    with pytest.raises(ValueError):
        utils.parse_summary_period(value, datetime(2026, 7, 22, 12, 0, 30))


@pytest.mark.parametrize(
    ("value", "seconds"),
    [
        ("1m", 60),
        ("1h", 3600),
        ("1.5h", 5400),
        ("1d", 86400),
        ("2H", 7200),
    ],
)
def test_parse_duration(value: str, seconds: int) -> None:
    assert utils.parse_duration(value).total_seconds() == seconds


@pytest.mark.parametrize("value", ["", "0m", "1", "1w", "-1h", "1.5.2h"])
def test_parse_duration_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        utils.parse_duration(value)


def test_schedule_summary_can_add_update_and_remove(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_scheduler = FakeScheduler()
    monkeypatch.setattr(utils, "scheduler", fake_scheduler)
    data = Data(hour=8, minimum_messages=50)

    utils.schedule_summary(123, data)

    job_id = utils.get_scheduler_job_id(123)
    assert job_id == "ai_group_123"
    assert fake_scheduler.jobs[job_id][2]["hour"] == 8
    assert fake_scheduler.jobs[job_id][2]["args"] == (123, 50)

    utils.remove_summary_schedule(123)
    assert job_id not in fake_scheduler.jobs


def test_store_uses_ai_group_data_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        store_module,
        "get_plugin_data_file",
        lambda filename: tmp_path / filename,
    )
    store_module.Store._instance = None

    try:
        store = store_module.Store()
        assert store.store == tmp_path / "ai_group.json"
    finally:
        store_module.Store._instance = None


@pytest.mark.asyncio
async def test_scheduler_requires_threshold_within_last_24_hours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now()

    class FakeBot:
        async def get_group_msg_history(self, **kwargs):
            return {
                "messages": [
                    make_message("old", now - timedelta(hours=25)),
                    make_message("recent 1", now - timedelta(hours=2)),
                    make_message("recent 2", now - timedelta(hours=1)),
                ]
            }

    summarize = AsyncMock(return_value="summary")
    send = AsyncMock()
    monkeypatch.setattr(utils, "get_bot", lambda: FakeBot())
    monkeypatch.setattr(utils, "messages_summary", summarize)
    monkeypatch.setattr(utils, "send_summary", send)

    await utils.scheduler_send_summary(group_id=123, minimum_messages=3)

    summarize.assert_not_awaited()
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_scheduler_keeps_last_real_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now()
    raw_messages = [
        make_message("first", now - timedelta(hours=3)),
        make_message("second", now - timedelta(hours=2)),
        make_message("last", now - timedelta(hours=1)),
    ]

    class FakeBot:
        async def get_group_msg_history(self, **kwargs):
            return {"messages": raw_messages}

    bot = FakeBot()
    summarize = AsyncMock(return_value="summary")
    send = AsyncMock()
    monkeypatch.setattr(utils, "get_bot", lambda: bot)
    monkeypatch.setattr(utils, "messages_summary", summarize)
    monkeypatch.setattr(utils, "send_summary", send)

    await utils.scheduler_send_summary(group_id=123, minimum_messages=3)

    processed_messages = summarize.await_args.args[0]
    assert processed_messages == [
        {"tester": "first"},
        {"tester": "second"},
        {"tester": "last"},
    ]
    send.assert_awaited_once_with(bot, 123, "summary")


@pytest.mark.asyncio
async def test_duration_history_filters_and_sorts_messages() -> None:
    now = datetime.now()

    class FakeBot:
        async def get_group_msg_history(self, **kwargs):
            return {
                "messages": [
                    make_message("recent 2", now - timedelta(minutes=2)),
                    make_message("old", now - timedelta(hours=2)),
                    make_message("recent 1", now - timedelta(minutes=5)),
                ]
            }

    messages, truncated = await utils.get_group_msg_history_by_duration(
        FakeBot(), group_id=123, duration=timedelta(hours=1)
    )

    assert messages == [
        {"tester": "recent 1"},
        {"tester": "recent 2"},
    ]
    assert truncated is False


@pytest.mark.asyncio
async def test_duration_history_reports_message_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now()

    class FakeBot:
        async def get_group_msg_history(self, **kwargs):
            assert kwargs["count"] == 3
            return {
                "messages": [
                    make_message(str(index), now - timedelta(minutes=index))
                    for index in range(3)
                ]
            }

    monkeypatch.setattr(utils.config, "ai_group_max_messages", 3)

    messages, truncated = await utils.get_group_msg_history_by_duration(
        FakeBot(), group_id=123, duration=timedelta(hours=1)
    )

    assert len(messages) == 3
    assert truncated is True


@pytest.mark.asyncio
async def test_time_range_history_includes_boundaries() -> None:
    day = datetime(2026, 7, 22)

    class FakeBot:
        async def get_group_msg_history(self, **kwargs):
            return {
                "messages": [
                    make_message("after", day.replace(hour=10, minute=22)),
                    make_message("start", day.replace(hour=9, minute=52)),
                    make_message("before", day.replace(hour=9, minute=51)),
                    make_message("end", day.replace(hour=10, minute=21)),
                    make_message("middle", day.replace(hour=10)),
                ]
            }

    messages, truncated = await utils.get_group_msg_history_by_time_range(
        FakeBot(),
        group_id=123,
        start=day.replace(hour=9, minute=52),
        end=day.replace(hour=10, minute=21),
    )

    assert messages == [
        {"tester": "start"},
        {"tester": "middle"},
        {"tester": "end"},
    ]
    assert truncated is False


@pytest.mark.asyncio
async def test_private_summary_is_sent_to_requester() -> None:
    bot = AsyncMock()

    await utils.send_private_summary(bot, 456, " summary ")

    bot.send_private_msg.assert_awaited_once_with(user_id=456, message="summary")


@pytest.mark.asyncio
@pytest.mark.parametrize("private", [True, False])
async def test_summary_falls_back_to_text_when_image_rendering_fails(
    monkeypatch: pytest.MonkeyPatch, private: bool
) -> None:
    bot = AsyncMock()
    render = AsyncMock(side_effect=RuntimeError("render failed"))
    monkeypatch.setattr(utils.config, "ai_group_render_image", True)
    monkeypatch.setattr(utils, "generate_image", render, raising=False)

    if private:
        await utils.send_private_summary(bot, 456, " summary ")
        bot.send_private_msg.assert_awaited_once_with(user_id=456, message="summary")
    else:
        await utils.send_summary(bot, 123, " summary ")
        bot.send_group_msg.assert_awaited_once_with(group_id=123, message="summary")

    render.assert_awaited_once_with(" summary ")


@pytest.mark.asyncio
async def test_group_access_requires_requester_membership() -> None:
    allowed_bot = AsyncMock()
    denied_bot = AsyncMock()
    denied_bot.get_group_member_info.side_effect = RuntimeError("not a member")

    assert await utils.can_user_access_group(allowed_bot, 123, 456) is True
    assert await utils.can_user_access_group(denied_bot, 123, 456) is False
