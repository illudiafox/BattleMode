# Reverting the detection pipeline change

The detection loop was refactored on DEFIANT (2026-05-16) from a single thread to a
producer-consumer pipeline (two threads: one grabs frames, one runs detection).

If this causes problems on DREAMWEAVER — weird V4L2 timing, crashes, frames not
updating — here's how to roll it back:

## Quick revert (just the one file)

```bash
# Find the commit hash just before the pipeline change
git log --oneline battlemode/ui/app.py

# Check out the old version of app.py from that commit
git checkout <hash> -- battlemode/ui/app.py

# Commit the revert
git add battlemode/ui/app.py
git commit -m "Revert detection pipeline to single-thread loop"
```

## What to look for in git log

The commit that introduced the pipeline will mention `_FrameBuffer` or
"producer-consumer". The commit before that is the one you want.

## What changed

- **Old design**: one thread does `cap.grab()` then detection in a serial loop
- **New design**: capture thread fills a `_FrameBuffer`, detection thread reads from it

The `_FrameBuffer` class sits just above `PlayerSignals` in `app.py`.
To revert manually, delete `_FrameBuffer` and restore `_start_detection_thread`
so that `cap.grab()` is called directly inside the detection loop
(wrapped in `with make_cap() as cap:`).
