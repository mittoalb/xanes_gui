"""Publish a running scan's status to the shared beamline registry.

Scans (XANES 1D, XANES 2D, …) report what they are
doing to ``~/.aps_agents/agents.json`` — the same file pystream's Agents
panel and the read-only Slack bot read — so "is a scan running, which
one, how far along, where is the data going" can be answered from
anywhere.

Never raises and never blocks a scan (writes happen on a background
thread): if ``beamline-agent`` isn't
installed or the registry can't be written, every call is a no-op.

    st = ScanStatus("2D Time Series", total=n_frames, file=path)
    for i in range(n_frames):
        ...
        st.step(i + 1, text=f"frame {i + 1}/{n_frames}")
    st.finish(f"{n_frames} frames → {path}")      # or st.error(...) /
                                                  #    st.aborted()
"""

from __future__ import annotations

import atexit
import logging
import queue
import threading

LOGGER = logging.getLogger(__name__)

# All registry writes (a JSON file in the NFS home directory) happen on
# ONE background thread, in order. The scan thread only enqueues, so a
# slow or hung NFS can never stall an acquisition or its cleanup.
_q: "queue.Queue" = queue.Queue()
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


def _run_queue():
    while True:
        fn = _q.get()
        try:
            fn()
        except Exception as ex:              # never kill the writer thread
            LOGGER.debug("scan status write failed: %s", ex)
        finally:
            _q.task_done()


def _drain_at_exit(timeout: float = 3.0):
    """Give pending writes (e.g. the final 'done') a moment at exit so a
    command-line scan doesn't leave its record stuck at 'running'."""
    import time
    deadline = time.monotonic() + timeout
    while _q.unfinished_tasks and time.monotonic() < deadline:
        time.sleep(0.05)


def _submit(fn):
    global _worker
    with _worker_lock:
        if _worker is None:
            _worker = threading.Thread(target=_run_queue, daemon=True,
                                       name="scan-status-writer")
            _worker.start()
            atexit.register(_drain_at_exit)
    _q.put(fn)


class ScanStatus:
    def __init__(self, name: str, total: int | None = None, **info):
        self._pub = None
        self._total = total

        def create():
            try:
                from beamline_agent.status import scan_publisher
            except Exception as ex:      # beamline-agent not installed
                LOGGER.debug("scan status disabled: %s", ex)
                return
            self._pub = scan_publisher(name, **info)
            self._pub.activity("starting")
            if total:
                self._pub.progress(0, total)
        _submit(create)

    def _call(self, method: str, *args, **kw) -> None:
        def run():
            if self._pub is not None:
                getattr(self._pub, method)(*args, **kw)
        _submit(run)

    def step(self, done: int, total: int | None = None, text: str = "") -> None:
        """Progress update: `done` of `total` (defaults to the total
        given at construction)."""
        total = total if total is not None else self._total
        if total:
            self._call("progress", done, total, text)
        elif text:
            self._call("activity", text)

    def activity(self, text: str) -> None:
        """Free-text "what it's doing now" (e.g. "taking flat field")."""
        self._call("activity", text)

    def info(self, **fields) -> None:
        """Update details such as the output file or current energy."""
        self._call("set_info", **fields)

    def finish(self, summary: str = "") -> None:
        self._call("finish", summary)

    def aborted(self, text: str = "stopped by user") -> None:
        self._call("finish", f"aborted: {text}")

    def error(self, text: str) -> None:
        self._call("error", text)
