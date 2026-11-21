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
