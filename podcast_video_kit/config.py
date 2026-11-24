"""Read and validate the local episode manifest before using any media inputs."""
from __future__ import annotations

from argparse import Namespace
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import json
from pathlib import Path
import re


_REQUIRED_PATHS = ('script', 'narration', 'portrait_a', 'portrait_b', 'output')
_OPTIONAL_PATHS = ('words_json', 'whisper_model', 'font')
_PRESENTATION = ('title', 'scenes', 'mouth_motion')
_KEYS = frozenset(_REQUIRED_PATHS + _OPTIONAL_PATHS + _PRESENTATION + (
    'section', 'language', 'timing_mode', 'preview', 'preview_start', 'plan_only',
))


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f'Duplicate key in episode config: {key!r}')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError(f'Invalid JSON number in episode config: {value}')


def _decimal(value):
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('JSON number is out of range in episode config') from exc


def _seconds(config, key, *, minimum, maximum, allow_zero=False):
    value = config[key]
    # Check bounds before converting integers to floats or fractions.
    if (type(value) not in (int, Decimal) or not minimum <= value <= maximum
            or (not allow_zero and value == 0)):
        constraint = f'between {minimum} and {maximum}' if allow_zero else f'greater than 0 and up to {maximum}'
        raise ValueError(f'{key} must be a number of seconds {constraint}')
    if not value:
        return Fraction(0)
    if isinstance(value, Decimal) and value.adjusted() < -12:
        # Positive sub-picosecond lengths still select one frame; offsets round to frame zero.
        return Fraction(0 if allow_zero else 1, 10**12)
    return Fraction(value)


def _presentation(value):
    # Presentation keeps the same numeric types as the renderer's former JSON loader.
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return [_presentation(item) for item in value]
    if isinstance(value, dict):
        return {key: _presentation(item) for key, item in value.items()}
    return value


def _path(value, key):
    if not isinstance(value, str) or not value.strip() or '\0' in value:
        raise ValueError(f'{key} must be a nonempty path string')
    try:
        return Path(value).expanduser()
    except RuntimeError as exc:
        raise ValueError(f'Cannot expand the home directory in {key}') from exc


def load_config(path: Path):
    """Return validated run settings and presentation settings separately."""
    path = _path(str(path), 'config').absolute()
    data = json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_object,
                      parse_float=_decimal, parse_constant=_invalid_constant)
    if not isinstance(data, dict):
        raise ValueError('Episode config must be a JSON object')
    unknown = data.keys() - _KEYS
    if unknown:
        raise ValueError('Unknown episode config keys: ' + ', '.join(map(repr, sorted(unknown))))
    missing = [key for key in _REQUIRED_PATHS if key not in data]
    if missing:
        raise ValueError('Missing episode config keys: ' + ', '.join(missing))
    if ('words_json' in data) == ('whisper_model' in data):
        raise ValueError('Set exactly one of words_json or whisper_model in the episode config')
    paths = {key: path.parent / _path(data[key], key) if key in data else None
             for key in _REQUIRED_PATHS + _OPTIONAL_PATHS}

    section = data.get('section', '7. 팟캐스트 대본')
    if not isinstance(section, str) or not section.strip():
        raise ValueError('section must be a nonempty heading string')
    language = data.get('language')
    if 'language' in data and (not isinstance(language, str) or re.fullmatch('[A-Za-z]{2,3}', language) is None):
        raise ValueError('language must be a language code, e.g. ko or en')
    timing_mode = data.get('timing_mode', 'repair')
    if timing_mode not in ('repair', 'strict'):
        raise ValueError('timing_mode must be "repair" or "strict"')

    plan_only = data.get('plan_only', False)
    if not isinstance(plan_only, bool):
        raise ValueError('plan_only must be true or false')
    if plan_only and 'preview' in data:
        raise ValueError('plan_only and preview cannot both be set')
    if 'preview_start' in data and 'preview' not in data:
        raise ValueError('preview_start requires preview')
    preview = _seconds(data, 'preview', minimum=0, maximum=120) if 'preview' in data else None
    preview_start = (_seconds(data, 'preview_start', minimum=0, maximum=7200, allow_zero=True)
                     if 'preview_start' in data else Fraction(0))

    if 'title' in data and not isinstance(data['title'], str):
        raise ValueError('title must be a string')
    if 'scenes' in data and (not isinstance(data['scenes'], list)
                             or any(not isinstance(item, dict) for item in data['scenes'])):
        raise ValueError('scenes must be an array of objects')
    return (Namespace(**paths, section=section, language=language, repair_zero_duration=timing_mode == 'repair',
                      plan_only=plan_only, preview=preview, preview_start=preview_start),
            {key: _presentation(data[key]) for key in _PRESENTATION if key in data})
