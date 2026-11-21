#!/usr/bin/env python3
"""Stage an explicitly selected private asset bundle into a NEW working folder.

This bootstrap helper is not yet a general-purpose podcast renderer.
Never executes episode code, authenticates, downloads, or overwrites a directory.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import shutil
import sys
import wave

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ("wide", "A_close", "B_threequarter", "over_A", "over_B", "high")
OLD_CONCEPTS = ("function", "map", "fold", "overview")
NEW_CONCEPTS = ("lambda", "factory", "filter", "sort")
REQUIRED = tuple(
    [f"multiangle/{name}.jpg" for name in VIEWS]
    + [f"concept-focus/{name}.jpg" for name in OLD_CONCEPTS]
    + [f"full-local/concepts-2-5/{name}.png" for name in NEW_CONCEPTS]
    + [f"full-local/revoice-swapped/{name}" for name in
       ("timeline.json", "captions.json", "scenes.json", "analysis.wav", "audio.m4a")]
)
CODE = (
    "full-local/render_revoice_swapped.py",
    "full-local/mouths.py",
    "full-local/mouth-landmarks-640.json",
    "full-local/revoice-swapped/verify.py",
)


def asset_files(root: Path) -> list[tuple[Path, Path]]:
    """Allowlist only; refuse symlinks escaping the supplied asset bundle."""
    root = root.resolve(strict=True)
    files = []
    for name in REQUIRED:
        rel = Path(name)
        path = (root / rel).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"Not a regular file inside the asset bundle: {rel}")
        files.append((path, rel))
    narration = sorted(root.glob("Generated*.wav"))
    if len(narration) != 1:
        raise ValueError("Expected exactly one Generated*.wav in the asset root")
    wav = narration[0].resolve(strict=True)
    if not wav.is_relative_to(root) or not wav.is_file():
        raise ValueError("Narration must be a regular file inside the asset bundle")
    files.append((wav, Path(narration[0].name)))
    return files


def validate_reference(root: Path) -> None:
    data = root / "full-local/revoice-swapped"
    timeline = json.loads((data / "timeline.json").read_text())
    captions = json.loads((data / "captions.json").read_text())
    scenes = json.loads((data / "scenes.json").read_text())
    duration = timeline["duration"]
    turns = timeline["turns"]
    if not math.isfinite(duration) or abs(duration - 1791.36) > 0.001 or len(turns) != 89:
        raise ValueError("This adapter accepts only the approved 89-turn reference episode")
    if len(captions) != 277 or len(scenes) != 36:
        raise ValueError("Expected the approved 277 captions and 36 concept intervals")
    for sequence in (timeline["turns"], captions, scenes):
        previous_end = 0.0
        for item in sequence:
            if not (previous_end <= item["start"] < item["end"] <= 1791.36):
                raise ValueError("Timing is invalid, overlapping, or outside the episode")
            previous_end = item["end"]
    for turn in turns:
        if turn["speaker"] not in ("A", "B"):
            raise ValueError("Unknown speaker")
    for caption in captions:
        index = caption["turn"]
        if type(index) is not int or not 0 <= index < len(turns):
            raise ValueError("Invalid caption turn reference")
        if caption["speaker"] != turns[index]["speaker"]:
            raise ValueError("Caption speaker does not match its turn")
    for name in (data / "analysis.wav", next(root.glob("Generated*.wav"))):
        with wave.open(str(name), "rb") as audio:
            if (audio.getframerate(), audio.getnchannels(), audio.getsampwidth()) != (24000, 1, 2):
                raise ValueError("Reference WAVs must be PCM16 mono at 24000 Hz")
            if abs(audio.getnframes() / 24000 - 1791.36) > 0.001:
                raise ValueError("Reference WAV duration mismatch")


def stage(assets: Path, output: Path) -> int:
    assets = assets.resolve(strict=True)
    output = output.resolve()
    files = asset_files(assets)
    validate_reference(assets)
    if output == assets or output.is_relative_to(assets):
        raise ValueError("Output must be outside the source asset bundle")
    if output.exists():
        raise ValueError("Output already exists; choose a new directory")
    # All inputs are checked before making an output directory. Partial copies
    # are retained for inspection if a filesystem error interrupts staging.
    output.mkdir(parents=True, exist_ok=False)
    for source, relative in files:
        dest = output / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    for relative in CODE:
        dest = output / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "reference" / relative, dest)
    return len(files)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", type=Path, required=True,
                        help="Existing private functional-podcast bundle")
    parser.add_argument("--output", type=Path, help="New isolated working directory")
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.check_only and args.output is None:
        parser.error("--output is required unless --check-only is used")
    try:
        files = asset_files(args.assets)
        validate_reference(args.assets.resolve())
        if args.check_only:
            print(f"PASS: {len(files)} required private assets; reference timing/WAV formats checked")
        else:
            count = stage(args.assets, args.output)
            print(f"Staged {count} assets and {len(CODE)} source files. Originals unchanged.")
    except (OSError, ValueError, KeyError, TypeError, wave.Error) as error:
        print(f"Preflight failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
