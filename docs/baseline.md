# Approved 2D reference

The reference is the final swapped-character episode, not older 2-minute/20-minute or unswapped outputs. See reference-provenance.json for frame count, dimensions, durations and source hashes. Only the renderer's font selection has a portability override; all other imported source/calibration bytes are preserved.

Voice A drives the navy/black-haired character (original visual B). Voice B drives the green/brown-bob character (original visual A). Caption A/B remain logical voices. Asset names such as A_close are legacy visual identifiers.

Architecture:
- Pillow scene compositing at 1280x720/24fps; six cached still-image views.
- PCM amplitude envelope -> silence-gated, eight-state cached mouth patches; listener mouth remains at rest. Some open poses include a locally drawn inner mouth cavity. Not phoneme lip sync.
- Seven-second segment/turn-based camera schedule, unchanged narration, ASR-derived captions, 36 concept intervals.
- Presenters shrink/fade out and are fully absent in the concept core, then return.
- H.264 yuv420p plus stream-copied AAC for full master; a separate multi-window sample re-encodes extracted audio.

Known improvement targets: sorting labels drifting off cards; fold display edge crowding; worked pipelines without sufficient visible calculation; text baseline/padding/number alignment. Build a reusable measured layout system and test transition states, not just static frames. Preserve the lesson's semantics and do not insert unspoken corrections into captions.

Performance baseline is a few minutes for the original full 2D render on its development host; it is not a portable benchmark guarantee. Measure local setup, render and encode times separately. Do not make full Blender scene rendering the default: the product goal is quick repeatable episode production.

Original verification covered full decode, frame/duration checks, AAC preservation, silence gating, asset preservation and representative encoded frames. Full human listening/visual review was not performed. Do not inherit any subjective approval from a numeric report.

## Reproduce the reference

The following workflow is unchanged. It uses six prebuilt still-image views, amplitude-driven mouth animation, and timed concept scenes. To reproduce the original edit, use this reference workflow rather than the new-episode renderer.

### Setup (macOS / Linux)

Requirements: Python 3.11+, FFmpeg with libx264 and AAC support, ffprobe on PATH, and a Korean-capable font. Install dependencies in a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Replace the placeholder asset path below with your downloaded **functional-podcast** folder. Keep its folder structure intact. This public repository deliberately does not contain the recording, episode transcript, images, or final video. See [asset layout](assets.md).

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
