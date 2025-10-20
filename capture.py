from playwright.sync_api import sync_playwright, Browser
import time, uuid, json
from dataclasses import dataclass, field
from typing import List, Set
from pathlib import Path
from playwright._impl._errors import TargetClosedError
from video import FFmpegFullScreenRecorder
from save import LogPump, JsonlWriter
from config import Config
import platform


class Recorder:
    def __init__(self, config: Config):
        self.config = config
        self.page_ids = {}
        self.basename: str = str(uuid.uuid4())[:8]
        self.ts = int(time.time())
        self.pump = LogPump()
        self.jsonl = JsonlWriter(self.config.jsonl_dir, f"{self.basename}_{self.ts}")
        self.screen_rec = None

    def set_window_state(
        self, page, state="maximized"
    ):  # "fullscreen" or "maximized" or "normal"
        cdp = page.context.new_cdp_session(page)
        wid = cdp.send("Browser.getWindowForTarget")["windowId"]
        cdp.send(
            "Browser.setWindowBounds",
            {"windowId": wid, "bounds": {"windowState": state}},
        )
        page.bring_to_front()

    def _emit_event(self, pid: str, obj: dict):
        """
        Enrich and send the event to both stdout ([BROWSER_LOG] line) and JSONL.
        """
        # Shallow-copy to avoid mutating original dict if reused
        evt = dict(obj)
        # Normalize timestamp
        ts = evt.get("ts")
        if isinstance(ts, (int, float)) and ts > 1e10:  # detect ms epoch
            evt["ts"] = round(ts / 1000.0, 6)

        self.jsonl.put(evt)

        # Also emit the compact JSON on stdout (the same structure)
        payload = json.dumps(evt, ensure_ascii=False, separators=(",", ":"))
        self.pump.put(f"[BROWSER_LOG] [{pid}] {payload}")

    def _pid(self, page):
        return self.page_ids.setdefault(page, str(uuid.uuid4())[:8])

    def _wire(self, page):
        pid = self.page_ids.setdefault(page, str(uuid.uuid4())[:8])

        def _on_console(msg):
            text = msg.text or ""
            if not text or text[0] != "{":
                if self.config.debug:
                    self.pump.put(
                        f"[BROWSER_{(msg.type or '').upper()}] [{pid}] {text}"
                    )
                return
            try:
                obj = json.loads(text)
            except Exception:
                if self.config.debug:
                    self.pump.put(f"[BROWSER_PARSE_ERR] [{pid}] {text}")
                return

            if obj.get("__rec") == 1 and obj.get("type") in self.config.action_types:
                obj.pop("__rec", None)  # remove marker
                # (optional) redact long input values
                if obj.get("type") in {"type", "type_commit"} and isinstance(
                    obj.get("value"), str
                ):
                    v = obj["value"]
                    obj["value"] = v if len(v) <= 120 else (v[:117] + "…")
                self._emit_event(pid, obj)
            elif self.config.debug:
                self.pump.put(f"[BROWSER_OTHER] [{pid}] {text}")

        def _on_popup(p):
            self._wire(p)

        page.on("console", _on_console)
        page.on("popup", _on_popup)

    def start(self):
        self.pump.start()
        self.jsonl.start()

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=self.config.headless, args=self.config.chromium_args
                )

                context = browser.new_context(
                    viewport=None,
                    no_viewport=True,
                    bypass_csp=config.bypass_csp,
                )

                context.add_init_script(self.config.init_script)

                for pg in context.pages:
                    self._wire(pg)
                context.on("page", lambda pg: self._wire(pg))

                page = context.new_page()
                self.set_window_state(page)
                # self._wire(page)
                page.goto(self.config.start_url, wait_until="domcontentloaded")

                # --- Start video as soon as we can get stable bounds ---
                try:
                    self.screen_rec = FFmpegFullScreenRecorder(
                        out_dir=self.config.video_dir,
                        filename=f"{self.basename}_{self.ts}",
                        codec_preference="hevc",
                        fps=self.config.fps,
                    )
                    ffmpeg_start = time.time()
                    self.screen_rec.start()
                    self.pump.put(
                        f"[RECORDER] Full-screen recording started → {self.screen_rec.out_path}"
                    )
                except Exception as e:
                    self.pump.put(f"[RECORDER] Failed to start screen recording: {e}")

                while browser.is_connected():
                    pgs = context.pages
                    if pgs:
                        # this is a Playwright call; it pumps events without doing anything visible
                        try:
                            pgs[0].wait_for_timeout(100)  # ~100 ms
                        except TargetClosedError:
                            break  # exit when browser is closed

                    else:
                        time.sleep(0.1)

        finally:
            if self.screen_rec:
                try:
                    outp = self.screen_rec.stop()
                    self.pump.put(
                        f"[RECORDER] Video started at {ffmpeg_start} saved: {outp}"
                    )
                except Exception as e:
                    self.pump.put(f"[RECORDER] Video stop failed: {e}")
            # Ensure pump stops
            self.pump.stop()
            self.jsonl.stop()
            print("exit", flush=True)


if __name__ == "__main__":
    start_url = "https://www.amazon.com/"
    action_types = {
        "action_types",
        "click",
        "scroll_start",
        "scroll_end",
        "type",
        "type_commit",
        "tab_hidden",
        "navigation",
        "recorder_init",
    }

    system = platform.system()

    if system == "Windows":
        print("Running on Windows")
        config = Config(
            headless=False,
            bypass_csp=True,
            start_url=start_url,
            # action_types=action_types,
            debug=False,
        )
    elif system == "Darwin":
        print("Running on macOS")
        config = Config(
            headless=False,
            bypass_csp=True,
            fps=60,
            start_url=start_url,
            # action_types=action_types,
            debug=False,
        )
    else:
        print(f"Unsupported platform: {system}")
        exit(1)

    config = Config(
        headless=False,
        bypass_csp=True,
        debug=False,
    )
    Recorder(config).start()
