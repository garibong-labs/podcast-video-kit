"""Generate a local 2D episode from a script, supplied recording and two portraits."""
from __future__ import annotations

import argparse
from bisect import bisect_left
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory
import wave
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from .episode import (align_with_provenance, captions, check_script_length,
                      concept_scenes, read_words, script, srt)

FPS = 24
SIZE = (1280, 720)
MAC_FONT = Path('/System/Library/Fonts/AppleSDGothicNeo.ttc')


def command(args, capture=False):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE if capture else None).stdout


def json_write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def probe(path, *args):
    return json.loads(command(['ffprobe', '-v', 'error', *args, '-show_streams',
                               '-show_format', '-of', 'json', str(path)], capture=True))


def duration_wav(path):
    with path.open('rb') as src:
        header = src.read(12)
    if header[:4] not in (b'RIFF', b'RF64') or header[8:] != b'WAVE':
        raise ValueError('Narration must be a local WAV file')
    streams = probe(path, '-f', 'wav')['streams']
    if len(streams) != 1 or streams[0]['codec_type'] != 'audio':
        raise ValueError('Narration WAV must contain one audio stream')
    try:
        stream = streams[0]
        seconds = int(stream['duration_ts']) * Fraction(stream['time_base'])
    except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise ValueError('Cannot determine the exact WAV duration from ffprobe') from exc
    if not 0 < seconds <= 7200:
        raise ValueError('Narration must be between 0 and 7200 seconds')
    return seconds


def transcribe(args):
    if args.words_json:
        return args.words_json.read_bytes()
    if not args.whisper_model:
        raise ValueError('Supply an existing local --whisper-model .pt file or --words-json')
    model = args.whisper_model.resolve(strict=True)
    if not model.is_file() or model.suffix.lower() != '.pt':
        raise ValueError('Use an existing trusted Whisper .pt model; no downloads are attempted')
    if args.language is not None and re.fullmatch('[A-Za-z]{2,3}', args.language) is None:
        raise ValueError('--language must be a language code, e.g. ko or en')
    # The subprocess emits a raw transcript named after the input WAV. Never
    # place it under the run directory, which may be inside a Git checkout.
    with TemporaryDirectory(prefix='podcast-video-kit-') as tmp:
        wav = str(args.narration.resolve())
        command(['whisper', wav, '--model', str(model), '--task', 'transcribe',
                 '--device', 'cpu', '--fp16', 'False', '--word_timestamps', 'True',
                 '--output_format', 'json', '--output_dir', tmp, '--verbose', 'False',
                 *(['--language', args.language.lower()] if args.language else [])])
        return (Path(tmp) / (Path(wav).stem + '.json')).read_bytes()


def extract_aac_hash(path):
    cmd = ['ffmpeg', '-nostdin', '-v', 'error', '-i', str(path), '-map', '0:a:0',
           '-c:a', 'copy', '-f', 'adts', 'pipe:1']
    with subprocess.Popen(cmd, stdout=subprocess.PIPE) as proc:
        value = hashlib.file_digest(proc.stdout, 'sha256').hexdigest()
        if proc.wait() != 0:
            raise subprocess.CalledProcessError(proc.returncode, cmd)
    return value


def verify(video, aac, nframes, audio_seconds):
    data = probe(video, '-count_frames')
    image = next(s for s in data['streams'] if s['codec_type'] == 'video')
    audio = next(s for s in data['streams'] if s['codec_type'] == 'audio')
    seconds = float(audio['duration'])
    if ((image['width'], image['height']) != SIZE or image['r_frame_rate'] != '24/1'
            or int(image['nb_read_frames']) != nframes or abs(seconds-audio_seconds) > .05):
        raise ValueError('Encoded output dimensions, frame count, rate or audio duration mismatch')
    command(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(video), '-f', 'null', '-'])
    digest = extract_aac_hash(aac)
    if digest != extract_aac_hash(video):
        raise ValueError('Encoded output AAC does not match the local AAC reference')
    return dict(decode='PASS', frames=nframes, audio_seconds=seconds, aac_sha256=digest,
                width=SIZE[0], height=SIZE[1], fps=FPS)


def _render_window(args, duration):
    # Index previews on the same frame grid, so caption and scene boundaries do not drift.
    total = math.ceil(duration * FPS)
    first, last = 0, total
    if args.preview:
        requested = Fraction(str(args.preview_start))
        if requested < 0 or requested >= duration:
            raise ValueError('Preview starts outside the recording or at its end')
        first = min(total - 1, round(requested * FPS))
        last = min(total, first + math.ceil(Fraction(str(args.preview)) * FPS))
    offset = Fraction(first, FPS)
    return first, last, offset, min(duration, Fraction(last, FPS))


