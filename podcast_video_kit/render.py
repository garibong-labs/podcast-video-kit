"""Local 1280 × 720 Pillow renderer for podcast still portraits and timed text.

Construct ``Renderer(portrait_a, portrait_b, font_path, title, turns, cues,
scenes, fps=24)`` and call ``frame(index, rms)`` with a zero-based frame index
and linear, normalized PCM RMS (0–1). The returned RGB image belongs to the
caller. This module does not align text or read, modify, or encode audio/video.

Timeline entries use finite start/end seconds (start inclusive, end exclusive).
Each list may be unordered, but entries within a list may not overlap. Turns
and cues use logical speaker ``A`` or ``B``; cues include ``text`` and may use
``speaker=""`` for unattributed text with no badge. Scenes have ``title``, plain
multiline ``body``, and optional ``kind`` (a literal label, not a template
selector). No values are calculated and no content is inferred.
Captions follow their own timeline, including across scene cuts and silence.
Pass exact unmatched-word intervals as ``unmatched_words`` to use the neutral
studio shot during those intervals. An optional ``frame_window`` of absolute
frame indices limits text layout and frame requests to that window.

Portraits are EXIF-oriented, contain-fitted without cropping visible pixels,
and composited with alpha over colored mattes. Only the first image of an
animated source is used. The current speaker gets a lit label and level meter
above the silence threshold. Optional ``mouth_motion`` landmarks add cached
audio-driven poses to that speaker only, not face detection or phoneme lip sync.
The turn, not the RMS, controls the camera; it stays put during
brief silence. There is no font fallback; supply a scalable font with glyphs
and shaping support for the episode's languages. Wrapping keeps the original
separators within caption lines, normalizes other horizontal whitespace,
preserves explicit newlines, and may split an overwide token. If
copy still cannot fit at the minimum type size, construction raises ValueError
instead of clipping or dropping text. Split dense cues or cards upstream.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
import math
import operator
from pathlib import Path
import re
import unicodedata

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

from .mouth import Mouth, POSE_COUNT, mouth_level, parse_mouth_motion


_SIZE = (1280, 720)
_SILENCE_RMS = 0.008  # Linear full-scale PCM, about -42 dBFS.
_CONCEPT_TITLE_Y = 183
_CONCEPT_BODY_GAP = 25
_CONCEPT_TEXT_BOTTOM = 505
_TITLE_FONT_SIZE = 36
_INK = "#17262d"
_PAPER = "#f6efe1"
_LIGHT = "#f8f2e6"
_MUTED = "#a8bec0"
_ACCENT = {"A": "#ffcb81", "B": "#8ee4cf"}
_MATTE = {
    "A": ((102, 65, 50), (52, 37, 38)),
    "B": ((45, 89, 83), (26, 49, 57)),
}
_WIDE_PANELS = {"A": (56, 122, 574, 404, 46), "B": (650, 122, 574, 404, 46)}
_CLOSE_PANEL = (420, 108, 804, 418, 9)


@dataclass(frozen=True)
class _Timeline:
    starts: tuple[float, ...]
    ends: tuple[float, ...]
    rows: tuple[dict, ...]

    @classmethod
    def build(cls, name: str, entries: Iterable[dict]) -> _Timeline:
        intervals = []
        for i, item in enumerate(entries):
            try:
                start, end = float(item["start"]), float(item["end"])
            except (KeyError, ValueError, TypeError, OverflowError) as exc:
                raise ValueError(f"{name}[{i}] requires numeric start and end seconds") from exc
            if not (0 <= start < end and math.isfinite(end)):
                raise ValueError(f"{name}[{i}] requires finite 0 <= start < end")
            if name == "turns" and item.get("speaker") not in ("A", "B"):
                raise ValueError(f"{name}[{i}].speaker must be A or B")
            if name == "cues" and item.get("speaker") not in ("A", "B", ""):
                raise ValueError(f"{name}[{i}].speaker must be A or B, or empty")
            required = {"cues": ("text",), "scenes": ("title", "body")}.get(name, ())
            for key in required + (("kind",) if name == "scenes" and "kind" in item else ()):
                if not isinstance(item.get(key), str):
                    raise ValueError(f"{name}[{i}].{key} must be a string")
            intervals.append((start, end, item.copy()))
        intervals.sort(key=lambda interval: interval[0])
        for previous, current in zip(intervals, intervals[1:]):
            if current[0] < previous[1]:
                raise ValueError(f"{name} intervals must not overlap ({current[0]:g}s)")
        return cls(
            tuple(row[0] for row in intervals), tuple(row[1] for row in intervals),
            tuple(row[2] for row in intervals),
        )

    def at(self, time: float) -> int:
        i = bisect_right(self.starts, time) - 1
        return i if i >= 0 and time < self.ends[i] else -1

    def visible(self, frames: range, fps: float) -> Iterator[tuple[int, float]]:
        """Yield each sampled row's original index and its last sampled time."""
        def time(index: int) -> float:
            return index / fps

        for i, (start, end) in enumerate(zip(self.starts, self.ends)):
            stop = bisect_left(frames, end, key=time)
            if stop and (sample := time(frames[stop - 1])) >= start:
                yield i, sample


