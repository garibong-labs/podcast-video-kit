# New-episode input and review

The installed CLI accepts a UTF-8 Word DOCX with a uniquely named script heading, a local WAV, and one image for each of speakers A and B. The new renderer does not read the legacy timeline or depend on private storyboard assets. See the README for commands.

Inside the selected section, use a paragraph for each `A:` / `B:` turn. The parser keeps consecutive turns by one speaker. It stops at the next sequential typed section number or a heading at the same or higher Word outline level. It also recognizes conventional top-level automatic decimal labels such as `7. Script` or `7) Script` when the paragraphs share a Word list with an explicit start value and a known level. In such a list, the next top-level numbered paragraph without an A/B label ends the section. A unique bare heading such as `Script` also selects it.

Numbered dialogue and nested list notes can stay in the section. Word paragraphs with an explicit top-level bullet format stay in the section as notes or labeled dialogue unless their outline level ends the section. For style-inherited numbering, exactly one effective list level must link to the paragraph style or one of its parent styles. When automatic numbering makes the heading or boundary ambiguous, the CLI identifies the paragraph. Use typed numbers or consistent Word outline headings for section boundaries in those documents. Paragraphs without a speaker label appear in `plan.json` with their positions. If an unlabeled continuation creates a poor match, add the intended voice label in a private copy of the script, then inspect a new plan.

The aligner matches normalized character runs against timestamped words. The script limit of 30,000 normalized characters is checked before transcription. The same limit applies to ASR word text after transcription. If a segment supplies text, its timed words must account for that text after case, punctuation, and spacing normalization. Caches that omit segment text are supported. The aligner reports per-turn coverage, lists turns below 60%, and fails if no anchors exist for a turn or overall script coverage falls below 50%. Coverage measures matched text. Unmatched speech appears without a speaker label, including between two words matched to the same speaker.

During the exact time span of a spoken word with no matched characters, the studio uses the neutral wide shot and leaves both speaker indicators idle. Captions keep their own display timing.

Each caption cue that overlaps the selected render window must be visible on at least one frame at 24 fps. If a cue falls between frames, the render error gives the cue number and time range. Adjust the word timing or preview bounds and retry. Preview text fitting covers the captions and cards visible in that preview. Review warnings and play back the preview before rendering the full recording.

## Optional mouth motion

Add `mouth_motion` to your `--config private/episode.json` to animate one or both of your existing portraits. For example:

```json
{
  "mouth_motion": {
    "A": [0.49, 0.64, 0.13],
    "B": [0.52, 0.62, 0.12]
  }
}
```

Replace the sample values with measurements from each portrait. Open the original image as displayed after EXIF rotation or mirroring, including any transparent margins. Divide the mouth center's horizontal pixel position by the image width, its vertical position by the image height, and the distance between the lip corners by the image width. Values must be between 0 and 1, and the lip area must fit inside the portrait. Omit a speaker to leave that portrait still, or omit the entire field to keep the default behavior. This field can coexist with `title` and `scenes` in the same file.

The renderer stretches a small region of the original portrait and adds a shaded inner-mouth opening. The current speaker's audio level selects a cached pose; during silence, unmatched speech, and the other speaker's turn, the portrait returns to the original image. This is not phoneme lip sync. Use a short `--preview` with both speakers and a pause to check the landmarks before rendering the whole episode. Keep episode-specific calibration private.

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
