# Initial-import validation

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

CI checks synthetic tests and source compilation without private media. Actual media rendering and screenshot comparisons require the private asset bundle and a compatible font.
