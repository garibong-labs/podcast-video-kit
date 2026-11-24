# Next implementation milestones

The current CLI uses [one episode JSON](episodes.md) for a DOCX, WAV, two portraits, timing source, and output. It already supports plans, previews, full renders, bounded timing repair, optional mouth motion, and explicit concept cards. The [legacy reference workflow](baseline.md) remains separate. The milestones below are future work, not requirements to run the CLI.

1. Version the existing episode manifest before adding richer shot schedules, scene templates, or output profiles. Keep private episode data outside source control.
2. Extract a side-effect-free library from reference scripts: audio envelope, mouth calibration/cache, camera scheduling, typography/layout, concept scenes, captions, FFmpeg encoding and verification. Preserve reference behavior with golden comparisons using locally supplied assets.
3. Grow the installed CLI with subcommands such as init and doctor, rather than overloading its single episode command. Configurable paths, clear preflight failures, no overwrite by default, bounded subprocess handling and resumable jobs are required.
4. Provide reusable 2D layout components: measured text bounds, baseline/card alignment, consistent padding, tabular numeric updates, arrows and values avoiding labels, subtitle exclusion zone and worked-problem states. Validate longest Korean strings and transition frames.
5. Improve low-confidence correction and reuse of local timing data. Preserve the supplied recording. Disclose ASR errors and distinguish script matching from forced alignment/diarization.
6. Extend the existing synthetic tests and encode smoke checks with richer scene-transition coverage and per-stage performance budgets. Private visual goldens remain local.
7. Only after a reliable fast 2D product exists, consider optional offline asset authoring (including Blender) without requiring a multi-hour 3D render for each episode.

Acceptance for a future generic release: two distinct episodes created with configuration/assets rather than source edits; fresh-machine setup documented; sample-first review; all inputs untouched; predictable local execution; correct teaching graphics; measured speed and honest review limits.
