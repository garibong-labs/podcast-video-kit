# New-episode input and review

The installed CLI accepts a UTF-8 Word DOCX with a uniquely named script heading, a local WAV, and one image for each of speakers A and B. The new renderer does not read the legacy timeline or depend on private storyboard assets. See the README for commands.

Inside the selected section, use a paragraph for each `A:` / `B:` turn. The parser keeps consecutive turns by one speaker. It stops at the next sequential numbered section or a heading at the same or higher Word outline level. Paragraphs without a speaker label appear in `plan.json` with their positions; they are not assigned to a voice automatically. The input DOCX is never edited. If an unlabeled continuation creates a poor match, add the intended voice label in a private copy of the script, then inspect a new plan.

The aligner matches normalized character runs against timestamped words. It reports per-turn coverage, lists turns below 60%, and fails if no anchors exist for a turn or overall script coverage falls below 50%. Coverage measures matched text, not timing accuracy or whether each voice is cast correctly. An ASR cue without a matching turn can still appear as an unlabeled caption. Review warnings and play back the preview before rendering the full recording.

## Optional concept cards

Supply `--config private/episode.json` using this structure:

```json
{
  "title": "Illustrated example",
  "scenes": [
    {
      "first_turn": 3,
      "last_turn": 4,
      "title": "Add one to each entry",
      "body": "Input: 1, 3, 5\nOutput: 2, 4, 6"
    }
  ]
}
```

Turn numbers are 1-based. Each range must cover at least two seconds after alignment and must not overlap another range. The CLI takes wording and numbers as literal text. It does not infer teaching diagrams, run embedded code, or fact-check the lesson. Preview the densest cards and subtitles at the intended delivery size. Keep generated `words.json`, `plan.json`, media and subtitles under an ignored `runs/` or private directory, and never attach them to public issues or commits.