def _validate_cue_frames(cues, first, last, offset, end):
    frames = range(first, last)
    window_start, window_end = float(offset), float(end)
    # Renderer.frame samples index / fps with start inclusive and end exclusive.
    for i, cue in enumerate(cues, 1):
        start = max(window_start, cue['start'])
        stop = min(window_end, cue['end'])
        if start >= stop:
            continue
        j = bisect_left(frames, start, key=lambda index: index / FPS)
        if j == len(frames) or frames[j] / FPS >= stop:
            raise ValueError(f'Caption cue {i} [{cue["start"]}, {cue["end"]}) seconds '
                             f'has no visible frame at {FPS} fps in this render; '
                             'adjust the word timings or preview bounds')


def make_video(args, directory, config, turns, cues, scenes, duration, font, unmatched_words):
    first, last, offset, end = _render_window(args, duration)
    _validate_cue_frames(cues, first, last, offset, end)
    import numpy as np
    from .render import Renderer

    start = float(offset)
    length = float(end-offset)
    renderer = Renderer(args.portrait_a, args.portrait_b, font,
                        config.get('title', 'Podcast'), turns, cues, scenes, fps=FPS,
                        unmatched_words=unmatched_words,
                        frame_window=range(first, last) if args.preview else None)
    audio = directory / 'audio.m4a'
    pcm = directory / 'analysis.wav'
    # Full mode never cuts, stretches, adds silence or resamples the delivery audio deliberately.
    excerpt = ['-ss', str(start), '-t', str(length)] if args.preview else []
    for dest, settings in ((audio, ['-c:a', 'aac', '-b:a', '192k']),
                           (pcm, ['-c:a', 'pcm_s16le', '-ar', '24000', '-ac', '1'])):
        command(['ffmpeg', '-nostdin', '-n', '-v', 'error', '-xerror', '-f', 'wav', '-i',
                 str(args.narration.resolve()), *excerpt, '-map', '0:a:0', *settings, str(dest)])
    partial = directory / 'pending.mp4'
    cmd = ['ffmpeg', '-n', '-v', 'error', '-xerror', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
           '-s:v', '1280x720', '-r', str(FPS), '-i', 'pipe:0', '-i', str(audio), '-map', '0:v:0',
           '-map', '1:a:0', '-c:v', 'libx264', '-preset', 'fast', '-crf', '23', '-pix_fmt', 'yuv420p',
           '-c:a', 'copy', '-movflags', '+faststart', str(partial)]
    with wave.open(str(pcm), 'rb') as level, subprocess.Popen(cmd, stdin=subprocess.PIPE) as proc:
        try:
            for i in range(first, last):
                values = np.frombuffer(level.readframes(1000), dtype='<i2').astype(np.float32)/32768
                rms = float(np.sqrt(np.mean(values*values))) if len(values) else 0.0
                frame = renderer.frame(i, rms)
                proc.stdin.write(frame.tobytes())
                if (i-first) % (60*FPS) == 0:
                    print(f'Rendering {i-first}/{last-first} frames', flush=True)
            proc.stdin.close()
            if proc.wait() != 0:
                raise subprocess.CalledProcessError(proc.returncode, cmd)
        except BaseException:
            if proc.poll() is None:
                proc.kill()
            raise
    result = verify(partial, audio, last-first, length)
    output = directory / ('preview.mp4' if args.preview else 'episode.mp4')
    partial.rename(output)
    return dict(result, mode='preview' if args.preview else 'full', preview_offset=start)


