#!/usr/bin/env python3
import argparse, ctypes, json, math, re, shutil, subprocess, time
from pathlib import Path
from typing import Optional, Literal, Iterable, Dict, Any


# ---------- ffmpeg helpers ----------
def which_ffmpeg() -> str:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        return ffmpeg
    mac_ffmpeg = "/opt/homebrew/bin/ffmpeg"
    if Path(mac_ffmpeg).exists():
        return mac_ffmpeg
    raise RuntimeError("ffmpeg not found on PATH.")


def extract_frame(
    ffmpeg: str, video: Path, t_sec: float, out_path: Path, image_ext="jpg", quality=2
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(video),
        "-ss",
        f"{t_sec:.6f}",
        "-frames:v",
        "1",
    ]
    if image_ext in ("jpg", "jpeg"):
        args += ["-q:v", str(quality)]
    elif image_ext == "png":
        args += ["-c:v", "png"]
    elif image_ext == "webp":
        args += ["-c:v", "libwebp"]
    args.append(str(out_path))
    p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError(
            f"ffmpeg failed at t={t_sec:.6f}s for {out_path}\n{p.stderr.decode('utf-8', errors='ignore')}"
        )


# ---------- ffmpeg log -> host start seconds ----------
START_RE = re.compile(r"\bstart:\s*([0-9]+(?:\.[0-9]+)?)")


def extract_ffmpeg_start_ts(
    log_file: str | Path, prefer: Literal["first", "last"] = "last"
) -> Optional[float]:
    text = Path(log_file).read_text(encoding="utf-8", errors="ignore")
    m = list(START_RE.finditer(text)) or [None]
    m = m[0] if prefer == "first" else m[-1]
    return float(m.group(1)) if m else None


# ---------- macOS CoreMedia host-time conversion ----------
def _mach_timebase_numer_denom():
    class mach_timebase_info_data_t(ctypes.Structure):
        _fields_ = [("numer", ctypes.c_uint32), ("denom", ctypes.c_uint32)]

    info = mach_timebase_info_data_t()
    lib = ctypes.CDLL("/usr/lib/libSystem.dylib")
    if lib.mach_timebase_info(ctypes.byref(info)) != 0:
        raise OSError("mach_timebase_info failed")
    return info.numer, info.denom


def host_time_seconds_now() -> float:
    lib = ctypes.CDLL("/usr/lib/libSystem.dylib")
    lib.mach_absolute_time.restype = ctypes.c_uint64
    ticks = lib.mach_absolute_time()
    numer, denom = _mach_timebase_numer_denom()
    ns = (ticks * numer) // denom
    return ns / 1e9


def host_seconds_to_epoch(host_secs: float) -> float:
    wall_now = time.time()
    host_now = host_time_seconds_now()
    return (wall_now - host_now) + host_secs


# ---------- JSONL helpers ----------
def read_jsonl(p: Path) -> Iterable[Dict[str, Any]]:
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def sanitize_ts(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except Exception:
        return None


# ---------- main ----------
def main():
    ap = argparse.ArgumentParser(
        description="Verify files, parse ffmpeg start, convert to epoch, and extract frames for events after video start."
    )
    ap.add_argument("--basename", required=True)
    ap.add_argument("--logs-dir", default="logs")
    ap.add_argument("--videos-dir", default="videos")
    ap.add_argument("--img-dir", default="images")  # root images dir
    ap.add_argument("--out-jsonl", default=None)
    ap.add_argument("--include-types", nargs="*", default=None)
    ap.add_argument("--offset-ms", type=float, default=0.0)
    ap.add_argument("--min-gap-ms", type=float, default=0.0)
    ap.add_argument("--ext", default="jpg", choices=["jpg", "jpeg", "png", "webp"])
    ap.add_argument("--quality", type=int, default=2)
    ap.add_argument("--prefer", choices=["first", "last"], default="last")
    args = ap.parse_args()

    basename = args.basename
    logs_dir = Path(args.logs_dir).resolve()
    videos_dir = Path(args.videos_dir).resolve()
    images_root = Path(args.img_dir).resolve()

    # Required files
    jsonl_path = logs_dir / f"{basename}.jsonl"
    ffmpeg_log_path = videos_dir / f"{basename}.log"
    video_path = videos_dir / f"{basename}.mp4"
    missing = [p for p in (jsonl_path, ffmpeg_log_path, video_path) if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "Missing required file(s):\n" + "\n".join(map(str, missing))
        )

    # Per-basename image subfolder: images/<basename>/
    images_dir = images_root / basename
    images_dir.mkdir(parents=True, exist_ok=True)

    # Output JSONL
    out_jsonl = (
        Path(args.out_jsonl).resolve()
        if args.out_jsonl
        else (logs_dir / f"{basename}_frames.jsonl")
    )
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)

    # Parse ffmpeg start & convert to epoch
    host_start = extract_ffmpeg_start_ts(ffmpeg_log_path, prefer=args.prefer)
    if host_start is None:
        raise RuntimeError(f"No 'start:' timestamp found in {ffmpeg_log_path}")
    video_start_epoch = host_seconds_to_epoch(host_start)

    ffmpeg_bin = which_ffmpeg()
    include_types = set(args.include_types) if args.include_types else None
    min_gap_s = args.min_gap_ms / 1000.0 if args.min_gap_ms > 0 else 0.0
    offset_s = args.offset_ms / 1000.0
    image_ext = args.ext.lower()
    quality = int(args.quality)

    counter = 1
    last_rel = -math.inf

    with out_jsonl.open("w", encoding="utf-8") as fout:
        for ev in read_jsonl(jsonl_path):
            ts = sanitize_ts(ev.get("ts"))
            if ts is None or ts < video_start_epoch:
                # Only include actions after the video has started
                continue

            ev_type = ev.get("type", "event")
            if include_types is not None and ev_type not in include_types:
                continue

            rel_t = (ts - video_start_epoch) + offset_s
            if rel_t < 0:  # extra guard
                continue
            if rel_t - last_rel < min_gap_s:
                continue

            fname = f"{counter:06d}_{ev_type}_{int(ts*1000)}.{image_ext}"
            frame_path = images_dir / fname
            try:
                extract_frame(
                    ffmpeg_bin,
                    video_path,
                    rel_t,
                    frame_path,
                    image_ext=image_ext,
                    quality=quality,
                )
            except Exception:
                continue

            ev_out = dict(ev)
            ev_out["frame_path"] = str(frame_path.resolve())
            fout.write(json.dumps(ev_out, ensure_ascii=False) + "\n")

            counter += 1
            last_rel = rel_t

    print("[OK] Images →", images_dir)
    print("[OK] Augmented JSONL →", out_jsonl)
    print(
        f"[OK] Video start (host): {host_start:.6f} s  |  (epoch): {video_start_epoch:.6f}"
    )


if __name__ == "__main__":
    main()
