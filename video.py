import os, platform, subprocess, time, shutil, signal, re
from typing import Optional, List


class FFmpegFullScreenRecorder:
    """
    Full-screen recorder using ffmpeg.
      - Windows: gdigrab (captures entire desktop, mouse always on)
      - macOS:   avfoundation ("<screen_index>:none") with cursor capture flags
    Auto-selects GPU encoder when available; else falls back to CPU.
    """

    def __init__(
        self,
        out_dir: str = "videos",
        filename: str = "screen",
        fps: int = 30,
        bitrate: str = "8M",
        preset: str = "fast",
        screen_index: int = None,  # set to None to obtain screen_index automatically
        codec_preference: str = "h264",  # "h264" or "hevc"
        pix_fmt: str = "yuv420p",
        extra_filters: Optional[str] = None,  # e.g., "scale=1920:1080"
        use_genpts: bool = True,
    ):
        self.system = platform.system()
        if self.system not in ("Windows", "Darwin"):
            raise RuntimeError("This recorder currently supports Windows and macOS.")

        self.ffmpeg = shutil.which("ffmpeg")
        if not self.ffmpeg:
            raise RuntimeError("ffmpeg not found on PATH.")

        os.makedirs(out_dir, exist_ok=True)
        self.out_path = os.path.abspath(os.path.join(out_dir, f"{filename}.mp4"))
        self.log_path = os.path.abspath(os.path.join(out_dir, f"{filename}.log"))

        # Choose encoder according to availability
        enc = self._pick_encoder(codec_preference)
        vcodec = enc["name"]

        # Build platform-specific input (no audio anywhere; mouse always included)
        if self.system == "Windows":
            # gdigrab always includes mouse via -draw_mouse 1
            input_args = [
                "-f",
                "gdigrab",
                "-framerate",
                str(fps),
                "-draw_mouse",
                "1",
                "-rtbufsize",
                "200M",
                "-probesize",
                "10M",
                "-use_wallclock_as_timestamps",
                "1",
                "-i",
                "desktop",
                "-fps_mode",
                "cfr",
            ]
            vf = []  # typically not needed on Windows unless you want scaling
        else:
            # macOS: avfoundation, must specify ":none" to avoid audio input
            # Try to capture cursor
            if screen_index is None:
                screen_index = self._auto_screen_index_mac()

            input_args = [
                "-f",
                "avfoundation",
                "-framerate",
                str(fps),
                "-capture_cursor",
                "1",
                "-capture_mouse_clicks",
                "0",
                "-i",
                f"{screen_index}:none",
                "-fps_mode",
                "cfr",
            ]
            # Ensure even dimensions for hardware encoders; add user filters if any
            vf = ["scale=trunc(iw/2)*2:trunc(ih/2)*2"]

        if extra_filters:
            vf.append(extra_filters)

        # Common encoding/output args
        out_args: List[str] = []
        if use_genpts:
            out_args += ["-fflags", "+genpts"]
        out_args += [
            "-r",
            str(fps),
            "-c:v",
            vcodec,
        ]

        # Encoder-specific tuning
        if vcodec in ("libx264", "libx265"):
            out_args += ["-preset", preset, "-b:v", bitrate, "-pix_fmt", pix_fmt]
        else:
            # hardware encoders generally ignore -preset
            out_args += ["-b:v", bitrate, "-pix_fmt", pix_fmt]

        # Video filters
        if vf:
            out_args += ["-vf", ",".join(vf)]

        out_args += ["-movflags", "+faststart"]
        out_args += [self.out_path]

        # Final command (no audio flags at all)
        self.cmd = [self.ffmpeg, "-y"] + input_args + out_args

        self.proc = None
        self._stderr_fp = None

    def _auto_screen_index_mac(self) -> int:
        """
        Discover the AVFoundation device index for screen capture.
        Runs: ffmpeg -f avfoundation -list_devices true -i ""
        Looks for lines like: "[4] Capture screen 0"
        Returns the DEVICE INDEX (e.g., 4), not the "screen N" suffix.
        Prefers the entry ending with "screen 0" if multiple are present.
        """
        try:
            # ffmpeg dumps device list to stderr; merge to stdout for easy parsing
            res = subprocess.run(
                [
                    self.ffmpeg,
                    "-hide_banner",
                    "-f",
                    "avfoundation",
                    "-list_devices",
                    "true",
                    "-i",
                    "",
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,  # this command ends with an error by design; we just parse output
            )
            text = res.stdout or ""
        except Exception as e:
            raise RuntimeError(f"Failed to enumerate AVFoundation devices: {e}")

        # Limit parsing to the "AVFoundation video devices" section (optional but cleaner)
        # Then find lines of the form: [<dev_idx>] Capture screen <screen_num>
        video_section = []
        capture = False
        for line in text.splitlines():
            if "AVFoundation video devices:" in line:
                capture = True
                continue
            if "AVFoundation audio devices:" in line:
                break
            if capture:
                video_section.append(line)

        # regex: bracketed device id, then "Capture screen" (case-insensitive), then a number
        pat = re.compile(r"\[(\d+)\]\s+Capture\s+screen\s+(\d+)", re.IGNORECASE)
        matches = []
        for line in video_section:
            m = pat.search(line)
            if m:
                dev_idx = int(m.group(1))
                screen_num = int(m.group(2))
                matches.append((dev_idx, screen_num))

        if not matches:
            # Some ffmpeg builds label it slightly differently (e.g., "Capture Screen")
            pat_alt = re.compile(r"\[(\d+)\]\s+Capture\s+Screen\s+(\d+)", re.IGNORECASE)
            for line in video_section:
                m = pat_alt.search(line)
                if m:
                    dev_idx = int(m.group(1))
                    screen_num = int(m.group(2))
                    matches.append((dev_idx, screen_num))

        if not matches:
            raise RuntimeError(
                "Could not auto-detect a screen capture device from AVFoundation.\n"
                "Raw listing below (look for lines like '[4] Capture screen 0'):\n"
                f"{text}"
            )

        # Prefer the device whose label ends with "screen 0"; otherwise take the first
        for dev_idx, screen_num in matches:
            if screen_num == 0:
                return dev_idx
        return matches[0][0]

    def _pick_encoder(self, pref: str) -> dict:
        """Return best available encoder for the requested family (h264/hevc)."""
        try:
            res = subprocess.run(
                [self.ffmpeg, "-hide_banner", "-encoders"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=True,
            )
            enc_list = res.stdout
        except Exception:
            enc_list = ""

        if pref.lower() == "hevc":
            order = [
                "hevc_nvenc",
                "hevc_qsv",
                "hevc_amf",
                "hevc_videotoolbox",
                "libx265",
            ]
        else:
            order = [
                "h264_nvenc",
                "h264_qsv",
                "h264_amf",
                "h264_videotoolbox",
                "libx264",
            ]

        for name in order:
            if name in enc_list:
                return {"name": name}

        return {"name": "libx265" if pref.lower() == "hevc" else "libx264"}

    def start(self):
        self._stderr_fp = open(self.log_path, "w", encoding="utf-8")
        creation = 0
        if self.system == "Windows" and hasattr(subprocess, "CREATE_NO_WINDOW"):
            creation = subprocess.CREATE_NO_WINDOW

        self.proc = subprocess.Popen(
            self.cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=self._stderr_fp,
            creationflags=creation,
        )
        self._stderr_fp.write(str(time.time()))
        time.sleep(0.5)  # let ffmpeg init
        if self.proc.poll() is not None:
            raise RuntimeError(
                f"ffmpeg exited ({self.proc.returncode}). See log: {self.log_path}"
            )

    def stop(self, timeout=6):
        if self.proc and self.proc.poll() is None:
            try:
                if self.proc.stdin:
                    self.proc.stdin.write(b"q")  # graceful stop
                    self.proc.stdin.flush()
            except Exception:
                try:
                    self.proc.terminate()
                except Exception:
                    pass
            try:
                self.proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    if self.system == "Windows":
                        self.proc.send_signal(signal.CTRL_BREAK_EVENT)
                        self.proc.wait(timeout=2)
                    else:
                        self.proc.kill()
                except Exception:
                    self.proc.kill()
        try:
            if self._stderr_fp:
                self._stderr_fp.close()
        except Exception:
            pass

        if not os.path.exists(self.out_path) or os.path.getsize(self.out_path) == 0:
            raise RuntimeError(
                f"Recorded video missing/empty: {self.out_path}. Log: {self.log_path}"
            )
        return self.out_path
