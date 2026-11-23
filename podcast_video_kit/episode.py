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
NUMBERED = re.compile(r'^(\d+)\s*[.)]\s+\S')
OUTLINE_LEVELS = {str(level): level for level in range(9)}
NESTED_LIST_LEVELS = {str(level) for level in range(1, 9)}
MAX_ALIGNMENT_CHARS = 30_000


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def _check_alignment_length(length):
    if length > MAX_ALIGNMENT_CHARS:
        raise ValueError('This aligner supports up to 30,000 normalized characters; split into episodes')


def check_script_length(turns):
    _check_alignment_length(sum(len(normalized(turn['text'])) for turn in turns))


def _heading_key(text):
    # Runs, tabs and soft line breaks may differ between Word exporters.
    return ' '.join(unicodedata.normalize('NFC', text).split())


def _word_xml(archive, name):
    member = archive.getinfo(f'word/{name}')
    if member.file_size > 8_000_000:
        raise ValueError(f'DOCX {name} exceeds 8 MB')
    data = archive.read(member).decode('utf-8-sig')
    if '<!DOCTYPE' in data.upper() or '<!ENTITY' in data.upper():
        raise ValueError('DOCX XML declarations with DTD/entities are not supported')
    return ET.fromstring(data)


def _property(node, name):
    child = node.find('/'.join(W + part for part in name.split('/')))
    return child.get(W + 'val') if child is not None else None


def _style_chain(current, styles):
    seen = set()
    while current in styles and current not in seen:
        seen.add(current)
        yield styles[current]
        current = _property(styles[current], 'basedOn')


def _outline(node, style_id, inherited, default_outline):
    level = next((value for p in (node, *inherited)
                  if (value := _property(p, 'pPr/outlineLvl')) is not None), None)
    if level is not None:
        # 9 denotes body text and explicitly overrides an inherited heading.
        return OUTLINE_LEVELS.get(level)
    builtin = re.fullmatch(r'Heading([1-9])', style_id or '', re.I)
    if builtin:
        return int(builtin[1]) - 1
    return OUTLINE_LEVELS.get(default_outline)


def _top_level_numbering(root):
    abstracts = {abstract_id: node for node in root.findall(W + 'abstractNum')
                 if (abstract_id := node.get(W + 'abstractNumId'))}
    decimals, bullets = {}, set()
    for num in root.findall(W + 'num'):
        num_id = num.get(W + 'numId')
        abstract = abstracts.get(_property(num, 'abstractNumId'))
        if not num_id or abstract is None or abstract.find(W + 'numStyleLink') is not None:
            continue
        level = abstract.find(f'{W}lvl[@{W}ilvl="0"]')
        override = num.find(f'{W}lvlOverride[@{W}ilvl="0"]')
        start_override = None
        if override is not None:
            start_override = _property(override, 'startOverride')
            replacement = override.find(W + 'lvl')
            if replacement is not None:
                level = replacement
        if level is None:
            continue
        num_fmt = _property(level, 'numFmt')
        if num_fmt == 'bullet':
            bullets.add(num_id)
        if num_fmt != 'decimal':
            continue
        label = _property(level, 'lvlText')
        start = start_override if start_override is not None else _property(level, 'start')
        if label in ('%1.', '%1)') and start is not None and re.fullmatch(r'[0-9]{1,9}', start):
            decimals[num_id] = int(start), label[-1]
    return decimals, bullets


def _automatic_number(node, inherited):
    direct = node.find(f'{W}pPr/{W}numPr')
    num_id = _property(node, 'pPr/numPr/numId')
    if num_id == '0':
        return None, None
    if num_id is not None:
        level = direct.find(W + 'ilvl')
        return num_id, level.get(W + 'val') if level is not None else '0'
    for style in inherited:
        style_num = _property(style, 'pPr/numPr/numId')
        if style_num is not None:
            return (None, None) if style_num == '0' else (style_num, None)
    return ('', None) if direct is not None else (None, None)


def _unsupported_numbering(paragraph):
    return ValueError(f'Paragraph {paragraph}: automatic numbering cannot determine the script heading '
                      'or section boundary; use typed section numbers or Word outline headings')