def load_font(path: Path, size: int = _TITLE_FONT_SIZE) -> ImageFont.FreeTypeFont:
    if not Path(path).is_file():
        raise ValueError(f"Font file not found: {path}; use --font or PVK_FONT")
    try:
        # Use truetype's underlying loader without its system-font search.
        return ImageFont.FreeTypeFont(str(path), size)
    except OSError as exc:
        raise ValueError(f"Cannot load font {path}: {exc}; use --font or PVK_FONT") from exc


def _gradient(size: tuple[int, int], top: tuple, bottom: tuple) -> Image.Image:
    strip = Image.new("RGB", (1, size[1]))
    height = max(1, size[1] - 1)
    strip.putdata([
        tuple(round(a + (b - a) * y / height) for a, b in zip(top, bottom))
        for y in range(size[1])
    ])
    return strip.resize(size)


def _load_portrait(path: Path) -> Image.Image:
    return _read_portrait(path)[0]


def _read_portrait(path, point=None, speaker=None):
    try:
        with Image.open(path) as source:
            portrait = ImageOps.exif_transpose(source).convert("RGBA")
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError(f"Cannot decode portrait {path}: {exc}") from exc
    bounds = portrait.getbbox()  # RGBA getbbox uses alpha, not hidden RGB values.
    if bounds is None:
        raise ValueError(f"Cannot use portrait {path}: portrait is fully transparent")
    mouth = Mouth.locate(portrait, bounds, point, speaker) if point is not None else None
    return (portrait.crop(bounds) if bounds != (0, 0, *portrait.size) else portrait), mouth


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: int, max_lines: int,
          *, preserve_spacing: bool = False) -> list[str] | None:
    """Use ink bounds (including overhangs), preserving all non-whitespace text."""
    def fits(line: str) -> bool:
        left, _, right, _ = font.getbbox(line, anchor="ls")
        return right - left <= width

    lines = []
    for paragraph in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = ""
        previous_end = 0
        for match in re.finditer(r"\S+", paragraph):
            separator = paragraph[previous_end:match.start()] if preserve_spacing else " "
            previous_end = match.end()
            word = match[0]
            joined = line + separator + word if line else word
            if fits(joined):
                line = joined
                continue
            if line:
                lines.append(line)
                if len(lines) >= max_lines:
                    return None
                line = ""
            if joined != word and fits(word):
                line = word
                continue
            # Break long identifiers and unspaced CJK text. Keep common combining
            # marks and joiner sequences attached; not full Unicode segmentation.
            cluster = ""
            for char in word:
                joins = unicodedata.category(char).startswith("M") or char == "\u200d"
                joins |= "\U0001f3fb" <= char <= "\U0001f3ff"
                if not cluster or joins or cluster.endswith("\u200d"):
                    cluster += char
                    continue
                if not fits(line + cluster):
                    if not line or not fits(cluster):
                        return None
                    lines.append(line)
                    if len(lines) >= max_lines:
                        return None
                    line = ""
                line += cluster
                cluster = char
            if not fits(line + cluster):
                if not line or not fits(cluster):
                    return None
                lines.append(line)
                if len(lines) >= max_lines:
                    return None
                line = ""
            line += cluster
        lines.append(line)
        if len(lines) > max_lines:
            return None
    return lines


