"""Parse a private script and align it to local ASR; never interpret it as commands."""
from __future__ import annotations

import math
import re
import unicodedata
from bisect import bisect_right
from difflib import SequenceMatcher
from xml.etree import ElementTree as ET
from zipfile import ZipFile

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
SPEAKER = re.compile(r'^([AB])\s*[:：]\s*(.*)$')
NUMBERED = re.compile(r'^(\d+)\s*[.)]\s*\S')


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def script(path, heading):
    with ZipFile(path) as z:
        document = z.getinfo('word/document.xml')
        if document.file_size > 8_000_000:
            raise ValueError('DOCX document.xml exceeds 8 MB')
        data = z.read(document).decode('utf-8-sig')
    if '<!DOCTYPE' in data.upper() or '<!ENTITY' in data.upper():
        raise ValueError('DOCX XML declarations with DTD/entities are not supported')
    body = ET.fromstring(data).find(W + 'body')
    if body is None:
        raise ValueError('DOCX has no document body')
    rows = []
    for node in body.iter(W + 'p'):
        style = node.find(f'{W}pPr/{W}pStyle')
        text = ''.join((p.text or '') if p.tag == W + 't' else ' '
                       for p in node.iter() if p.tag in {W + 't', W + 'br', W + 'tab'})
        rows.append((text.strip(), '' if style is None else style.get(W + 'val', '')))
    matching = [i for i, (t, _) in enumerate(rows) if normalized(t) == normalized(heading)]
    if len(matching) != 1:
        raise ValueError('Expected one script heading; supply the exact heading with --section')
    first = matching[0]
    start_number = NUMBERED.match(rows[first][0])
    heading_level = re.fullmatch(r'Heading(\d+)', rows[first][1], re.I)
    turns, notes = [], []
    for i, (text, style) in enumerate(rows[first + 1:], first + 2):
        if not text:
            continue
        match = SPEAKER.match(text)
        if match:
            speaker, line = match.groups()
            if not normalized(line):
                raise ValueError(f'Paragraph {i}: missing dialogue after speaker label')
            turns.append({'speaker': speaker, 'text': line, 'paragraph': i})
            continue
        n = NUMBERED.match(text)
        level = re.fullmatch(r'Heading(\d+)', style, re.I)
        if ((n and start_number and int(n[1]) == int(start_number[1]) + 1)
                or (level and heading_level and int(level[1]) <= int(heading_level[1]))):
            break
        notes.append({'paragraph': i, 'after_turn': len(turns), 'text': text})
    if not turns:
        raise ValueError('Selected section contains no A:/B: dialogue')
    return turns, notes


def read_words(transcript, duration):
    words = []
    previous = 0.0
    for seg in transcript['segments']:
        for w in seg.get('words', []):
            text = w['word']
            start, end = float(w['start']), float(w['end'])
            if (not math.isfinite(start) or not math.isfinite(end) or start < 0
                    or end > duration + .25 or end < start):
                raise ValueError('ASR has invalid or out-of-range word timestamps')
            if start + .1 < previous:
                raise ValueError('ASR word timestamps go backwards')
            start, end = min(duration, max(start, previous)), min(duration, max(start, end))
            if end > start and text.strip():
                words.append((start, end, text))
                previous = end
    if not words:
        raise ValueError('Expected Whisper JSON with nonempty word timestamps')
    return words


def align(turns, words):
    # Exact matching of normalized character runs, monotonic across the episode.
    # Character positions interpolate within ASR words; they are not phoneme times.
    parts = [normalized(t['text']) for t in turns]
    script_text = ''.join(parts)
    asr_parts = [normalized(w[2]) for w in words]
    audio_text = ''.join(asr_parts)
    if max(len(script_text), len(audio_text)) > 30_000:
        raise ValueError('This aligner supports up to 30,000 normalized characters; split into episodes')
    times = [(a + (b-a)*i/len(part), a + (b-a)*(i+1)/len(part))
             for (a, b, _), part in zip(words, asr_parts) for i in range(len(part))]
    matches = {}
    for a, b, size in SequenceMatcher(None, script_text, audio_text, autojunk=False).get_matching_blocks():
        matches.update((a+i, b+i) for i in range(size))
    cursor = 0
    aligned, issues = [], []
    for index, (turn, part) in enumerate(zip(turns, parts), 1):
        hits = [matches[i] for i in range(cursor, cursor+len(part)) if i in matches]
        cursor += len(part)
        ratio = len(hits) / len(part)
        if ratio < .60:
            issues.append(index)
        aligned.append(dict(turn, coverage=ratio, start=times[hits[0]][0] if hits else None,
                            end=times[hits[-1]][1] if hits else None))
    if not matches or len(matches)/len(script_text) < .50 or any(t['start'] is None for t in aligned):
        failing = ', '.join(str(i+1) for i,t in enumerate(aligned) if t['start'] is None)
        raise ValueError('Script and recording could not be reliably aligned. Check section and recording.'
                         + (f' No matches for turns: {failing}.' if failing else ''))
    return aligned, issues, len(matches)/len(script_text)


def captions(turns, words):
    """Group actual ASR words; unmatched speech is preserved without a speaker label."""
    starts = [t['start'] for t in turns]
    out = []
    for a, b, raw in words:
        mid = (a+b)/2
        j = bisect_right(starts, mid)-1
        speaker = turns[j]['speaker'] if j >= 0 and mid < turns[j]['end'] else ''
        text = raw.strip()
        line = (out[-1]['text'] + ' ' + text) if out else text
        if (out and speaker == out[-1]['speaker'] and a-out[-1]['end'] <= .6
                and b-out[-1]['start'] <= 5 and len(line) <= 54):
            out[-1].update(end=b, text=line)
        else:
            out.append({'start': a, 'end': b, 'speaker': speaker, 'text': text})
    return out


def concept_scenes(config, turns):
    result = []
    for item in config.get('scenes', []):
        i, j = item['first_turn'], item.get('last_turn', item['first_turn'])
        if type(i) is not int or type(j) is not int or not 1 <= i <= j <= len(turns):
            raise ValueError('Concept scene turn indices must be valid 1-based ranges')
        title, body = item['title'], item['body']
        if not isinstance(title, str) or not title.strip() or not isinstance(body, str) or not body.strip():
            raise ValueError('Concept scenes require a nonempty title and body')
        start, end = turns[i-1]['start'], turns[j-1]['end']
        if end-start < 2:
            raise ValueError('Choose at least 2 seconds of dialogue for each concept scene')
        result.append(dict(start=start, end=end, title=title, body=body))
    result.sort(key=lambda item: item['start'])
    if any(a['end'] > b['start'] for a,b in zip(result,result[1:])):
        raise ValueError('Concept scene ranges must not overlap')
    return result


def srt(cues):
    def stamp(seconds):
        total = round(seconds*1000)
        m, ms = divmod(total, 1000)
        h, m = divmod(m, 3600)
        m, sec = divmod(m, 60)
        return f'{h:02d}:{m:02d}:{sec:02d},{ms:03d}'
    return ''.join(f"{i}\n{stamp(c['start'])} --> {stamp(c['end'])}\n"
                   + (c['speaker']+': ' if c['speaker'] else '') + c['text'] + '\n\n'
                   for i,c in enumerate(cues,1))
