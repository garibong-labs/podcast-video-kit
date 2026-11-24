# podcast-video-kit

A local-first CLI project for turning narration, scripts, and character assets into repeatable podcast videos.

## New episodes: DOCX + WAV + two portraits

Use `podcast-video-kit` for new episodes. It is a local 2D renderer, not Blender or phoneme lip sync. It does not use cloud transcription, generate images, or require the reference episode's assets.

Requirements: Python 3.11+, FFmpeg (including libx264 and AAC) and ffprobe, a font that covers the script language, and either the OpenAI Whisper CLI with a trusted local model checkpoint or a matching local Whisper word-timestamp JSON. Apple SD Gothic Neo is used on macOS unless you set `--font` or `PVK_FONT`; on Linux, pick a local font with the required glyph coverage.

On macOS, install FFmpeg and ffprobe with Homebrew.

```bash
brew install ffmpeg
```

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Put your settings in a local `episode.json`, for example in a directory with your private inputs:

```json
{
  "script": "script.docx",
  "narration": "narration.wav",
  "portrait_a": "A.png",
  "portrait_b": "B.png",
  "words_json": "words.json",
  "preview": 30,
  "output": "runs/episode-preview"
}
```

```bash
podcast-video-kit --config "private/episode.json"
```

All run settings come from that file. Relative paths (including `output`) are relative to the JSON file, not the terminal's working directory. Absolute paths and `~/` paths also work; shell variables inside JSON are not expanded. Old commands using individual flags must move those settings into JSON: for example, `--portrait-a` becomes `"portrait_a": "A.png"`, and `--preview 30` becomes `"preview": 30`.

Use a word-timestamp cache from the same WAV to skip transcription. To transcribe instead, replace `words_json` with `"whisper_model": "~/.cache/whisper/small.pt"` and optionally add `"language": "ko"`. The commands below install Whisper on macOS and prepare `small.pt` once using one second of generated silence. On Linux, install the Whisper CLI for your system and start at `sample_dir`. This setup runs separately from `podcast-video-kit`.

```bash
brew install openai-whisper
sample_dir=$(mktemp -d)
ffmpeg -v error -f lavfi -i anullsrc=r=16000:cl=mono -t 1 "$sample_dir/sample.wav"
whisper "$sample_dir/sample.wav" --model small --model_dir "$HOME/.cache/whisper" --device cpu --fp16 False --language ko --output_dir "$sample_dir" --output_format txt
```

The model file must already exist. Use a trusted model: its loading is delegated to Whisper. No model is downloaded by the episode command. The default heading is `7. 팟캐스트 대본`; set `section` for a different heading. Dialogue starts with `A:` or `B:`. Matching keeps turn order, including repeat speakers; it does not identify speakers acoustically. Use portrait files in the same A/B order as the script and recording. Front-facing separate portraits work best. One image per person produces a wide two-portrait layout and 2D close-up, not six distinct camera angles. Add [optional mouth motion](docs/episodes.md#optional-mouth-motion) to animate the same images.

- Start with `"preview": 30` and optionally `"preview_start": 60` to inspect another part of the episode. Preview offsets must be inside the WAV; they are then snapped to the nearest available video frame. With `whisper_model`, even a preview transcribes the full WAV. Full and preview runs load the chosen font and check both portraits before transcription. `"plan_only": true` inspects alignment without loading the font or decoding the portraits; omit `preview` and `preview_start` in that mode. Use a fresh `output` directory on every retry.
- Review `plan.json`, especially low-coverage turns and unlabeled paragraphs (not silently read as dialogue). Subtitles come from the recording's ASR, not a verbatim copy of the script. Words that cross a speaker boundary are shown without a speaker label. If segment text and timed words disagree, or word timings are missing or invalid, the CLI identifies the offending entry. Correct the generated `words.json` or your original imported cache, then retry with a new output folder.
- By default, nonblank words with identical start and end times get a bounded estimate and a warning. Set `"timing_mode": "strict"` to reject them without estimating. Repair reserves time for later zero-duration words, including when they share a gap or borrow from opposite ends of one neighbor. A neighbor can lend up to 40 ms total, keeping at least half and at least 20 ms of its original duration. If a repair leaves a caption between frames, the planner tries alternate bounded placements using the full-video frame grid. It does not remove words or change the WAV or raw `words.json`. Check `estimated_word_timings` in `plan.json` and play back the affected times. In a `neighbor_boundary` record, `source_end` (when present) is the raw end and `original_end` is the WAV-clipped end before the extra trim. If the limits do not allow a repair or another timing error remains, correct the cache separately.
- To render the full recording, set a **new** `output` such as `runs/episode-full`, omit both preview keys, and use `words_json` for the same WAV. If you started with `whisper_model`, replace it with the new preview cache, e.g. `"words_json": "runs/episode-preview/words.json"`. `captions.srt` and plan timestamps always refer to the full recording, even in a preview run.
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
