"""Bounded subprocess execution with process-tree cleanup.

All captured output is drained incrementally from OS pipes. Only the final
``max_output_bytes`` of each stream are retained, independent of total output.
"""
from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Mapping, Sequence


class _TailBuffer:
    def __init__(self, limit: int) -> None:
        self.limit = max(0, int(limit))
        self._data = bytearray()
        self._lock = threading.Lock()

    def append(self, chunk: bytes) -> None:
        if not self.limit:
            return
        with self._lock:
            if len(chunk) >= self.limit:
                self._data[:] = chunk[-self.limit:]
            else:
                excess = len(self._data) + len(chunk) - self.limit
                if excess > 0:
                    del self._data[:excess]
                self._data.extend(chunk)

    def text(self) -> str:
        with self._lock:
            return bytes(self._data).decode("utf-8", "replace")


def _group_exists(pid: int) -> bool:
    if os.name == "nt":
        # Windows process groups are not queryable using os.killpg.
        return False
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _terminate_tree(proc: subprocess.Popen[bytes], grace_seconds: float = 0.8) -> None:
    """Terminate the process group/tree, escalate, and reap the direct child."""
    if os.name == "nt":
        # taskkill /T addresses descendants as well as the root process.
        try:
            killer = subprocess.Popen(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            killer.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            try:
                proc.kill()
            except OSError:
                pass
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError:
            try:
                proc.terminate()
            except OSError:
                pass

        deadline = time.monotonic() + grace_seconds
        while time.monotonic() < deadline:
            if not _group_exists(proc.pid):
                break
            time.sleep(0.025)
        if _group_exists(proc.pid):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                try:
                    proc.kill()
                except OSError:
                    pass

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except OSError:
            pass
        proc.wait()


def run_process(
    args: Sequence[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    stderr_to_stdout: bool = False,
    max_output_bytes: int = 16_384,
) -> subprocess.CompletedProcess[str]:
    """Run argv without shell expansion and retain bounded stdout/stderr tails.

    ``subprocess.TimeoutExpired`` is raised on timeout with the bounded tails
    attached as text in ``output`` and ``stderr``. The process group is stopped
    before the exception is propagated.
    """
    argv = list(args)
    stdout_tail = _TailBuffer(max_output_bytes)
    stderr_tail = _TailBuffer(max_output_bytes)

    creationflags = 0
    popen_options: dict[str, object] = {}
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        popen_options["start_new_session"] = True

    proc = subprocess.Popen(
        argv,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if stderr_to_stdout else subprocess.PIPE,
        bufsize=0,
        creationflags=creationflags,
        **popen_options,
    )

    readers: list[threading.Thread] = []

    def drain(stream, target: _TailBuffer) -> None:
        try:
            while True:
                chunk = os.read(stream.fileno(), 64 * 1024)
                if not chunk:
                    return
                target.append(chunk)
        except (OSError, ValueError):
            return

    assert proc.stdout is not None
    readers.append(threading.Thread(target=drain, args=(proc.stdout, stdout_tail), daemon=True,
                                     name=f"publisher-stdout-{proc.pid}"))
    if not stderr_to_stdout:
        assert proc.stderr is not None
        readers.append(threading.Thread(target=drain, args=(proc.stderr, stderr_tail), daemon=True,
                                         name=f"publisher-stderr-{proc.pid}"))
    for reader in readers:
        reader.start()

    try:
        returncode = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        _terminate_tree(proc)
        for reader in readers:
            reader.join(timeout=1.0)
        # Close the parent-side pipe handles on every timeout path. The child
        # tree has already been stopped; closing here prevents ResourceWarning
        # leaks and releases descriptors even if a reader did not observe EOF.
        for stream in (proc.stdout, proc.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        for reader in readers:
            reader.join(timeout=0.5)
        out, err = stdout_tail.text(), stderr_tail.text()
        raise subprocess.TimeoutExpired(argv, timeout, output=out, stderr=err) from exc

    # A descendant that inherited the pipes must not hold the caller open
    # indefinitely after the direct child exits. Give the streams a bounded
    # drain window, then stop the remaining group and close the descriptors.
    for reader in readers:
        reader.join(timeout=2.0)
    if any(reader.is_alive() for reader in readers):
        _terminate_tree(proc)
    for stream in (proc.stdout, proc.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError:
                pass
    for reader in readers:
        reader.join(timeout=0.5)

    return subprocess.CompletedProcess(argv, returncode, stdout_tail.text(),
                                        "" if stderr_to_stdout else stderr_tail.text())
