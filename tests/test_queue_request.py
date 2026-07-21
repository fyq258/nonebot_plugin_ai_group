import asyncio

import pytest
import pytest_asyncio

from nonebot_plugin_ai_group.utils import queue_request


@pytest_asyncio.fixture
async def isolated_queue(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(queue_request, "summary_queue", asyncio.Queue(maxsize=1))
    monkeypatch.setattr(queue_request, "_summary_worker_tasks", [])
    monkeypatch.setattr(queue_request, "_max_workers", 1)

    yield

    tasks = queue_request._summary_worker_tasks
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
async def test_timeout_includes_waiting_for_queue_space(
    isolated_queue, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def do_not_start_workers() -> None:
        return None

    loop = asyncio.get_running_loop()
    occupied_future = loop.create_future()
    await queue_request.summary_queue.put(([], "occupied", occupied_future))
    monkeypatch.setattr(queue_request, "ensure_workers_running", do_not_start_workers)
    monkeypatch.setattr(queue_request.config, "ai_group_request_timeout", 0.01)

    result = await queue_request.queue_summary_request([], "prompt")

    assert result == "总结请求处理超时,请稍后再试。"
    assert queue_request.summary_queue.qsize() == 1
    occupied_future.cancel()


@pytest.mark.asyncio
async def test_timed_out_request_does_not_stop_worker(
    isolated_queue, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate = asyncio.Event()

    class SlowModel:
        async def summary_history(self, messages, prompt):
            await gate.wait()
            return "summary"

    monkeypatch.setattr(queue_request, "model", SlowModel())
    monkeypatch.setattr(queue_request.config, "ai_group_request_timeout", 0.01)

    result = await queue_request.queue_summary_request([], "prompt")
    gate.set()
    await asyncio.sleep(0.01)

    assert result == "总结请求处理超时,请稍后再试。"
    assert len(queue_request._summary_worker_tasks) == 1
    assert not queue_request._summary_worker_tasks[0].done()
