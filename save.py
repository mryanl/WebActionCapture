import json, threading, queue, os
from typing import Optional


class LogPump:
    """
    Background, non-blocking printer so Playwright's event loop never waits on stdout.
    """

    def __init__(self):
        self.q: "queue.Queue[Optional[str]]" = queue.Queue(maxsize=10000)
        self._stop = threading.Event()
        self.t = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self.t.start()

    def stop(self, timeout: float = 1.0):
        self._stop.set()
        try:
            self.q.put_nowait(None)
        except Exception:
            pass
        self.t.join(timeout=timeout)

    def put(self, line: str):
        try:
            self.q.put_nowait(line)
        except queue.Full:
            # Drop if overwhelmed; better than blocking Playwright thread
            pass

    def _run(self):
        while not self._stop.is_set():
            try:
                item = self.q.get(timeout=0.25)
            except queue.Empty:
                continue
            if item is None:
                break
            print(item, flush=True)


class JsonlWriter:
    """
    Threaded, non-blocking JSONL writer.
    Accepts Python dicts and appends compact JSON per line.
    """

    def __init__(self, out_dir: str, filename: str):
        self.out_dir = out_dir
        self.filename = filename
        self.q: "queue.Queue[Optional[dict]]" = queue.Queue(maxsize=10000)
        self._stop = threading.Event()
        self.t = threading.Thread(target=self._run, daemon=True)
        # Ensure dir exists
        if out_dir and not os.path.exists(out_dir):
            os.makedirs(out_dir, exist_ok=True)

    def start(self):
        self.t.start()

    def stop(self, timeout: float = 1.0):
        self._stop.set()
        try:
            self.q.put_nowait(None)
        except Exception:
            pass
        self.t.join(timeout=timeout)

    def put(self, obj: dict):
        try:
            self.q.put_nowait(obj)
        except queue.Full:
            # Drop rather than block
            pass

    def _run(self):
        # Open once and append lines
        with open(
            os.path.join(self.out_dir, f"{self.filename}.jsonl"), "a", encoding="utf-8"
        ) as f:
            while not self._stop.is_set():
                try:
                    item = self.q.get(timeout=0.25)
                except queue.Empty:
                    continue
                if item is None:
                    break
                try:
                    line = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
                    f.write(line + "\n")
                    f.flush()
                    os.fsync(f.fileno())
                except Exception:
                    # Swallow writer errors to avoid crashing the recorder thread
                    pass
