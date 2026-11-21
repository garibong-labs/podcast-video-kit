import ast
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import stage_reference as staging


class StagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.assets = self.base / "assets"
        self.assets.mkdir()
        for name in staging.REQUIRED:
            path = self.assets / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"synthetic fixture")
        (self.assets / "Generated synthetic.wav").write_bytes(b"synthetic narration")

    def test_exact_allowlist(self):
        (self.assets / "unrelated-private-note.txt").write_text("synthetic excluded note")
        self.assertEqual(len(staging.asset_files(self.assets)), 20)
        self.assertNotIn("unrelated-private-note.txt", [str(rel) for _, rel in staging.asset_files(self.assets)])

    def test_missing_input_rejected(self):
        (self.assets / staging.REQUIRED[0]).unlink()
        with self.assertRaises(FileNotFoundError):
            staging.asset_files(self.assets)

    def test_duplicate_narration_rejected(self):
        (self.assets / "Generated extra.wav").write_bytes(b"duplicate")
        with self.assertRaisesRegex(ValueError, "exactly one"):
            staging.asset_files(self.assets)

    def test_escape_symlink_rejected(self):
        outside = self.base / "outside.jpg"
        outside.write_bytes(b"outside")
        target = self.assets / staging.REQUIRED[0]
        target.unlink()
        target.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "inside"):
            staging.asset_files(self.assets)

    def test_copy_preserves_originals_and_uses_repo_code(self):
        malicious = self.assets / "full-local/render_revoice_swapped.py"
        malicious.write_text("raise RuntimeError('must not execute or copy')")
        output = self.base / "output"
        with patch.object(staging, "validate_reference"):
            self.assertEqual(staging.stage(self.assets, output), 20)
        self.assertEqual((output / staging.CODE[0]).read_bytes(),
                         (staging.ROOT / "reference" / staging.CODE[0]).read_bytes())
        for source, rel in staging.asset_files(self.assets):
            self.assertEqual(source.read_bytes(), (output / rel).read_bytes())
            self.assertFalse((output / rel).is_symlink())
        target = output / staging.REQUIRED[0]
        target.write_bytes(b"changed output")
        self.assertEqual((self.assets / staging.REQUIRED[0]).read_bytes(), b"synthetic fixture")

    def test_existing_output_rejected(self):
        output = self.base / "output"
        output.mkdir()
        marker = output / "keep.txt"
        marker.write_text("keep")
        with patch.object(staging, "validate_reference"), self.assertRaisesRegex(ValueError, "already exists"):
            staging.stage(self.assets, output)
        self.assertEqual(marker.read_text(), "keep")

    def test_nested_output_rejected(self):
        with patch.object(staging, "validate_reference"), self.assertRaisesRegex(ValueError, "outside"):
            staging.stage(self.assets, self.assets / "output")

    def test_check_only_no_writes(self):
        before = sorted(str(p.relative_to(self.assets)) for p in self.assets.rglob("*"))
        with patch.object(staging, "validate_reference"), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(staging.main(["--assets", str(self.assets), "--check-only"]), 0)
        after = sorted(str(p.relative_to(self.assets)) for p in self.assets.rglob("*"))
        self.assertEqual(before, after)

    def test_missing_assets_clean_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(staging.main(["--assets", str(self.base / "missing"), "--check-only"]), 1)

    def test_invalid_reference_counts(self):
        data = self.assets / "full-local/revoice-swapped"
        (data / "timeline.json").write_text(json.dumps({"duration": 1.0, "turns": []}))
        (data / "captions.json").write_text("[]")
        (data / "scenes.json").write_text("[]")
        with self.assertRaisesRegex(ValueError, "89-turn"):
            staging.validate_reference(self.assets)

    def write_fixture_metadata(self, duration=1791.36, caption_speaker="A", caption_turn=0):
        data = self.assets / "full-local/revoice-swapped"
        def intervals(count):
            return [{"start": i, "end": i + 0.5} for i in range(count)]
        turns = [dict(item, speaker="A") for item in intervals(89)]
        caps = [dict(item, speaker=caption_speaker, turn=caption_turn) for item in intervals(277)]
        (data / "timeline.json").write_text(json.dumps({"duration": duration, "turns": turns}))
        (data / "captions.json").write_text(json.dumps(caps))
        (data / "scenes.json").write_text(json.dumps(intervals(36)))

    def test_nonfinite_reference_duration_rejected(self):
        self.write_fixture_metadata(duration=float("nan"))
        with self.assertRaisesRegex(ValueError, "89-turn"):
            staging.validate_reference(self.assets)

    def test_caption_speaker_must_match_turn(self):
        self.write_fixture_metadata(caption_speaker="B")
        with self.assertRaisesRegex(ValueError, "speaker does not match"):
            staging.validate_reference(self.assets)

    def test_caption_turn_must_be_valid_index(self):
        for index in (999, -1, True, 0.0):
            with self.subTest(index=index):
                self.write_fixture_metadata(caption_turn=index)
                with self.assertRaisesRegex(ValueError, "Invalid caption turn"):
                    staging.validate_reference(self.assets)

    def test_sources_parse_without_importing_side_effects(self):
        for source in (staging.ROOT / "reference").rglob("*.py"):
            ast.parse(source.read_text())

    def test_mapping_and_frame_contract(self):
        source = (staging.ROOT / "reference/full-local/render_revoice_swapped.py").read_text()
        self.assertIn("visual_who={'A':'B','B':'A',None:None}[who]", source)
        self.assertIn("studio=host(shot(t,visual_who),visual_who,int(states[i]))", source)
        self.assertIn("'-c:a','copy'", source)
        manifest = json.loads((staging.ROOT / "docs/reference-provenance.json").read_text())
        self.assertEqual(manifest["frames"], round(manifest["duration"] * manifest["fps"]))


if __name__ == "__main__":
    unittest.main()
