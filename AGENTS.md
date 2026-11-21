# Development contract

This is a public local-first media CLI project. Read README.md and docs/roadmap.md before changing it.

- Preserve the existing LICENSE. Do not invent redistribution rights for private media.
- Never commit narration, transcripts, captions, generated images, recordings, rendered videos, local paths, user identities, credentials, payment data, provider configuration, or session logs. Use synthetic fixtures.
- Keep reference/ as the behavioral baseline. Do not run its scripts in the original asset folder. Use tools/stage_reference.py with a fresh ignored output directory.
- Current reference scripts perform import-time I/O and are intentionally not a reusable library yet.
- Keep logical voice IDs distinct from visual asset IDs: voice A -> original visual B (navy); voice B -> original visual A (green).
- Preserve complete narration and copy AAC on the master. Sample audio extraction is separate and must be disclosed.
- Do not claim generic CLI, phoneme lip sync, full listening review, or 3D rendering until actually implemented/verified.
- Default backend remains fast 2D. Benchmark representative samples before expensive renders. No automatic cloud/provider fallback, uploads, or downloads.
- Extend standard-library tests with synthetic data. Run unittest and compileall before a PR. Use explicit file staging and inspect the staged diff, not git add .
- Keep episode-specific content external as the pipeline is generalized. Replace hardcoded teaching layout with measured reusable components, not more per-frame offsets.