def script(path, heading):
    with ZipFile(path) as z:
        body = _word_xml(z, 'document.xml').find(W + 'body')
        try:
            styles_xml = _word_xml(z, 'styles.xml')
        except KeyError:  # Some exporters omit styles.xml entirely.
            styles_xml = ET.Element(W + 'styles')
        try:
            decimals, bullets = _top_level_numbering(_word_xml(z, 'numbering.xml'))
        except KeyError:
            decimals, bullets = {}, set()
    if body is None:
        raise ValueError('DOCX has no document body')
    styles = {s.get(W + 'styleId'): s for s in styles_xml.findall(W + 'style')
              if s.get(W + 'type') == 'paragraph' and s.get(W + 'styleId')}
    default_style = next((sid for sid, style in styles.items()
                          if style.get(W + 'default') in ('1', 'true', 'on')), None)
    default_outline = _property(styles_xml, 'docDefaults/pPrDefault/pPr/outlineLvl')
    default_paragraph = styles_xml.find(f'{W}docDefaults/{W}pPrDefault')
    counts = {}
    rows = []
    for node in body.iter(W + 'p'):
        text = ''.join((p.text or '') if p.tag == W + 't' else ' '
                       for p in node.iter() if p.tag in {W + 't', W + 'br', W + 'tab'}).strip()
        style_id = _property(node, 'pPr/pStyle') or default_style
        inherited = tuple(_style_chain(style_id, styles))
        outline = _outline(node, style_id, inherited, default_outline)
        num_id, list_level = _automatic_number(
            node, inherited if default_paragraph is None else (*inherited, default_paragraph))
        label = None
        if num_id in decimals and list_level not in OUTLINE_LEVELS:
            # An unresolved level may have advanced this list's top-level counter.
            counts[num_id] = None
        elif list_level == '0' and num_id in decimals:
            start, suffix = decimals[num_id]
            number = counts.get(num_id, start)
            if number is not None:
                counts[num_id] = number + 1
                label = f'{number}{suffix} {text}'
        rows.append((text, outline, num_id, list_level, label))
    key = _heading_key(heading)
    matching = [i for i, (t, _, _, _, label) in enumerate(rows)
                if key and key in (_heading_key(t), _heading_key(label or ''))]
    if len(matching) != 1:
        if not matching:
            for i, (text, _, num_id, _, label) in enumerate(rows, 1):
                if text and num_id is not None and label is None and not SPEAKER.match(text):
                    if key.endswith(' ' + _heading_key(text)):
                        raise _unsupported_numbering(i)
        raise ValueError('Expected one script heading; supply the exact heading with --section')
    first = matching[0]
    heading_text, heading_level, heading_list, _, heading_label = rows[first]
    if heading_list is not None and heading_label is None and heading_level is None:
        raise _unsupported_numbering(first + 1)
    start_number = NUMBERED.match(heading_text) or NUMBERED.match(heading_label or '')
    turns, notes = [], []
    for i, (text, level, num_id, list_level, label) in enumerate(rows[first + 1:], first + 2):
        if not text:
            continue
        if level is not None and heading_level is not None and level <= heading_level:
            break
        is_bullet = list_level == '0' and num_id in bullets
        n = None if is_bullet else NUMBERED.match(text)
        if n and start_number and int(n[1]) == int(start_number[1]) + 1:
            break
        match = SPEAKER.match(text)
        if (not match and not is_bullet and num_id is not None and list_level not in NESTED_LIST_LEVELS
                and (level is None or heading_level is None)):
            if label is not None and heading_label is not None and num_id == heading_list:
                break
            raise _unsupported_numbering(i)
        if match:
            speaker, line = match.groups()
            if not normalized(line):
                raise ValueError(f'Paragraph {i}: missing dialogue after speaker label')
            turns.append({'speaker': speaker, 'text': line, 'paragraph': i})
            continue
        notes.append({'paragraph': i, 'after_turn': len(turns), 'text': text})
    if not turns:
        raise ValueError('Selected section contains no A:/B: dialogue')
    return turns, notes


class IncompleteSegmentWords(ValueError):
    """The segment text and its timed words disagree."""


