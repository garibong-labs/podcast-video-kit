# Next implementation milestones

The initial import intentionally establishes a reproducible reference before a generic CLI redesign. Do not treat the earlier Blender-production brief as the active product specification.

1. Define a versioned episode manifest: narration, timing/captions, logical speakers, explicit visual mapping, asset/font references, shot schedule, scene templates and output profile. Keep all private episode data outside source control.
2. Extract a side-effect-free library from reference scripts: audio envelope, mouth calibration/cache, camera scheduling, typography/layout, concept scenes, captions, FFmpeg encoding and verification. Preserve reference behavior with golden comparisons using locally supplied assets.
3. Add a real installed CLI with proposed commands init, doctor, validate, preview, render and verify. These command names are a roadmap, NOT currently available. Configurable paths, clear preflight failures, no overwrite by default, bounded subprocess handling and resumable jobs are required.
4. Provide reusable 2D layout components: measured text bounds, baseline/card alignment, consistent padding, tabular numeric updates, arrows and values avoiding labels, subtitle exclusion zone and worked-problem states. Validate longest Korean strings and transition frames.
5. Make new-episode timing/transcription an explicit optional local stage. Do not resynthesize supplied narration. Disclose ASR errors and distinguish script matching from forced alignment/diarization.
6. Add synthetic short media fixtures and headless smoke tests, timeline invariants, speaker/camera/mouth mapping tests, AAC identity checks and per-stage performance budgets. Private visual goldens remain local.
7. Only after a reliable fast 2D product exists, consider optional offline asset authoring (including Blender) without requiring a multi-hour 3D render for each episode.

Acceptance for a future generic release: two distinct episodes created with configuration/assets rather than source edits; fresh-machine setup documented; sample-first review; all inputs untouched; predictable local execution; correct teaching graphics; measured speed and honest review limits.
