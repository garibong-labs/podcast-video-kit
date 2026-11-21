# podcast-video-kit

A local-first CLI project for turning narration, scripts, and character assets into repeatable podcast videos.

## Current status

**Initial reference import, not a finished general-purpose CLI.** This version preserves a working Python/Pillow/NumPy/FFmpeg 2D pipeline and a safe asset-staging command. It can reproduce the existing functional-programming episode with its separately supplied private assets. Arbitrary new episodes, transcription, and configurable scene templates are planned, not implemented. Blender is not required.

The baseline uses six still-image camera views, amplitude-driven mouth animation, timed Korean captions, and animated concept overlays. It is not phoneme lip sync or real 3D animation.

## Quick start (macOS / Linux)

Requirements: Python 3.11+, FFmpeg with libx264 and AAC support, ffprobe on PATH, and a Korean-capable font. Install dependencies in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Replace the placeholder asset path below with your downloaded **functional-podcast** folder. Keep its folder structure intact. This public repository deliberately does not contain the recording, episode transcript, images, or final video. See [asset layout](docs/assets.md).

```bash
python tools/stage_reference.py --assets "/path/to/functional-podcast" --check-only
python tools/stage_reference.py --assets "/path/to/functional-podcast" --output runs/reference
```

For fonts, the reference defaults to macOS Apple SD Gothic Neo. On Linux, or to override the font, supply a locally installed Korean font:

	export PVK_FONT="/path/to/KoreanFont.ttf"

Stage creates a NEW working copy and refuses an existing output directory. The following commands operate only on that copy:

```bash
# Inspect representative still frames first
python runs/reference/full-local/render_revoice_swapped.py --preview

# Render and validate a short multi-scene sample
python runs/reference/full-local/render_revoice_swapped.py --sample
python runs/reference/full-local/revoice-swapped/verify.py --sample

# Only after reviewing the sample: render and validate the full episode
python runs/reference/full-local/render_revoice_swapped.py
python runs/reference/full-local/revoice-swapped/verify.py
```

- Preview: contact sheet, regenerated SRT and mouth-state array; no video encoding.
- Sample: approximately 50 seconds assembled from seven reference windows. This separate sample re-encodes its excerpt audio. Its verifier reports dimensions and durations and checks decode; compare the report against 1,209 frames and 50.375 seconds for length parity.
- Full: approximately 29m51s at 1280×720/24fps; **copies the complete reference AAC stream** without cutting or retiming it.
- The full verifier performs a complete decode, frame/duration and AAC-identity checks and extracts representative frames. Inspect the images and listen yourself; numeric checks do not constitute human review.

Outputs are under `runs/reference/full-local/`. The renderer itself overwrites outputs in its staged working copy when repeated. Stage each experiment into a different directory. Do not run the reference scripts inside your source asset folder: they write files at import/runtime.

## Development checks

```bash
python -m unittest discover -s tests -v
python -m compileall -q tools reference tests
```

These tests require no private episode assets. CI does not upload media or use external AI services. See [development plan](docs/roadmap.md), [baseline details](docs/baseline.md), and [public-repository safety](SECURITY.md).

## Known limitations

- Episode-specific duration, labels, camera schedules and concept code remain hardcoded. This commit establishes a baseline for refactoring, not a generic product claim.
- The reference has known concept-label alignment/spacing and worked-problem presentation defects. Preserve it as a comparison target, not a perfect design.
- Automatic captions have not been fully proofread. Speaker timing uses script matching rather than acoustic diarization.
- Changing fonts or dependency versions can change pixels, wrapping and encoded bytes. The baseline MP4 hash is an identity reference, not a guarantee of byte-identical re-encoding.
- Source media and font licensing are separate from the repository's existing LICENSE. No media redistribution rights are implied.