def read_words(transcript, duration):
    if not isinstance(transcript, dict) or not isinstance(transcript.get('segments'), list):
        raise ValueError('Expected Whisper JSON with a segments array')
    words = []
    previous = 0.0
    for i, seg in enumerate(transcript['segments']):
        if not isinstance(seg, dict):
            raise ValueError(f'ASR segments[{i}] must be an object')
        entries = seg.get('words', [])
        if not isinstance(entries, list):
            raise ValueError(f'ASR segments[{i}].words must be an array')
        segment_text = seg.get('text', '')
        if not isinstance(segment_text, str):
            raise ValueError(f'ASR segments[{i}].text must be a string')
        before = len(words)
        for j, w in enumerate(entries):
            location = f'segments[{i}].words[{j}]'
            if not isinstance(w, dict) or not isinstance(w.get('word'), str):
                raise ValueError(f'ASR {location} must be an object with string word text')
            text = w['word']
            try:
                start, end = w['start'], w['end']
                if type(start) not in (int, float, str) or type(end) not in (int, float, str):
                    raise ValueError('expected numeric seconds')
                start, end = float(start), float(end)
            except (KeyError, ValueError, OverflowError) as exc:
                raise ValueError(f'ASR {location} requires numeric start/end timestamps') from exc
            if (not math.isfinite(start) or not math.isfinite(end) or start < 0
                    or end > duration + .25 or end < start):
                raise ValueError(f'ASR {location} has invalid or out-of-range word timestamps')
            if start + .1 < previous:
                raise ValueError(f'ASR {location} timestamps go backwards')
            timed = start < end
            start, end = min(duration, max(start, previous)), min(duration, end)
            if text.strip():
                if not timed or end <= start:
                    raise ValueError(f'ASR {location} has no positive duration; correct its timestamps before aligning')
                words.append((start, end, text))
                previous = end
        if len(words) == before and segment_text.strip():
            raise ValueError(f'ASR segments[{i}] has text but no usable word timestamps')
        if 'text' in seg and normalized(segment_text) != normalized(''.join(w[2] for w in words[before:])):
            raise IncompleteSegmentWords(
                f'ASR segments[{i}].text does not match its timed words; correct the segment before aligning')
    if not words:
        raise ValueError('Expected Whisper JSON with nonempty word timestamps')
    return words


def align(turns, words):
    aligned, issues, coverage, _ = align_with_provenance(turns, words)
    return aligned, issues, coverage


def align_with_provenance(turns, words):
    """Also return matched character counts in ASR token order, or None for non-speech tokens."""
    # Exact matching of normalized character runs, monotonic across the episode.
    # Character positions interpolate within ASR words; they are not phoneme times.
    parts = [normalized(t['text']) for t in turns]
    script_text = ''.join(parts)
    asr_parts = [normalized(w[2]) for w in words]
    audio_text = ''.join(asr_parts)
    _check_alignment_length(max(len(script_text), len(audio_text)))
    times = []
    for (a, b, _), part in zip(words, asr_parts):
        if part:
            boundaries = [a, *(a + (b-a)*i/len(part) for i in range(1, len(part))), b]
            times.extend(zip(boundaries, boundaries[1:]))
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
    audio_hits = set(matches.values())
    token_matches = []
    cursor = 0
    for part in asr_parts:
        stop = cursor + len(part)
        token_matches.append(sum(i in audio_hits for i in range(cursor, stop)) if part else None)
        cursor = stop
    return aligned, issues, len(matches)/len(script_text), token_matches


def _caption_speaker(turns, starts, start, end):
    j = bisect_right(starts, start) - 1
    if j < 0 or start >= turns[j]['end']:
        return ''
    speaker = turns[j]['speaker']
    # Adjacent turns by the same speaker can share a word. Across speakers
    # or an unaligned gap, don't assign the entire word to one speaker.
    while end > turns[j]['end']:
        j += 1
        if (j == len(turns) or turns[j]['speaker'] != speaker
                or turns[j]['start'] > turns[j - 1]['end']):
            return ''
    return speaker


def captions(turns, words, token_matches=None):
    """Group actual ASR words; unmatched speech is preserved without a speaker label."""
    starts = [t['start'] for t in turns]
    out = []
    for i, (a, b, raw) in enumerate(words):
        speaker = ''
        if token_matches is None or token_matches[i] != 0:
            speaker = _caption_speaker(turns, starts, a, b)
        line = (out[-1]['text'] + raw) if out else raw
        if (out and speaker == out[-1]['speaker'] and a-out[-1]['end'] <= .6
                and b-out[-1]['start'] <= 5 and len(line.strip()) <= 54):
            out[-1].update(end=b, text=line)
        else:
            out.append({'start': a, 'end': b, 'speaker': speaker, 'text': raw})
    for cue in out:
        cue['text'] = cue['text'].strip()
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
