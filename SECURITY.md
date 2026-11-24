# Public repository safety

This repository contains source, legacy numeric mouth calibration, documentation, and synthetic tests only. Keep private episode assets and manifests outside the checkout or under ignored `private/` or `runs/` directories. `episode.json` is ignored by basename; keep custom-named manifests under `private/` or outside the checkout because they can contain local paths, episode text, and calibration values.

Before publishing any change:
1. Stage an explicit allowlist, inspect git diff --cached and git diff --cached --stat.
2. Check file contents, filenames, Git author/committer metadata, and generated reports for personal identities, home directories, credentials, OAuth refresh tokens, cloud/provider settings, billing details, and session references.
3. Exclude all original narration, transcript/caption text, source documents, images, final videos and archives. An ignore rule is not a security boundary: previously tracked files remain tracked.
4. Use synthetic test data and placeholder paths. Do not put private data in public CI logs or issue reports.
5. Never weaken TLS validation to get a push or download working.

If credentials are exposed, revoke/rotate them first and contact the repository owner privately. Do not paste the values into a public issue. Automated searches are supplementary; they do not prove the absence of sensitive information.
