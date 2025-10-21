from dataclasses import dataclass, field
from typing import List, Set, Optional
from pathlib import Path


@dataclass
class Config:
    headless: bool = False
    bypass_csp: bool = True
    window_width: int = 1920  # not used
    window_height: int = 1080  # not used
    fps: int = 30
    chromium_args: List[str] = field(
        default_factory=lambda: [
            "--disable-web-security",
            "--disable-features=TranslateUI",
        ]
    )
    start_url: str = "https://www.amazon.com"
    action_types: Set[str] = field(
        default_factory=lambda: {
            "mouse_move",  # Cursor moved; throttled (~100 ms)
            "click",  # User click (with nearest <a href> if present)
            "scroll_start",  # Scroll began
            "scroll_end",  # Scroll ended (delta + duration)
            "type",  # Text entry into non-password inputs/textarea
            "type_commit",  # Commit of text (Enter or blur)
            "window_focus",  # Window gained focus (page active)
            "window_blur",  # Window lost focus (page inactive)
            "tab_hidden",  # Page became hidden (tab/backgrounded)
            "tab_visible",  # Page became visible (tab/foregrounded)
            "navigation",  # SPA/history navigation (from → to)
            "recorder_init",  # Recorder attached; logs UA/viewport
            "log_error",  # Fallback when logging fails
        }
    )
    init_script = Path("inject.js").read_text(encoding="utf-8")
    # Logging/verbosity
    debug: bool = False  # When False: hide REQUEST_FAILED, BROWSER_* etc.
    video_dir: str = "videos"
    jsonl_dir: str = "logs"
    storage_state_path: Optional[str] = None