@dataclass(frozen=True)
class _Text:
    font: ImageFont.FreeTypeFont
    lines: tuple[tuple[str, int], ...]
    step: int
    top: int
    height: int

    def draw(self, draw: ImageDraw.ImageDraw, xy: tuple[int, int], fill: str) -> None:
        x, y = xy
        for i, (line, left) in enumerate(self.lines):
            draw.text((x - left, y - self.top + i * self.step), line,
                      fill=fill, font=self.font, anchor="ls")


class Renderer:
    """Deterministic frame renderer; see the module docstring for the input contract."""

    def __init__(
        self, portrait_a: Path, portrait_b: Path, font_path: Path, title: str,
        turns: list[dict], cues: list[dict], scenes: list[dict], fps: float = 24,
        *, unmatched_words: Iterable[dict] = (), frame_window: range | None = None,
        mouth_motion: dict | None = None,
    ) -> None:
        self._fps = float(fps)
        if not (0 < self._fps < math.inf):
            raise ValueError("fps must be positive and finite")
        self._turns = _Timeline.build("turns", turns)
        self._cues = _Timeline.build("cues", cues)
        self._scenes = _Timeline.build("scenes", scenes)
        self._unmatched_words = _Timeline.build("unmatched words", unmatched_words)
        self._frame_window = frame_window
        self._font_path = font_path
        self._fonts: dict[int, ImageFont.FreeTypeFont] = {}
        self._title = self._fit(title, 888, 47, _TITLE_FONT_SIZE, 20, "episode title", max_lines=1)
        if frame_window is None:
            caption_indices = range(len(self._cues.rows))
            scene_indices = range(len(self._scenes.rows))
        else:
            caption_indices = [i for i, _ in self._cues.visible(frame_window, self._fps)]
            # A sampled card can have zero opacity only at its opening instant.
            scene_indices = [i for i, time in self._scenes.visible(frame_window, self._fps)
                             if self._scene_mix(i, time) > 0]
        self._caption_text = [None] * len(self._cues.rows)
        for i in caption_indices:
            row, start = self._cues.rows[i], self._cues.starts[i]
            self._caption_text[i] = self._fit(
                row["text"], 976 if row["speaker"] else 1104,
                132, 36, 19, f"caption at {start:g}s", preserve_spacing=True,
            )
        self._scene_text = [None] * len(self._scenes.rows)
        for i in scene_indices:
            self._scene_text[i] = self._layout_concept(self._scenes.starts[i], self._scenes.rows[i])
        self._studio = _gradient(_SIZE, (26, 45, 54), (13, 25, 34))
        points = parse_mouth_motion(mouth_motion) if mouth_motion is not None else {}
        studios, mouths = {}, {}
        for speaker, path in (("A", portrait_a), ("B", portrait_b)):
            studios[speaker], mouths[speaker] = _read_portrait(path, points.get(speaker), speaker)
        # Seven static frames: idle wide, live wide for either host, and quiet/live
        # close frames for either host. Source images are released after setup.
        self._room_frames = self._make_rooms(studios)
        self._mouth_patches = self._make_mouth_patches(studios, mouths)
        self._last_scene: tuple[int, Image.Image] | None = None
        self._last_caption: tuple[int, int, Image.Image] | None = None

    def _font(self, size: int) -> ImageFont.FreeTypeFont:
        if size not in self._fonts:
            self._fonts[size] = load_font(self._font_path, size)
        return self._fonts[size]

    def _fit(
        self, text: str, width: int, height: int, size: int, minimum: int,
        field: str, max_lines: int | None = None, *, preserve_spacing: bool = False,
    ) -> _Text:
        layout = next(self._fitting_text(
            text, width, height, size, minimum, max_lines, preserve_spacing=preserve_spacing,
        ), None)
        if layout is None:
            raise ValueError(f"{field} does not fit; shorten the title or split the text")
        return layout

    def _fitting_text(
        self, text: str, width: int, height: int, size: int, minimum: int,
        max_lines: int | None = None, *, preserve_spacing: bool = False,
    ) -> Iterator[_Text]:
        for point in range(size, minimum - 1, -1):
            font = self._font(point)
            ascent, descent = font.getmetrics()
            gap = max(2, point // 7)
            limit = height // (ascent + descent + gap) + 1
            if max_lines is not None:
                limit = min(limit, max_lines)
            lines = _wrap(text, font, width, limit, preserve_spacing=preserve_spacing)
            if lines is None:
                continue
            boxes = [font.getbbox(line, anchor="ls") for line in lines]
            top, bottom = min(b[1] for b in boxes), max(b[3] for b in boxes)
            step = max(ascent + descent, bottom - top) + gap
            block_height = (len(lines) - 1) * step + bottom - top
            if block_height <= height:
                yield _Text(font, tuple((line, box[0]) for line, box in zip(lines, boxes)),
                            step, top, block_height)

    def _label(self, draw: ImageDraw.ImageDraw, x: int, y: int, text: str,
               fill: str, size: int = 19) -> None:
        draw.text((x, y), text, font=self._font(size), fill=fill, anchor="lm")

    def _layout_concept(self, start: float, row: dict) -> tuple[_Text, _Text, _Text]:
        kind = self._fit(row.get("kind", "CONCEPT"), 910, 27, 19, 14,
                         f"scene kind at {start:g}s", max_lines=1)
        # Try the largest title first to preserve cards that already fit. If its
        # remaining space cannot fit the body at any size, try a smaller title.
        field = "title"
        for title in self._fitting_text(row["title"], 954, 124, 54, 27):
            field = "body"
            height = _CONCEPT_TEXT_BOTTOM - _CONCEPT_TITLE_Y - _CONCEPT_BODY_GAP - title.height
            body = next(self._fitting_text(row["body"], 954, height, 35, 20), None)
            if body is not None:
                return kind, title, body
        raise ValueError(f"scene {field} at {start:g}s does not fit; shorten the title or split the text")

    def _header(self, draw: ImageDraw.ImageDraw, label: str) -> None:
        draw.rounded_rectangle((57, 44, 64, 76), radius=3, fill="#edaa75")
        self._title.draw(draw, (80, 59 - self._title.height // 2), _LIGHT)
        draw.rounded_rectangle((1038, 43, 1223, 77), radius=17, outline="#527078")
        self._label(draw, 1057, 60, label, _MUTED, 17)
        draw.line((56, 96, 1224, 96), fill="#45606a")

    @staticmethod
    def _portrait_tile(portrait: Image.Image, speaker: str, size: tuple[int, int],
                       inset: int) -> Image.Image:
        tile = _gradient(size, *_MATTE[speaker]).convert("RGBA")
        draw = ImageDraw.Draw(tile)
        center_x, center_y = size[0] // 2, size[1] // 2
        radius = min(size) // 2 - 10
        color = "#927059" if speaker == "A" else "#508279"
        draw.ellipse((center_x - radius, center_y - radius, center_x + radius,
                      center_y + radius), outline=color, width=2)
        draw.line((20, center_y, size[0] - 20, center_y), fill=color)
        scale = min((size[0] - 2 * inset) / portrait.width,
                    (size[1] - 2 * inset) / portrait.height)
        dimensions = tuple(max(1, round(length * scale)) for length in portrait.size)
        fitted = portrait.resize(dimensions, Image.Resampling.LANCZOS)
        tile.alpha_composite(fitted, ((size[0] - fitted.width) // 2,
                                      (size[1] - fitted.height) // 2))
        return tile.convert("RGB")

    def _make_rooms(self, portraits: dict[str, Image.Image]) -> dict[tuple[str, str], Image.Image]:
        base = self._studio.copy()
        self._header(ImageDraw.Draw(base), "TWO HOSTS   /   2D")
        rooms = {}
        wide = base.copy()
        for speaker, panel in _WIDE_PANELS.items():
            self._panel(wide, portraits[speaker], speaker, *panel)
        rooms["wide", ""] = wide
        for speaker, panel in _WIDE_PANELS.items():
            hot = wide.copy()
            self._panel_label(hot, speaker, *panel[:4], True)
            rooms["wide", speaker] = hot

            # The close is a larger uncropped view of the same asset, not a
            # digital crop. Negative space introduces the focus title at left.
            close = base.copy()
            draw = ImageDraw.Draw(close)
            draw.line((94, 182, 346, 182), fill="#45606a", width=2)
            draw.line((94, 422, 346, 422), fill="#45606a", width=2)
            self._label(draw, 94, 215, "IN CONVERSATION", _MUTED)
            self._label(draw, 88, 301, speaker, _ACCENT[speaker], 132)
            self._label(draw, 94, 390, f"SPEAKER {speaker}  /  CLOSE", _LIGHT)
            self._panel(close, portraits[speaker], speaker, *_CLOSE_PANEL)
            rooms[speaker, ""] = close
            hot = close.copy()
            self._panel_label(hot, speaker, *_CLOSE_PANEL[:4], True)
            rooms[speaker, speaker] = hot
        return rooms

    def _panel(self, frame: Image.Image, portrait: Image.Image, speaker: str,
               x: int, y: int, w: int, h: int, inset: int) -> None:
        draw = ImageDraw.Draw(frame)
        draw.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=20,
                               fill="#1a3039", outline="#48636a", width=2)
        tile = self._portrait_tile(portrait, speaker, (w - 28, h - 67), inset)
        frame.paste(tile, (x + 14, y + 14))
        self._panel_label(frame, speaker, x, y, w, h, False)

    def _make_mouth_patches(self, portraits, mouths):
        patches = {}
        for speaker, mouth in mouths.items():
            if mouth is None:
                continue
            portrait = portraits[speaker]
            views = [(view, (x + 14, y + 14), (w - 28, h - 67), inset)
                     for view, (x, y, w, h, inset) in
                     (("wide", _WIDE_PANELS[speaker]), (speaker, _CLOSE_PANEL))]
            resting = [self._portrait_tile(portrait, speaker, size, inset)
                       for _, _, size, inset in views]
            for level in range(1, POSE_COUNT):
                posed = mouth.pose(portrait, level)
                for (view, (x, y), size, inset), rest in zip(views, resting):
                    tile = self._portrait_tile(posed, speaker, size, inset)
                    if (box := ImageChops.difference(rest, tile).getbbox()) is not None:
                        patches[view, speaker, level] = tile.crop(box), (x + box[0], y + box[1])
        return patches

    def _panel_label(self, frame: Image.Image, speaker: str, x: int, y: int,
                     w: int, h: int, live: bool) -> None:
        draw = ImageDraw.Draw(frame)
        color = _ACCENT[speaker] if live else _MUTED
        cy = y + h - 27
        draw.rounded_rectangle((x + 15, cy - 17, x + 162, cy + 17), radius=17,
                               fill=color if live else "#314952")
        self._label(draw, x + 31, cy, f"SPEAKER {speaker}", _INK if live else _LIGHT)
        if live:
            draw.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=20,
                                   outline=color, width=2)
            self._label(draw, x + w - 152, cy, "LIVE", color, 16)

    def _room(self, time: float, rms: float) -> Image.Image:
        i = self._turns.at(time)
        if i < 0 or self._unmatched_words.at(time) >= 0:
            return self._room_frames["wide", ""].copy()
        speaker = self._turns.rows[i]["speaker"]
        close = (time - self._turns.starts[i]) % 6.0 >= 0.60
        live = math.isfinite(rms) and rms >= _SILENCE_RMS
        view = speaker if close else "wide"
        frame = self._room_frames[view, speaker if live else ""].copy()
        if live:
            if self._mouth_patches:
                patch = self._mouth_patches.get((view, speaker, mouth_level(rms, _SILENCE_RMS)))
                if patch is not None:
                    frame.paste(*patch)
            draw = ImageDraw.Draw(frame)
            right = 630 if not close and speaker == "A" else 1224
            lit = min(6, 1 + int(min(1.0, rms) * 28))
            for n in range(6):
                x, half_height = right - 95 + n * 12, 3 + n
                draw.rounded_rectangle((x, 499 - half_height, x + 6, 499 + half_height),
                                       radius=2, fill=_ACCENT[speaker] if n < lit else "#384f55")
        return frame

    def _concept(self, i: int) -> Image.Image:
        if self._last_scene is not None and self._last_scene[0] == i:
            return self._last_scene[1]
        frame = self._studio.copy()
        draw = ImageDraw.Draw(frame)
        self._header(draw, "CONCEPT CARD")
        draw.rounded_rectangle((57, 124, 1233, 535), radius=25, fill="#081820")
        draw.rounded_rectangle((56, 114, 1224, 526), radius=25, fill=_PAPER)
        draw.rounded_rectangle((84, 143, 96, 496), radius=5, fill="#ce744d")
        kind, title, body = self._scene_text[i]
        kind.draw(draw, (124, 145), "#823a26")
        self._label(draw, 1060, 158, f"CARD / {i + 1:02}", "#823a26", 17)
        title.draw(draw, (124, _CONCEPT_TITLE_Y), _INK)
        body_y = _CONCEPT_TITLE_Y + title.height + _CONCEPT_BODY_GAP
        draw.line((124, body_y - 12, 1156, body_y - 12), fill="#d6c1a8", width=2)
        body.draw(draw, (124, body_y), _INK)
        self._last_scene = (i, frame)
        return frame

    def _caption(self, i: int) -> tuple[int, Image.Image]:
        if self._last_caption is not None and self._last_caption[0] == i:
            _, y, patch = self._last_caption
            return y, patch
        speaker = self._cues.rows[i]["speaker"]
        text = self._caption_text[i]
        # Reserve y >= 542 for captions; bottom edge is always at y=702.
        height = max(60, text.height + 28)
        patch = Image.new("RGB", (1168, height), "#101d27")
        draw = ImageDraw.Draw(patch)
        draw.rectangle((0, 0, 1167, height - 1), outline="#506771")
        if speaker:
            draw.rounded_rectangle((17, 13, 70, 46), radius=16, fill=_ACCENT[speaker])
            self._label(draw, 36, 29, speaker, _INK, 21)
            draw.line((90, 14, 90, height - 15), fill="#506771")
        text.draw(draw, (112 if speaker else 24, (height - text.height) // 2), _LIGHT)
        y = 702 - height
        self._last_caption = (i, y, patch)
        return y, patch

    def _scene_mix(self, scene: int, time: float) -> float:
        start, end = self._scenes.starts[scene], self._scenes.ends[scene]
        # Cut between directly adjacent text cards and across very short cards.
        cut_in = scene > 0 and self._scenes.ends[scene - 1] == start
        cut_out = scene + 1 < len(self._scenes.rows) and self._scenes.starts[scene + 1] == end
        fade = min(0.25, (end - start) / 4)
        mix = 1.0
        if fade >= 1 / self._fps:
            if not cut_in:
                mix = min(mix, (time - start) / fade)
            if not cut_out:
                mix = min(mix, (end - time) / fade)
        return mix

    def frame(self, index: int, rms: float) -> Image.Image:
        """Return a fresh 1280 × 720 RGB still at ``index / fps``."""
        index = operator.index(index)
        if index < 0:
            raise ValueError("frame index must be non-negative")
        if self._frame_window is not None and index not in self._frame_window:
            raise ValueError("frame index falls outside the renderer's window")
        time = index / self._fps
        scene = self._scenes.at(time)
        mix = self._scene_mix(scene, time) if scene >= 0 else 0.0
        if mix == 0.0:
            image = self._room(time, rms)
        else:
            concept = self._concept(scene)
            image = concept.copy() if mix >= 1.0 else Image.blend(self._room(time, rms), concept, mix)
        cue = self._cues.at(time)
        if cue >= 0:
            y, patch = self._caption(cue)
            image.paste(patch, (56, y))
        return image