def build(args):
    if args.preview_start < 0 or (args.preview_start and not args.preview):
        raise ValueError('--preview-start requires --preview and a nonnegative time')
    for file in (args.script, args.narration, args.portrait_a, args.portrait_b):
        if not file.is_file():
            raise ValueError(f'Input file not found: {file}')
    turns, notes = script(args.script, args.section)
    check_script_length(turns)
    duration = duration_wav(args.narration)
    if args.preview:
        _render_window(args, duration)
    cfg = json.loads(args.config.read_text(encoding='utf-8')) if args.config else {}
    if not isinstance(cfg, dict) or not isinstance(cfg.get('title', 'Podcast'), str):
        raise ValueError('Config must be a JSON object with an optional text title')
    if not args.plan_only:
        from .render import _load_portrait, load_font

        font = args.font or Path(os.environ.get('PVK_FONT', str(MAC_FONT)))
        load_font(font)
        for portrait in (args.portrait_a, args.portrait_b):
            _load_portrait(portrait)
    out = args.output.resolve()
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    raw = transcribe(args)
    transcript = json.loads(raw.decode('utf-8'))
    if args.whisper_model:
        # Keep the generated cache verbatim so timing errors can be corrected and retried.
        (out / 'words.json').write_bytes(raw)
    words = read_words(transcript, float(duration))
    if args.words_json:
        (out / 'words.json').write_bytes(raw)
    aligned, weak, coverage, token_matches = align_with_provenance(turns, words)
    cues = captions(aligned, words, token_matches)
    scenes = concept_scenes(cfg, aligned)
    json_write(out / 'plan.json', dict(duration=float(duration), script_character_coverage=coverage,
               low_coverage_turns=weak, turns=aligned, unlabeled_paragraphs=notes,
               captions=cues, scenes=scenes))
    (out / 'captions.srt').write_text(srt(cues), encoding='utf-8')
    print(f'Plan: {len(aligned)} turns, alignment coverage {coverage:.0%}, '
          f'{len(weak)} low-coverage turns, {len(notes)} unlabeled paragraphs. Review plan.json.', flush=True)
    if not args.plan_only:
        unmatched_words = [dict(start=start, end=end)
                           for (start, end, _), count in zip(words, token_matches) if count == 0]
        result = make_video(args, out, cfg, aligned, cues, scenes, duration, font, unmatched_words)
        json_write(out / 'verification.json', result)
        print(f"Verified {result['mode']}: {result['frames']} frames; see verification.json", flush=True)


def positive(value):
    n = float(value)
    if not math.isfinite(n) or n <= 0 or n > 120:
        raise argparse.ArgumentTypeError('Use an excerpt length greater than 0 and up to 120 seconds')
    return n


def finite_seconds(value):
    try:
        seconds = Decimal(value)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError('Use a finite preview offset') from exc
    if not seconds.is_finite():
        raise argparse.ArgumentTypeError('Use a finite preview offset')
    if not seconds:
        return Fraction(0)
    if seconds.adjusted() < -12:
        # Sub-picosecond offsets always map to frame zero on valid WAVs.
        # Keep the sign without expanding arbitrary negative exponents.
        return Fraction(-1 if seconds.is_signed() else 1, 10**12)
    if seconds.adjusted() > 20:
        # Far beyond any WAV duration; avoid expanding arbitrary exponents.
        raise argparse.ArgumentTypeError('Preview offset is out of range')
    return Fraction(seconds)


def main(argv=None):
    arg = argparse.ArgumentParser(prog='podcast-video-kit', description=__doc__)
    arg.add_argument('--script', type=Path, required=True, help='DOCX with A:/B: turns')
    arg.add_argument('--section', default='7. 팟캐스트 대본', help='Exact DOCX section heading')
    arg.add_argument('--narration', type=Path, required=True, help='Complete supplied recording (WAV)')
    arg.add_argument('--portrait-a', type=Path, required=True, help='Portrait driven by voice A')
    arg.add_argument('--portrait-b', type=Path, required=True, help='Portrait driven by voice B')
    arg.add_argument('--output', type=Path, required=True, help='A new private run folder (e.g. runs/preview)')
    source = arg.add_mutually_exclusive_group(required=True)
    source.add_argument('--whisper-model', type=Path, help='Existing trusted local OpenAI Whisper checkpoint (.pt)')
    source.add_argument('--words-json', type=Path, help='Local Whisper JSON for the same WAV; reuse without inference')
    arg.add_argument('--language', help='Optional Whisper language code (otherwise autodetect)')
    arg.add_argument('--font', type=Path, help='Local font; defaults to PVK_FONT or macOS Apple SD Gothic Neo')
    arg.add_argument('--config', type=Path, help='Optional local title and concept scene JSON')
    mode = arg.add_mutually_exclusive_group()
    mode.add_argument('--preview', type=positive, metavar='SECONDS', help='Render only a sample; default is full')
    mode.add_argument('--plan-only', action='store_true', help='Only generate alignment, scene plan and SRT')
    arg.add_argument('--preview-start', type=finite_seconds, default=Fraction(0), metavar='SECONDS')
    args = arg.parse_args(argv)
    try:
        build(args)
    except (OSError, ValueError, TypeError, KeyError, IndexError, StopIteration, BadZipFile,
            ParseError, wave.Error, subprocess.SubprocessError) as exc:
        print(f'Cannot build episode: {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
