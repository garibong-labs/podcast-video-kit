"""Generate a local 2D episode from a script, supplied recording and two portraits."""
from __future__ import annotations

import argparse
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

from .episode import align, captions, concept_scenes, read_words, script, srt

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
        return json.loads(args.words_json.read_text(encoding='utf-8'))
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
        return json.loads((Path(tmp) / (Path(wav).stem + '.json')).read_text(encoding='utf-8'))


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


def make_video(args, directory, config, turns, cues, scenes, duration):
    import numpy as np
    from .render import Renderer

    # Index previews on the same frame grid, so caption and scene boundaries do not drift.
    total = math.ceil(duration * FPS)
    first = round(Fraction(str(args.preview_start)) * FPS) if args.preview else 0
    last = min(total, first + math.ceil(Fraction(str(args.preview)) * FPS)) if args.preview else total
    if first >= last:
        raise ValueError('Preview starts after the recording ends')
    offset = Fraction(first, FPS)
    start = float(offset)
    length = float(min(duration-offset, Fraction(last-first, FPS)))
    font = args.font or Path(os.environ.get('PVK_FONT', str(MAC_FONT)))
    if not font.is_file():
        raise ValueError('Specify a local Korean-capable font with --font or PVK_FONT')
    renderer = Renderer(args.portrait_a, args.portrait_b, font,
                        config.get('title', 'Podcast'), turns, cues, scenes)
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
    duration = duration_wav(args.narration)
    if args.preview and Fraction(round(Fraction(str(args.preview_start))*FPS), FPS) >= duration:
        raise ValueError('Preview starts after the recording ends')
    cfg = json.loads(args.config.read_text(encoding='utf-8')) if args.config else {}
    if not isinstance(cfg, dict) or not isinstance(cfg.get('title', 'Podcast'), str):
        raise ValueError('Config must be a JSON object with an optional text title')
    out = args.output.resolve()
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    transcript = transcribe(args)
    json_write(out / 'words.json', transcript)
    words = read_words(transcript, float(duration))
    aligned, weak, coverage = align(turns, words)
    cues = captions(aligned, words)
    scenes = concept_scenes(cfg, aligned)
    json_write(out / 'plan.json', dict(duration=float(duration), script_character_coverage=coverage,
               low_coverage_turns=weak, turns=aligned, unlabeled_paragraphs=notes,
               captions=cues, scenes=scenes))
    (out / 'captions.srt').write_text(srt(cues), encoding='utf-8')
    print(f'Plan: {len(aligned)} turns, alignment coverage {coverage:.0%}, '
          f'{len(weak)} low-coverage turns, {len(notes)} unlabeled paragraphs. Review plan.json.', flush=True)
    if not args.plan_only:
        result = make_video(args, out, cfg, aligned, cues, scenes, duration)
        json_write(out / 'verification.json', result)
        print(f"Verified {result['mode']}: {result['frames']} frames; see verification.json", flush=True)


def positive(value):
    n = float(value)
    if not math.isfinite(n) or n <= 0 or n > 120:
        raise argparse.ArgumentTypeError('Use an excerpt length greater than 0 and up to 120 seconds')
    return n


def finite_seconds(value):
    n = float(value)
    if not math.isfinite(n):
        raise argparse.ArgumentTypeError('Use a finite preview offset')
    return n


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
    arg.add_argument('--preview-start', type=finite_seconds, default=0.0, metavar='SECONDS')
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
