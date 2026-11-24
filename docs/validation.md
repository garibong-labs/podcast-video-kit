# Validation

## Current episode CLI

From the installed development environment, run:

```bash
podcast-video-kit --help
python -m unittest discover -s tests -v
python -m compileall -q podcast_video_kit tools reference tests
```

CI runs on Python 3.11 and 3.14. Synthetic tests cover manifest validation, script and timing handling, caption visibility, and preview/full encodes with decode and AAC verification. Media smoke tests require FFmpeg, ffprobe, and a suitable local font. CI does not use private media or download Whisper models. For a real run, inspect `plan.json` and `verification.json`, then play the preview to check captions, audio, and mouth alignment.

## Historical initial-import validation

Validated locally on macOS arm64 with Python 3.14, Pillow 12.1.1, NumPy 2.4.3 and installed FFmpeg/ffprobe.

- Standard-library synthetic tests: 15 passed.
- Python source compilation: passed; reference modules are parsed without executing import-time I/O in CI.
- Actual private-bundle preflight: 20 allowlisted input files, expected timing counts and PCM formats passed.
- Fresh staging: copied only selected inputs and four repository source/calibration files into an ignored directory. Original asset bundle is not a rendering workspace.
- Preview: 42,993-frame timeline at 1791.375 seconds; generated contact sheet byte-identical to the prior reference storyboard.
- Encoded multi-window sample: 50.375 seconds, 1,209 video frames; audio 50.36 seconds; complete decode passed.
- Sample MP4 was byte-identical to the existing swapped-reference sample on the validation host. Nine representative encoded sample frames inspected. This demonstrates import parity on this host, not portability or absence of inherited visual defects.
- Full 29-minute master was NOT rerendered in this bootstrap validation. The prior master verification is historical baseline evidence only.
- No subjective audio listening performed during this import.
- Public index: explicit source/docs/test allowlist; supplementary pattern scan found no personal home paths, personal identifiers, email addresses, common credential patterns, chat URLs or card-like numeric strings in the changed files at review time. This scan is not a guarantee; manual review and external-asset separation remain required.

Recreating or comparing the original edit requires the private reference asset bundle and a compatible font; the current CLI's synthetic tests do not.
