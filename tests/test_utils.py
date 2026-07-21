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
