python capture.py

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