"""Synthetic still-frame tests: no media tools, external fonts, or episode assets."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw, ImageFont

from podcast_video_kit.render import Renderer, _load_portrait, _wrap


_A = (241, 29, 174)
_B = (21, 248, 63)


def pixel_count(image, color):
    return next((count for count, pixel in image.getcolors(1280 * 720) if pixel == color), 0)


def turn(start, end, speaker):
    return dict(start=start, end=end, speaker=speaker)


def cue(start, end, speaker, text):
    return dict(start=start, end=end, speaker=speaker, text=text)


def scene(start, end, title="Compose", body="left = 2\nright = 7", **fields):
    return dict(start=start, end=end, title=title, body=body, **fields)


class RendererTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(TemporaryDirectory())
        self.root = Path(directory)
        self.a, self.b = self.root / "a.png", self.root / "b.png"
        for path, color in ((self.a, _A), (self.b, _B)):
            portrait = Image.new("RGBA", (60, 80), (255, 0, 0, 0))
            ImageDraw.Draw(portrait).ellipse((12, 5, 47, 74), fill=(*color, 255))
            portrait.save(path)
        # Keep the tests portable by using Pillow's embedded scalable font.
        # load_default also calls truetype, using its own in-memory font bytes.
        self.font = self.root / "synthetic.ttf"
        truetype = ImageFont.truetype

        def fixture_font(resource, size, *args, **kwargs):
            if resource == str(self.font):
                return ImageFont.load_default(size=size)
            return truetype(resource, size, *args, **kwargs)

        self.enterContext(patch.object(ImageFont, "truetype", side_effect=fixture_font))

    def renderer(self, turns=(), cues=(), scenes=(), fps=24):
        return Renderer(self.a, self.b, self.font, "Test episode", list(turns), list(cues),
                        list(scenes), fps)

    def assertSamePixels(self, a, b):
        self.assertIsNone(ImageChops.difference(a, b).getbbox())

    def test_wide_close_and_speaker_mapping(self):
        renderer = self.renderer(turns=[turn(2, 4, "B"), turn(0, 2, "A")])
        a_wide = renderer.frame(0, 0.10)
        b_wide = renderer.frame(48, 0.10)
        a_close = renderer.frame(24, 0.10)
        b_close = renderer.frame(72, 0.10)
        for frame in (a_wide, b_wide, a_close, b_close):
            self.assertEqual(frame.size, (1280, 720))
            self.assertEqual(frame.mode, "RGB")
        for frame in (a_wide, b_wide):
            self.assertEqual(frame.getpixel((343, 304)), _A)
            self.assertEqual(frame.getpixel((937, 304)), _B)
        self.assertEqual(a_close.getpixel((822, 297)), _A)
        self.assertEqual(pixel_count(a_close, _B), 0)
        self.assertEqual(b_close.getpixel((822, 297)), _B)
        self.assertEqual(pixel_count(b_close, _A), 0)
        self.assertGreater(pixel_count(a_close, _A), pixel_count(a_wide, _A))

    def test_silence_gates_indicator_without_jitter_or_non_speaker_motion(self):
        renderer = self.renderer(turns=[turn(0, 2, "A")])
        idle = renderer.frame(48, 0)
        self.assertSamePixels(idle, renderer.frame(48, 0.80))
        quiet = renderer.frame(10, 0.0079)
        self.assertSamePixels(idle, quiet)
        live = renderer.frame(10, 0.008)
        self.assertIsNotNone(ImageChops.difference(quiet, live).getbbox())
        self.assertSamePixels(quiet.crop((649, 110, 1225, 527)),
                              live.crop((649, 110, 1225, 527)))
        self.assertSamePixels(quiet.crop((70, 136, 616, 473)),
                              live.crop((70, 136, 616, 473)))
        close_quiet = renderer.frame(24, 0)
        close_live = renderer.frame(24, 0.5)
        for frame in (close_quiet, close_live):
            self.assertEqual(frame.getpixel((822, 297)), _A)
        self.assertSamePixels(close_quiet, renderer.frame(24, float("nan")))

    def test_concept_entry_core_exit_and_independent_captions(self):
        renderer = self.renderer(
            turns=[turn(0, 5, "A")], cues=[cue(1, 4, "B", "Example caption")],
            scenes=[scene(2, 3)],
        )
        entry, entering, core, leaving, returned = [
            renderer.frame(i, 0.12) for i in (48, 51, 60, 69, 72)
        ]
        sample = (822, 297)
        self.assertEqual(entry.getpixel(sample), _A)
        self.assertEqual(returned.getpixel(sample), _A)
        self.assertEqual(pixel_count(core, _A), 0)
        self.assertEqual(pixel_count(core, _B), 0)
        self.assertNotEqual(entering.getpixel(sample), _A)
        self.assertNotEqual(entering.getpixel(sample), core.getpixel(sample))
        self.assertEqual(entering.getpixel(sample), leaving.getpixel(sample))
        self.assertSamePixels(core, renderer.frame(60, 0))
        caption_zone = (56, 542, 1224, 702)
        for frame in (entry, entering, leaving, returned):
            self.assertSamePixels(core.crop(caption_zone), frame.crop(caption_zone))
        self.assertIsNotNone(ImageChops.difference(
            returned.crop(caption_zone), renderer.frame(96, 0.12).crop(caption_zone)
        ).getbbox())

    def test_adjacent_and_one_frame_concept_cards_do_not_reveal_portraits(self):
        renderer = self.renderer(
            turns=[turn(0, 5, "B")], fps=20,
            scenes=[scene(1, 2), scene(2, 3), scene(4, 4.05)],
        )
        for i in (39, 40, 80):
            self.assertEqual(pixel_count(renderer.frame(i, 0.2), _B), 0)
        for i in (60, 81):
            self.assertGreater(pixel_count(renderer.frame(i, 0.2), _B), 0)

    def test_frames_do_not_mutate_assets_or_shared_cache(self):
        source = self.a.read_bytes()
        renderer = self.renderer(turns=[turn(0, 3, "A")], scenes=[scene(1, 2)],
                                 cues=[cue(0, 3, "A", "Caption")])
        for index in (0, 36):
            frame = renderer.frame(index, 0.3)
            original = frame.copy()
            frame.paste((255, 0, 0), (0, 0, 1280, 720))
            self.assertSamePixels(original, renderer.frame(index, 0.3))
        self.assertEqual(source, self.a.read_bytes())

    def test_exif_orientation_and_alpha_are_respected(self):
        rgba = Image.new("RGBA", (12, 30), (255, 40, 80, 0))
        draw = ImageDraw.Draw(rgba)
        draw.rectangle((2, 4, 9, 25), fill=(*_A, 255))
        draw.point((2, 4), fill=(*_B, 255))
        orientation = Image.Exif()
        orientation[274] = 6  # 90° clockwise.
        rgba.save(self.a, exif=orientation)
        loaded = _load_portrait(self.a)
        self.assertEqual(loaded.size, (22, 8))
        self.assertEqual(loaded.getpixel((21, 0)), (*_B, 255))
        self.assertEqual(loaded.getpixel((0, 7)), (*_A, 255))
        palette = Image.new("P", (2, 2))
        palette.putdata((0, 1, 1, 1))
        palette.putpalette((255, 0, 255, 1, 9, 22))
        palette.save(self.b, transparency=0)
        loaded = _load_portrait(self.b)
        self.assertEqual(loaded.getpixel((0, 0))[3], 0)
        self.assertEqual(loaded.getpixel((1, 1)), (1, 9, 22, 255))
        self.assertEqual(pixel_count(self.renderer().frame(0, 0), (255, 0, 255)), 0)

    def test_wrap_uses_pixel_measurement_and_preserves_supplied_text(self):
        font = ImageFont.load_default(size=26)
        width = 170
        text = "Wide WWWWWWWWWWWWWWW   iii\n\nscore = 17\n연속된문자열값확인 e\u0301clair"
        lines = _wrap(text, font, width, max_lines=20)
        self.assertIsNotNone(lines)
        self.assertIn("", lines)
        self.assertIn("score = 17", lines)
        self.assertEqual("".join("".join(lines).split()), "".join(text.split()))
        self.assertFalse(any(line.startswith("\u0301") for line in lines))
        for line in lines:
            left, _, right, _ = font.getbbox(line, anchor="ls")
            self.assertLessEqual(right - left, width)
        self.assertEqual(_wrap("iiiiiiiiii", font, width, 2), ["iiiiiiiiii"])
        self.assertGreater(len(_wrap("WWWWWWWWWW", font, width, 3)), 1)

    def test_explicit_kind_and_body_change_the_card_not_the_outside_frame(self):
        first = self.renderer(scenes=[scene(0, 1, kind="Example")])
        second = self.renderer(scenes=[scene(0, 1, body="left = 5\nright = 7", kind="Example")])
        third = self.renderer(scenes=[scene(0, 1, kind="Definition")])
        core1, core2, core3 = (r.frame(12, 0) for r in (first, second, third))
        self.assertIsNotNone(ImageChops.difference(core1, core2).getbbox())
        self.assertIsNotNone(ImageChops.difference(core1, core3).getbbox())
        self.assertSamePixels(first.frame(24, 0), second.frame(24, 0))

    def test_unattributed_caption_renders_text_without_badge(self):
        renderer = self.renderer(cues=[cue(0, 1, "", "Unattributed words"),
                                       cue(1, 2, "A", "Unattributed words")])
        unknown = renderer.frame(0, 0)
        self.assertGreater(pixel_count(unknown.crop((80, 650, 500, 690)), (248, 242, 230)), 0)
        self.assertEqual(pixel_count(unknown.crop((56, 542, 1224, 702)), (255, 203, 129)), 0)
        self.assertGreater(pixel_count(renderer.frame(24, 0).crop((56, 542, 1224, 702)),
                                       (255, 203, 129)), 0)
        with self.assertRaisesRegex(ValueError, "turns.*speaker must be A or B"):
            self.renderer(turns=[turn(0, 1, "")])

    def test_overfull_copy_fails_preflight_and_invalid_timing_is_rejected(self):
        with self.assertRaisesRegex(ValueError, r"caption at 0s does not fit"):
            self.renderer(cues=[cue(0, 1, "A", "line\n" * 30)])
        with self.assertRaisesRegex(ValueError, r"scene body at 0s does not fit"):
            self.renderer(scenes=[scene(0, 1, body="line\n" * 30)])
        with self.assertRaisesRegex(ValueError, "turns intervals must not overlap"):
            self.renderer(turns=[turn(0, 2, "A"), turn(1, 3, "B")])
        with self.assertRaisesRegex(ValueError, "speaker must be A or B"):
            self.renderer(cues=[cue(0, 1, "C", "Hello")])
        with self.assertRaisesRegex(ValueError, "finite"):
            self.renderer(scenes=[scene(0, float("inf"))])
        with self.assertRaisesRegex(ValueError, "positive and finite"):
            self.renderer(fps=0)
        with self.assertRaisesRegex(ValueError, "non-negative"):
            self.renderer().frame(-1, 0)


if __name__ == "__main__":
    unittest.main()
