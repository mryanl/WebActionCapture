# Capture and Parse Browser Sessions

This project records full-screen browser sessions using Playwright and FFmpeg, logs user actions, and extracts event-aligned frames.

## Setup

```sh
conda env create -f environment.yml
conda activate capture
playwright install chromium
```

## Capture a Session

```sh
python capture.py
```

This launches Chromium, records the screen, and logs events to `logs/` and `videos/`.

## Extract Event Frames

```sh
python parser_mac.py \
  --basename 315b7b51_1760989935 \
  --logs-dir logs \
  --videos-dir videos \
  --img-dir images \
  --include-types mouse_move click scroll_start scroll_end type type_commit window_focus window_blur tab_hidden tab_visible navigation recorder_init \
  --offset-ms 0 \
  --min-gap-ms 50 \
  --ext jpg \
  --quality 2 \
  --prefer last
```

This extracts one frame per event into `images/`.

## Output

```
videos/   # Screen recordings (.mp4)
logs/     # Event logs (.jsonl)
images/   # Extracted event frames
```
