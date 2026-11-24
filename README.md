# Podcast Video Kit

A local command-line tool that turns a Word script, a WAV recording, and two portraits into a 2D podcast video with automatic subtitles, optional mouth motion, and concept cards. No cloud service or Blender required.

## Technical specs

- Python 3.11+, Pillow, NumPy, and FFmpeg/ffprobe with H.264 (`libx264`) and AAC support.
- MP4 at 1280×720, 24 fps, with AAC audio; SRT subtitles and a JSON render plan. Full renders keep the recording intact without cuts or speed changes.
- Timing comes from a local Whisper model or an existing word-timestamp cache for the same WAV. Portrait animation follows audio level, not phonemes.

## Install and run

Install FFmpeg and a font that covers your script language. On macOS, `brew install ffmpeg` provides `ffmpeg` and `ffprobe`. From the checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Save `private/episode.json` next to your inputs. In the DOCX, use `A:` and `B:` paragraphs under the heading you set in `section`.

```json
{
  "script": "script.docx",
  "section": "Script",
  "narration": "narration.wav",
  "portrait_a": "A.png",
  "portrait_b": "B.png",
  "words_json": "words.json",
  "preview": 30,
  "output": "runs/preview"
}
```

```bash
podcast-video-kit --config private/episode.json
```

Paths are relative to the JSON file. Check `preview.mp4` in the output folder. For the full video, remove `preview` and set `output` to a new directory. Keep input media and settings private.

[Episode settings and Whisper setup](docs/episodes.md) · [Development checks](docs/validation.md) · [Legacy reference](docs/baseline.md)
