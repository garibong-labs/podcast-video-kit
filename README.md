# podcast-video-kit

A local-first CLI project for turning narration, scripts, and character assets into repeatable podcast videos.

## New episodes: DOCX + WAV + two portraits

Use `podcast-video-kit` for new episodes. It is a local 2D renderer, not Blender or phoneme lip sync. It does not use cloud transcription, generate images, or require the reference episode's assets.

Requirements: Python 3.11+, FFmpeg (including libx264 and AAC) and ffprobe, a font that covers the script language, and either the OpenAI Whisper CLI with a trusted local model checkpoint or a matching local Whisper word-timestamp JSON. Apple SD Gothic Neo is used on macOS unless you set `--font` or `PVK_FONT`; on Linux, pick a local font with the required glyph coverage.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
# Install openai-whisper separately in this environment if using --whisper-model.
```

```bash
podcast-video-kit --script "private/script.docx" --narration "private/narration.wav" \
  --portrait-a "private/A.png" --portrait-b "private/B.png" \
  --whisper-model "$HOME/.cache/whisper/small.pt" --language ko \
  --output runs/episode-preview --preview 30
```

The model file must already exist. Use a trusted model: its loading is delegated to Whisper. No model is downloaded by this command. The default heading is `7. 팟캐스트 대본`; specify a different one with `--section`. Dialogue starts with `A:` or `B:`. Matching keeps turn order, including repeat speakers; it does not identify speakers acoustically. Use portrait files in the same A/B order as the script and recording. Front-facing separate portraits work best. One image per person produces a wide two-portrait layout and 2D close-up, not six distinct camera angles. Portraits stay still; an audio level indicator shows active speech rather than animating the mouth.

- Start with `--preview 30` and optionally `--preview-start 60` to inspect another part of the episode. Add `--plan-only` instead of preview to inspect alignment without rendering.
- Review `plan.json`, especially low-coverage turns and unlabeled paragraphs (not silently read as dialogue). Subtitles come from the recording's ASR, not a verbatim copy of the script. Words that cross a speaker boundary are shown without a speaker label. If a speech segment lacks word times or a token has no usable duration, the CLI identifies the offending entry instead of silently omitting speech. Correct the saved `words.json` and retry with that file and a new output folder.
- To render the full recording, repeat the command with a **new** `--output runs/episode-full`, change `--whisper-model … --language ko` to `--words-json runs/episode-preview/words.json`, and omit both preview flags. Reuse word JSON only with the WAV it came from. `captions.srt` and plan timestamps always refer to the full recording, even in a preview run.
- The full render keeps the supplied recording intact in time (no cuts, added gaps, or speed changes). It encodes the WAV to AAC once, copies that AAC track into the MP4, and verifies the copy and full decode. A preview encodes only the selected excerpt. Use `verification.json` and check the playback yourself.
- [Optional concept cards](docs/episodes.md) use explicitly supplied text and ranges in the script. No guesses are made about which words or numbers to teach. Keep inputs and generated runs private. `words.json` and `plan.json` contain episode text and are ignored under custom run folders too. The command does not publish or overwrite inputs or runs.

## Reproduce the existing reference episode

The following workflow is unchanged. It uses six prebuilt still-image views, amplitude-driven mouth animation, and timed concept scenes. To reproduce the original edit, use this reference workflow rather than the new-episode renderer.

### Reference quick start (macOS / Linux)

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
python -m compileall -q podcast_video_kit tools reference tests
```

These tests require no private episode assets. With FFmpeg and the test font installed, they also exercise a full and preview render using synthetic fixtures. CI does not upload media or use external AI services. See [development plan](docs/roadmap.md), [baseline details](docs/baseline.md), and [public-repository safety](SECURITY.md).

## Known limitations

- The legacy reference renderer still has hardcoded duration, layouts, and camera schedules. The new renderer is a simpler two-portrait layout, not a visual replica.
- The reference has known concept-label alignment/spacing and worked-problem presentation defects. Preserve it as a comparison target, not a perfect design.
- Automatic captions have not been fully proofread. Speaker timing uses script matching rather than acoustic diarization.
- Changing fonts or dependency versions can change pixels, wrapping and encoded bytes. The baseline MP4 hash is an identity reference, not a guarantee of byte-identical re-encoding.
- Source media and font licensing are separate from the repository's existing LICENSE. No media redistribution rights are implied.
