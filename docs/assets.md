# Private asset bundle — legacy reference

For new episodes, see the [episode config guide](episodes.md). The file list below is only for [recreating the original edit](baseline.md#reproduce-the-reference).

Obtain the existing functional-podcast asset folder through an authorized private transfer. Do not commit the folder or its sharing credentials. The initial adapter selects only these inputs:

- multiangle/{wide,A_close,B_threequarter,over_A,over_B,high}.jpg
- concept-focus/{function,map,fold,overview}.jpg
- full-local/concepts-2-5/{lambda,factory,filter,sort}.png
- full-local/revoice-swapped/{timeline.json,captions.json,scenes.json,analysis.wav,audio.m4a}
- Exactly one Generated*.wav at the bundle root (the original narration).

The original verification reports and final MP4 are useful comparison material but not required for staging. Old renders, raw ASR outputs, logs, draft scripts and task records are not copied. Four reviewed source/calibration files come from this repository, never from the external bundle.

Both analysis and narration WAV must be mono PCM16, 24000 Hz, 1791.36 seconds. The reference has 89 turns, 277 captions and 36 concept intervals. The staging check validates these counts, ordered nonoverlapping intervals, voice IDs, caption-to-turn references, and WAV headers; it does not prove asset provenance, inspect every glyph, or verify AAC until the rendering verifier runs. Symlinks outside the bundle are rejected. Staging performs copies, not symlinks, so subsequent renders cannot mutate original assets through shared links.

JSON shape (schematic, not episode data):

- timeline.json: {"duration": 1791.36, "turns": [{"start": 0.0, "end": 1.0, "speaker": "A"}, ...]}
- captions.json: [{"start": 0.0, "end": 1.0, "speaker": "A", "turn": 0, "text": "..."}, ...]
- scenes.json: [{"start": 1.0, "end": 5.0, "kind": "map", "title": "..."}, ...]

Keep original timing documents even when they have additional fields. Use a Korean-capable local font via PVK_FONT; fonts are not bundled. Correct font availability and text wrapping must be checked with --preview before encoding.
