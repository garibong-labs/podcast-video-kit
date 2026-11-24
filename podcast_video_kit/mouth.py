"""Local, amplitude-driven portrait poses; no face model or external assets."""

from dataclasses import dataclass
import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter


POSE_COUNT = 4  # Resting pose is the original portrait, plus three open poses.


def parse_mouth_motion(value):
    if not isinstance(value, dict) or not value or value.keys() - {'A', 'B'}:
        raise ValueError('mouth_motion must be an object with A and/or B landmarks')
    result = {}
    for speaker, point in value.items():
        if not (isinstance(point, (list, tuple)) and len(point) == 3
                and all(type(n) in (int, float) and 0 < n < 1 for n in point)):
            raise ValueError(f'mouth_motion.{speaker} needs [x, y, width], each between 0 and 1')
        result[speaker] = tuple(point)
    return result


@dataclass(frozen=True)
class Mouth:
    box: tuple[int, int, int, int]
    center: tuple[float, float]
    width: float

    @classmethod
    def locate(cls, image, bounds, point, speaker):
        x, y, width = point
        cx, cy, w = x * image.width, y * image.height, width * image.width
        left, top = math.floor(cx - .72*w), math.floor(cy - .38*w)
        right, bottom = math.ceil(cx + .72*w), math.ceil(cy + .38*w)
        l, t, r, b = bounds
        if not (w >= 8 and l <= left < right <= r and t <= top < bottom <= b
                and image.getpixel((int(cx), int(cy)))[3] >= 128):
            raise ValueError(f'mouth_motion.{speaker} needs an opaque mouth center and '
                             'a usable lip area inside the portrait')
        return cls((left-l, top-t, right-l, bottom-t), (cx-left, cy-top), w)

    def pose(self, image, level):
        """Stretch the local lip band, feather its edges, and paint a small cavity."""
        patch = image.crop(self.box)
        width, height = patch.size
        cx, cy = self.center
        lip_half = max(1, round(self.width * .06))
        opening = self.width * .035 * level
        stretch = max(1, round(opening))
        inner_start, inner_end = round(cy) - lip_half, round(cy) + lip_half
        stops = (0, inner_start, inner_end, height)
        stretched = (0, inner_start-stretch, inner_end+stretch, height)
        rgb = patch.convert('RGB')
        warped = Image.new('RGBA', patch.size)
        for i in range(3):
            strip = patch.crop((0, stops[i], width, stops[i+1]))
            warped.paste(strip.resize((width, stretched[i+1]-stretched[i]),
                                      Image.Resampling.BILINEAR), (0, stretched[i]))

        def ellipse_mask(rx, ry, scale):
            mask = Image.new('L', (width*scale, height*scale))
            ImageDraw.Draw(mask).ellipse(tuple(round(n*scale) for n in
                                              (cx-rx, cy-ry, cx+rx, cy+ry)), fill=255)
            return mask if scale == 1 else mask.resize(patch.size, Image.Resampling.LANCZOS)

        color = rgb.getpixel((int(cx), int(cy)))
        cavity = Image.new('RGB', patch.size, tuple(round(c * .30) for c in color))
        texture = Image.composite(warped.convert('RGB'), rgb, warped.getchannel('A'))
        # Close views can enlarge a portrait even when its mouth is wide in source pixels.
        texture = Image.composite(cavity, texture, ellipse_mask(self.width*.40, opening*.82, 2))
        mask = ellipse_mask(self.width*.60, self.width*.32, 2 if self.width < 100 else 1)
        # A soft boundary keeps stationary skin and hair unchanged beyond the patch.
        mask = mask.filter(ImageFilter.GaussianBlur(max(.5, self.width*.028)))
        alpha = patch.getchannel('A')
        posed = Image.composite(texture, rgb, ImageChops.multiply(mask, alpha))
        posed.putalpha(alpha)
        result = image.copy()
        result.paste(posed, self.box[:2])
        return result


def mouth_level(rms, threshold):
    if not math.isfinite(rms) or rms < threshold:
        return 0
    # Logarithmic gain avoids hitting the widest pose on every syllable.
    return min(POSE_COUNT - 1, 1 + int(math.log2(min(rms, 1.0) / threshold) / 1.5))
