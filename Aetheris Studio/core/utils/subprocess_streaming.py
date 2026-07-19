"""Run an already-spawned subprocess to completion, streaming stdout/stderr
into memory (not real streaming to the caller -- collected in full, then
returned) with an optional periodic progress callback and a hard timeout
that kills the process if it runs too long.
"""

import asyncio
import collections
import time
from typing import Awaitable, Callable, Dict, Optional, Tuple

PROGRESS_INTERVAL_SECONDS = 2.0
PROGRESS_TAIL_LINES = 12


async def run_subprocess_streaming(
    proc: asyncio.subprocess.Process,
    *,
    timeout: float,
    progress_cb: Optional[Callable[[Dict], Awaitable[None]]] = None,
) -> Tuple[str, str, Optional[int], bool]:
    """Returns (stdout, stderr, exit_code, timed_out)."""
    started = time.time()
    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    tail: collections.deque = collections.deque(maxlen=PROGRESS_TAIL_LINES)

    async def read_stream(stream, sink: list, is_stderr: bool):
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            decoded = line.decode("utf-8", errors="replace").rstrip("\n")
            sink.append(decoded)
            tail.append(f"! {decoded}" if is_stderr else decoded)

    async def emit_progress():
        await asyncio.sleep(PROGRESS_INTERVAL_SECONDS)
        while True:
            if progress_cb:
                try:
                    await progress_cb({"elapsed_s": round(time.time() - started, 1), "tail": "\n".join(tail)})
                except Exception:
                    pass
            await asyncio.sleep(PROGRESS_INTERVAL_SECONDS)

    stdout_task = asyncio.create_task(read_stream(proc.stdout, stdout_lines, False))
    stderr_task = asyncio.create_task(read_stream(proc.stderr, stderr_lines, True))
    progress_task = asyncio.create_task(emit_progress()) if progress_cb else None

    timed_out = False
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        timed_out = True
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except Exception:
            pass
    except asyncio.CancelledError:
        proc.kill()
        try:
            await asyncio.wait_for(proc.wait(), timeout=2)
        except Exception:
            pass
        for task in (stdout_task, stderr_task, progress_task):
            if task is not None:
                task.cancel()
        raise
    finally:
        if progress_task is not None and not progress_task.done():
            progress_task.cancel()
            try:
                await progress_task
            except (asyncio.CancelledError, Exception):
                pass
        for task in (stdout_task, stderr_task):
            try:
                await asyncio.wait_for(task, timeout=1)
            except Exception:
                pass

    return "\n".join(stdout_lines), "\n".join(stderr_lines), proc.returncode, timed_out
