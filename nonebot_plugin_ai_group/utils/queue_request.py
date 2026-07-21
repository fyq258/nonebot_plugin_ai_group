# 创建总结请求队列
import asyncio

from ..Config import config
from ..Model import detect_model

SummaryRequest = tuple[list[dict[str, str]], str, asyncio.Future[str]]

summary_queue: asyncio.Queue[SummaryRequest] = asyncio.Queue(
    maxsize=config.summary_max_queue_size
)
_summary_worker_tasks: list[asyncio.Task[None]] = []
_max_workers = config.summary_queue_workers

model = detect_model()


async def _process_summary_worker():
    """处理总结请求队列的工作线程"""
    while True:
        # 从队列获取任务
        messages, prompt, future = await summary_queue.get()
        try:
            if future.cancelled():
                continue

            # 调用实际的总结方法
            result = await model.summary_history(messages, prompt)
            # 设置结果
            if not future.done():
                future.set_result(result)
        except Exception as e:
            # 如果发生错误，将异常传播回调用方
            if not future.done():
                future.set_exception(e)
        finally:
            # 标记任务完成
            summary_queue.task_done()


async def ensure_workers_running():
    """确保工作线程池正常运行"""
    global _summary_worker_tasks

    # 清理已完成的任务
    _summary_worker_tasks = [task for task in _summary_worker_tasks if not task.done()]

    # 创建新的工作线程，确保始终有指定数量的工作线程运行
    while len(_summary_worker_tasks) < _max_workers:
        task = asyncio.create_task(_process_summary_worker())
        _summary_worker_tasks.append(task)


async def queue_summary_request(messages: list[dict[str, str]], prompt: str) -> str:
    """将总结请求加入队列并等待结果"""
    # 确保工作线程池正常运行
    await ensure_workers_running()

    # 创建Future对象以获取结果
    future = asyncio.get_running_loop().create_future()

    async def enqueue_and_wait() -> str:
        await summary_queue.put((messages, prompt, future))
        return await future

    try:
        # 超时覆盖等待队列空位和模型处理的全部时间
        return await asyncio.wait_for(
            enqueue_and_wait(), timeout=config.summary_queue_timeout
        )
    except asyncio.TimeoutError:
        if not future.done():
            future.cancel()
        return "总结请求处理超时,请稍后再试。"
    except Exception as e:
        return f"总结请求处理失败, {e}"
