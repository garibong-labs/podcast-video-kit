import contextlib
from fractions import Fraction
import io
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave
from xml.sax.saxutils import escape
from zipfile import ZipFile

from podcast_video_kit.__main__ import _render_window, _validate_cue_frames, duration_wav, main
from podcast_video_kit.episode import (align, align_with_provenance, captions, concept_scenes,
                                       read_words, repair_zero_duration, script, srt)


NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def docx(path, rows, styles='', numbering=''):
    paragraphs = [(row, '') if isinstance(row, str) else row for row in rows]
    xml = ''.join(f'<w:p>{props}<w:r><w:t>{escape(row)}</w:t></w:r></w:p>' for row, props in paragraphs)
    with ZipFile(path, 'w') as z:
        z.writestr('word/document.xml', f'<w:document xmlns:w="{NS}"><w:body>{xml}</w:body></w:document>')
        if styles:
            z.writestr('word/styles.xml', f'<w:styles xmlns:w="{NS}">{styles}</w:styles>')
        if numbering:
            z.writestr('word/numbering.xml', f'<w:numbering xmlns:w="{NS}">{numbering}</w:numbering>')


def number_props(num_id=3, level=0):
    return (f'<w:pPr><w:numPr><w:ilvl w:val="{level}"/>'
            f'<w:numId w:val="{num_id}"/></w:numPr></w:pPr>')


def cli_fixture(root, rows):
    docx(root/'script.docx', rows)
    for name in ('a.png', 'b.png', 'narration.wav'):
        (root/name).touch()
    return ['--script', str(root/'script.docx'), '--section', 'Script',
            '--narration', str(root/'narration.wav'), '--portrait-a', str(root/'a.png'),
            '--portrait-b', str(root/'b.png')]


class PlanningTests(unittest.TestCase):
    def test_automatic_decimal_sections_and_numbered_dialogue(self):
        numbering = '''<w:abstractNum w:abstractNumId="2"><w:lvl w:ilvl="0">
                         <w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/>
                       </w:lvl></w:abstractNum>
                       <w:num w:numId="3"><w:abstractNumId w:val="2"/><w:lvlOverride w:ilvl="0">
                         <w:startOverride w:val="7"/>
                       </w:lvlOverride></w:num>'''
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'example.docx'
            docx(p, [('Script', number_props()), ('A: First', number_props(4)),
                     ('Nested note', number_props(level=1)), 'B: Second',
                     ('Appendix', number_props()), 'A: Outside'], numbering=numbering)
            for heading in ('7. Script', 'Script'):
                with self.subTest(heading=heading):
                    turns, notes = script(p, heading)
                    self.assertEqual([t['text'] for t in turns], ['First', 'Second'])
                    self.assertEqual(notes, [dict(paragraph=3, after_turn=1, text='Nested note')])
            with self.assertRaisesRegex(ValueError, 'exact heading'):
                script(p, '8. Script')

    def test_unsupported_automatic_sections_fail_at_selection_or_boundary(self):
        roman = '''<w:abstractNum w:abstractNumId="2"><w:lvl w:ilvl="0">
                     <w:start w:val="7"/><w:numFmt w:val="upperRoman"/><w:lvlText w:val="%1."/>
                   </w:lvl></w:abstractNum>
                   <w:num w:numId="3"><w:abstractNumId w:val="2"/></w:num>'''
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'example.docx'
            docx(p, [('Script', number_props()), 'A: Inside', ('Appendix', number_props()), 'B: Outside'])
            for heading in ('7. Script', 'Script'):
                with self.subTest(heading=heading), self.assertRaisesRegex(ValueError, 'Paragraph 1: automatic numbering'):
                    script(p, heading)
            docx(p, ['Script', ('A: Inside', number_props(4)), ('Appendix', number_props()), 'B: Outside'],
                 numbering=roman)
            with self.assertRaisesRegex(ValueError, 'Paragraph 3: automatic numbering'):
                script(p, 'Script')

    def test_decimal_note_does_not_truncate_dialogue(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'example.docx'
            docx(p, ['7. Script', 'A: First', '8.5% growth', 'B: Second', '8. Appendix', 'A: Outside'])
            turns, notes = script(p, '7. Script')
            self.assertEqual([t['text'] for t in turns], ['First', 'Second'])
            self.assertEqual([n['text'] for n in notes], ['8.5% growth'])

    def test_top_level_bullets_stay_in_the_script_section(self):
        bullet = '<w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/></w:lvl>'
        decimal = ('<w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/>'
                   '<w:lvlText w:val="%1."/></w:lvl>')
        override = '<w:lvlOverride w:ilvl="0">{}</w:lvlOverride>'
        numbering = f'''<w:abstractNum w:abstractNumId="1">{bullet}</w:abstractNum>
                        <w:abstractNum w:abstractNumId="2">{decimal}</w:abstractNum>
                        <w:num w:numId="3"><w:abstractNumId w:val="1"/></w:num>
                        <w:num w:numId="4"><w:abstractNumId w:val="2"/>{override.format(bullet)}</w:num>
                        <w:num w:numId="5"><w:abstractNumId w:val="1"/>{override.format(decimal)}</w:num>'''
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'example.docx'
            rows = ['7. Script', 'A: First', ('8. Note', number_props()),
                    ('Another note', number_props(4)), ('B: Second', number_props(4)),
                    '8. Appendix', 'A: Outside']
            docx(p, rows, numbering=numbering)
            turns, notes = script(p, '7. Script')
            self.assertEqual(turns, [dict(speaker='A', text='First', paragraph=2),
                                     dict(speaker='B', text='Second', paragraph=5)])
            self.assertEqual(notes, [dict(paragraph=3, after_turn=1, text='8. Note'),
                                     dict(paragraph=4, after_turn=1, text='Another note')])

            for props in (number_props(5), number_props(level='')):
                with self.subTest(props=props):
                    rows[2] = ('Ambiguous list item', props)
                    docx(p, rows, numbering=numbering)
                    with self.assertRaisesRegex(ValueError, 'Paragraph 3: automatic numbering'):
                        script(p, '7. Script')

            outline = '<w:outlineLvl w:val="0"/>'
            rows[0] = ('7. Script', f'<w:pPr>{outline}</w:pPr>')
            rows[2] = ('Outline heading', number_props().replace('</w:pPr>', f'{outline}</w:pPr>'))
            docx(p, rows, numbering=numbering)
            self.assertEqual(script(p, '7. Script'), ([turns[0]], []))

    def test_style_inherited_bullets_require_a_unique_effective_level_link(self):
        styles = '''<w:style w:type="paragraph" w:styleId="BulletParent">
                      <w:pPr><w:numPr><w:ilvl w:val="2"/><w:numId w:val="3"/></w:numPr></w:pPr>
                    </w:style>
                    <w:style w:type="paragraph" w:styleId="BulletChild">
                      <w:basedOn w:val="BulletParent"/>
                    </w:style>'''
        bullet = '<w:lvl w:ilvl="{}"><w:numFmt w:val="bullet"/>{}</w:lvl>'
        parent = '<w:pStyle w:val="BulletParent"/>'
        numbering = '''<w:abstractNum w:abstractNumId="2">{}</w:abstractNum>
                       <w:num w:numId="3"><w:abstractNumId w:val="2"/>{}</w:num>'''
        props = '<w:pPr><w:pStyle w:val="BulletChild"/></w:pPr>'
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'example.docx'
            rows = ['7. Script', 'A: First', ('8. Bullet note', props), ('B: Second', props),
                    '8. Appendix', 'A: Outside']
            override = f'<w:lvlOverride w:ilvl="0">{bullet.format(0, parent)}</w:lvlOverride>'
            for levels, effective_override in ((bullet.format(0, parent), ''),
                                               (bullet.format(0, ''), override)):
                docx(path, rows, styles, numbering.format(levels, effective_override))
                turns, notes = script(path, '7. Script')
                self.assertEqual([t['text'] for t in turns], ['First', 'Second'])
                self.assertEqual([n['text'] for n in notes], ['8. Bullet note'])

            rows[2] = ('Bullet note', props)
            without_link = f'<w:lvlOverride w:ilvl="0">{bullet.format(0, "")}</w:lvlOverride>'
            for levels, effective_override in (
                (bullet.format(0, ''), ''),
                (bullet.format(0, parent) + bullet.format(1, parent), ''),
                (bullet.format(0, parent), without_link),
            ):
                with self.subTest(levels=levels, override=effective_override):
                    docx(path, rows, styles, numbering.format(levels, effective_override))
                    with self.assertRaisesRegex(ValueError, 'Paragraph 3: automatic numbering'):
                        script(path, '7. Script')

    def test_exact_heading_preserves_punctuation_and_case(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'example.docx'
            level = '<w:pPr><w:outlineLvl w:val="0"/></w:pPr>'
            docx(p, [('C#', level), 'B: Wrong', ('C++', level), 'A: Right', ('Appendix', level), 'B: Outside'])
            turns, _ = script(p, 'C++')
            self.assertEqual([t['text'] for t in turns], ['Right'])
            for heading in ('C', 'c++'):
                with self.subTest(heading=heading), self.assertRaisesRegex(ValueError, 'exact heading'):
                    script(p, heading)

    def test_section_boundaries_notes_and_repeat_speaker(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'example.docx'
            docx(p, ['A: Outside', '7. 팟캐스트 대본', 'A: 시작', '메모', 'A： 계속', 'B: 끝', '8. Notes', 'A: Outside'])
            turns, notes = script(p, '7. 팟캐스트 대본')
            self.assertEqual([t['speaker'] for t in turns], ['A', 'A', 'B'])
            self.assertEqual(notes, [{'paragraph': 4, 'after_turn': 1, 'text': '메모'}])
            with self.assertRaisesRegex(ValueError, 'one script heading'):
                script(p, 'missing')

    def test_section_ends_at_direct_outline_level(self):
        level0 = '<w:pPr><w:outlineLvl w:val="0"/></w:pPr>'
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'example.docx'
            docx(p, [('Script', level0), 'A: Inside', ('Appendix', level0), 'B: Outside'])
            self.assertEqual(script(p, 'Script'), ([dict(speaker='A', text='Inside', paragraph=2)], []))

    def test_section_respects_style_inheritance_and_direct_overrides(self):
        styles = '''<w:style w:type="paragraph" w:styleId="Major">
                     <w:pPr><w:outlineLvl w:val="1"/></w:pPr></w:style>
                    <w:style w:type="paragraph" w:styleId="Custom">
                      <w:basedOn w:val="Major"/></w:style>'''
        def props(level=None):
            direct = '' if level is None else f'<w:outlineLvl w:val="{level}"/>'
            return f'<w:pPr><w:pStyle w:val="Custom"/>{direct}</w:pPr>'
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'example.docx'
            docx(p, [('Script', props()), ('Details', props(2)), ('A: Inside', props(9)),
                     ('B: Continuation', props(9)), ('B: Appendix', props()), 'A: Outside'], styles)
            turns, notes = script(p, 'Script')
            self.assertEqual([t['text'] for t in turns], ['Inside', 'Continuation'])
            self.assertEqual([n['text'] for n in notes], ['Details'])

    def test_monotonic_alignment_captions_and_unmatched_words(self):
        src = dict(segments=[dict(words=[dict(start=a,end=b,word=text) for a,b,text in
                   [(0.0, .3, 'Unscripted'), (.6, 1.4, ' FIRST'), (1.9, 2.3, ' second'), (2.9, 3.4, ' third')]])])
        words = read_words(src, 4)
        turns, issues, coverage = align([dict(speaker=x,text=t) for x,t in
                                         [('A','first'),('A','second'),('B','third')]], words)
        self.assertEqual([t['start'] for t in turns], [.6, 1.9, 2.9])
        self.assertEqual(coverage, 1)
        self.assertEqual(issues, [])
        cues = captions(turns, words)
        self.assertEqual([c['speaker'] for c in cues], ['', 'A', 'B'])
        self.assertIn('FIRST second', srt(cues))
        self.assertIn('Unscripted', srt(cues))

    def test_caption_separators_stay_verbatim_inside_cue(self):
        words = [(0, .2, ' 今日'), (.2, .4, 'は'), (.4, .6, '晴れ  '),
                 (.6, .8, 'です'), (.8, 1, '。 '), (1, 1.3, ' 다음 ')]
        turns = [dict(start=0, end=1, speaker='A'), dict(start=1, end=1.3, speaker='B')]
        cues = captions(turns, words)
        self.assertEqual([cue['text'] for cue in cues], ['今日は晴れ  です。', '다음'])
        self.assertIn('A: 今日は晴れ  です。\n', srt(cues))

    def test_caption_word_crossing_turns_does_not_claim_one_speaker(self):
        words = [(0, 1, 'anymore'), (1, 1.5, ' later')]
        for second_speaker, expected in [('B', ''), ('A', 'A')]:
            with self.subTest(second_speaker=second_speaker):
                turns, _, coverage, provenance = align_with_provenance(
                    [dict(speaker='A', text='any'), dict(speaker=second_speaker, text='more later')], words)
                self.assertEqual(coverage, 1)
                self.assertEqual(turns[0]['end'], turns[1]['start'])
                cues = captions(turns, words, provenance)
                self.assertEqual(cues[0]['speaker'], expected)
                if not expected:
                    self.assertEqual(cues[0], dict(start=0, end=1, text='anymore', speaker=''))
                    self.assertEqual(cues[1]['speaker'], 'B')
                    self.assertIn('\nanymore\n\n', srt(cues))
                else:
                    self.assertEqual(cues, [dict(start=0, end=1.5, text='anymore later', speaker='A')])

    def test_unmatched_token_between_same_speaker_anchors_is_unattributed(self):
        words = [(.1, .4, 'Red'), (.4, .7, ' why'), (.7, 1, ' blue')]
        turns, _, coverage, provenance = align_with_provenance([dict(speaker='A', text='red blue')], words)
        self.assertEqual(coverage, 1)
        self.assertEqual(provenance, [3, 0, 4])
        self.assertEqual(captions(turns, words, provenance),
                         [dict(start=a, end=b, text=text.strip(), speaker=speaker)
                          for (a, b, text), speaker in zip(words, ('A', '', 'A'))])

    def test_alignment_uses_exact_word_endpoints(self):
        words = [(.2, .44, 'abcdefghi'), (.44, .7, 'yes')]
        turns, _, coverage = align([dict(speaker='A', text='abcdefghi'),
                                    dict(speaker='B', text='yes')], words)
        self.assertEqual(coverage, 1)
        self.assertEqual(turns[0]['end'], .44)
        self.assertEqual(turns[0]['end'], turns[1]['start'])

    def test_alignment_fails_instead_of_inventing_missing_turn(self):
        with self.assertRaisesRegex(ValueError, 'No matches for turns: 2'):
            align([dict(speaker='A', text='hello'), dict(speaker='B', text='xyz')], [(0, 1, 'hello')])

    def test_bad_word_coordinates_and_empty_word_list(self):
        for times in [(float('nan'), 1), (-1, 1), (0.4, 0.2), (0, 9)]:
            with self.subTest(times=times), self.assertRaisesRegex(ValueError, 'timestamps'):
                read_words({'segments': [{'words': [{'start': times[0], 'end': times[1], 'word': 'test'}]}]}, 3)
        with self.assertRaisesRegex(ValueError, 'word timestamps'):
            read_words({'segments': [{}]}, 3)

    def test_malformed_asr_structures_get_indexed_errors(self):
        for src, diagnostic in [([], 'segments array'),
                                ({'segments': [None]}, r'segments\[0\] must be an object'),
                                ({'segments': [{'words': {}}]}, r'words must be an array'),
                                ({'segments': [{'words': [None]}]}, r'words\[0\].*string word'),
                                ({'segments': [{'words': [{'word': 1}]}]}, r'words\[0\].*string word'),
                                ({'segments': [{'words': [{'word': 'hi'}]}]}, r'words\[0\].*timestamps')]:
            with self.subTest(src=src), self.assertRaisesRegex(ValueError, diagnostic):
                read_words(src, 1)

    def test_nonblank_segment_without_usable_words_is_not_silently_dropped(self):
        first = {'words': [{'start': 0, 'end': .1, 'word': 'Hi'}]}
        last = {'words': [{'start': .3, 'end': .5, 'word': ' Bye'}]}
        for fields in ({}, {'words': []}, {'words': [{'start': .1, 'end': .2, 'word': '  '}]}):
            with self.subTest(fields=fields), self.assertRaisesRegex(ValueError, r'segments\[1\].*word timestamps'):
                read_words({'segments': [first, dict(fields, text='Missing speech'), last]}, 1)
        self.assertEqual(len(read_words({'segments': [first, {'text': '  '}, last]}, 1)), 2)

    def test_segment_mismatch_only_preserves_the_verbatim_generated_cache(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = cli_fixture(root, ['Script', 'A: Red'])
            cache = root/'input.json'
            model = root/'model.pt'
            model.touch()
            words = [{'start': .1, 'end': .4, 'word': 'Red'}]
            raw = (json.dumps({'segments': [{'text': 'Red blue', 'words': words}]}) + '\r\n').encode()

            def fake_whisper(command):
                raw_dir = Path(command[command.index('--output_dir') + 1])
                (raw_dir/'narration.json').write_bytes(raw)

            with patch('podcast_video_kit.__main__.duration_wav', return_value=1):
                cache.write_bytes(raw)
                with patch('podcast_video_kit.__main__.command', side_effect=fake_whisper) as command:
                    for flag, source, directory in (('--words-json', cache, 'imported'),
                                                    ('--whisper-model', model, 'generated')):
                        with contextlib.redirect_stderr(io.StringIO()) as error:
                            self.assertEqual(main(args + [flag, str(source), '--plan-only',
                                                          '--output', str(root/directory)]), 1)
                        self.assertRegex(error.getvalue(), r'segments\[0\]\.text does not match its timed words')
                    command.assert_called_once()
                self.assertEqual(cache.read_bytes(), raw)
                self.assertFalse(list((root/'imported').iterdir()))
                self.assertEqual({p.name for p in (root/'generated').iterdir()}, {'words.json'})
                self.assertEqual((root/'generated'/'words.json').read_bytes(), raw)
                words += [{'start': .4, 'end': .7, 'word': ' why'}, {'start': .7, 'end': 1, 'word': ' blue'}]
                docx(root/'script.docx', ['Script', 'A: Red blue'])
                cache.write_text(json.dumps({'segments': [{'text': '  ＲＥＤ, WHY! Blue.', 'words': words}]}))
                self.assertEqual(main(args + ['--words-json', str(cache), '--plan-only',
                                              '--output', str(root/'valid')]), 0)
            plan = json.loads((root/'valid'/'plan.json').read_text())
            self.assertEqual(plan['turns'], [dict(speaker='A', text='Red blue', paragraph=2,
                                                 coverage=1, start=.1, end=1)])
            self.assertEqual(plan['captions'][1], dict(start=.4, end=.7, text='why', speaker=''))
            self.assertIn('\nwhy\n\n', (root/'valid'/'captions.srt').read_text())

    def test_missing_or_corrupt_selected_font_fails_before_whisper_except_plan_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = cli_fixture(root, ['Script', 'A: Red'])
            model, missing, corrupt = (root/name for name in ('model.pt', 'missing.ttf', 'corrupt.ttf'))
            model.touch()
            corrupt.write_bytes(b'not a font')
            args += ['--whisper-model', str(model)]

            def fake_whisper(command):
                raw_dir = Path(command[command.index('--output_dir') + 1])
                (raw_dir/'narration.json').write_text(
                    json.dumps({'segments': [{'words': [dict(start=0, end=1, word='Red')]}]}))

            with patch('podcast_video_kit.__main__.duration_wav', return_value=1), \
                    patch('podcast_video_kit.__main__.command') as command, \
                    patch.dict(os.environ, PVK_FONT=str(corrupt)):
                for font_args, mode, message, path in (
                    (['--font', str(missing)], [], 'Font file not found', missing),
                    ([], ['--preview', '1'], 'Cannot load font', corrupt),
                ):
                    with contextlib.redirect_stderr(io.StringIO()) as error:
                        self.assertEqual(main(args + font_args + mode + ['--output', str(root/'render')]), 1)
                    self.assertIn(message, error.getvalue())
                    self.assertIn(str(path), error.getvalue())
                self.assertFalse((root/'render').exists())
                del os.environ['PVK_FONT']
                with patch('podcast_video_kit.__main__.MAC_FONT', corrupt), \
                        contextlib.redirect_stderr(io.StringIO()) as error:
                    self.assertEqual(main(args + ['--output', str(root/'default')]), 1)
                    self.assertIn(f'Cannot load font {corrupt}', error.getvalue())
                command.assert_not_called()
                command.side_effect = fake_whisper
                for path in (missing, corrupt):
                    out = root/path.stem
                    self.assertEqual(main(args + ['--font', str(path), '--plan-only', '--output', str(out)]), 0)
                    self.assertTrue((out/'plan.json').is_file())

    def test_long_script_is_rejected_before_whisper_in_plan_and_preview(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = cli_fixture(root, ['Script', 'A: ' + 'ß ' * 15_000, 'B: !x'])
            model = root/'model.pt'
            model.touch()
            with patch('podcast_video_kit.__main__.command') as command:
                for mode in (['--plan-only'], ['--preview', '1']):
                    with self.subTest(mode=mode), contextlib.redirect_stderr(io.StringIO()) as error:
                        self.assertEqual(main(args + ['--whisper-model', str(model),
                                                      '--output', str(root/'run')] + mode), 1)
                        self.assertIn('30,000 normalized characters', error.getvalue())
                command.assert_not_called()
            self.assertFalse((root/'run').exists())
        with self.assertRaisesRegex(ValueError, '30,000 normalized characters'):
            align([dict(speaker='A', text='red')], [(0, 1, 'red' * 10_001)])

    def test_preview_frame_validation_uses_clipped_half_open_cues(self):
        args = SimpleNamespace(preview_start=1, preview=.04)
        window = _render_window(args, 2)
        visible = dict(start=.99, end=1.01)
        invisible = dict(start=1.01, end=1.05)
        outside = dict(start=1.05, end=1.06)
        with self.assertRaisesRegex(ValueError, r'Caption cue 2 \[1\.01, 1\.05\)'):
            _validate_cue_frames([visible, invisible, outside], *window)
        _validate_cue_frames([dict(start=.98, end=1), visible, outside], *window)
        _validate_cue_frames([dict(start=1.021, end=1.04)], *_render_window(args, Fraction(51, 50)))

    def test_unmatched_lexical_intervals_neutralize_only_their_own_frames(self):
        from PIL import Image, ImageChops, ImageFont
        from podcast_video_kit.render import Renderer

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = cli_fixture(root, ['Script', 'A: Red blue'])
            for name, color in (('a', 'red'), ('b', 'green')):
                Image.new('RGB', (60, 80), color).save(root/f'{name}.png')
            font_path = root/'font.ttf'
            font_path.write_bytes(ImageFont.load_default(size=36).font_bytes)
            cache = root/'input.json'
            cache.write_text(json.dumps({'segments': [{'words': [
                dict(start=0, end=.5, word='Red'), dict(start=.5, end=.75, word='!'),
                dict(start=.75, end=1, word=' xx'), dict(start=1.25, end=1.5, word=' yy'),
                dict(start=1.5, end=2, word=' blue'),
            ]}]}))

            def check_frames(options, directory, config, turns, cues, scenes, duration, font, unmatched_words):
                portraits = (options.portrait_a, options.portrait_b, font, 'Podcast')
                actual = Renderer(*portraits, turns, cues, scenes, unmatched_words=unmatched_words)
                neutral = Renderer(*portraits, [], cues, scenes)
                live = Renderer(*portraits, turns, cues, scenes)
                for index in range(17, 37):
                    with self.subTest(frame=index):
                        frame = actual.frame(index, .8)
                        unknown = index in range(18, 24) or index in range(30, 36)
                        expected = (neutral if unknown else live).frame(index, .8)
                        self.assertEqual(frame.mode, 'RGB')
                        self.assertIsNone(ImageChops.difference(frame, expected).getbbox())
                        # Close-up A meter at this time, or the idle wide layout.
                        self.assertEqual(frame.getpixel((1130, 499)) == (255, 203, 129), not unknown)
                return dict(mode='full', frames=48)

            out = root/'render'
            with patch('podcast_video_kit.__main__.duration_wav', return_value=2), \
                    patch('podcast_video_kit.__main__.make_video', side_effect=check_frames):
                self.assertEqual(main(args + ['--words-json', str(cache), '--font', str(font_path),
                                              '--output', str(out)]), 0)
            plan = json.loads((out/'plan.json').read_text())
            self.assertEqual(plan['turns'], [dict(speaker='A', text='Red blue', paragraph=2,
                                                 start=0, end=2, coverage=1)])
            self.assertEqual(plan['captions'], [dict(start=0, end=.75, speaker='A', text='Red!'),
                                               dict(start=.75, end=1.5, speaker='', text='xx yy'),
                                               dict(start=1.5, end=2, speaker='A', text='blue')])

    def test_raw_whisper_transcript_uses_system_temp_and_is_cleaned(self):
        with tempfile.TemporaryDirectory() as temp:
            checkout = Path(temp).resolve() / 'checkout'
            run = checkout / 'custom-output'
            checkout.mkdir()
            docx(checkout/'script.docx', ['Script', 'A: Hi'])
            for name in ('a.png', 'b.png', 'take.wav', 'model.pt'):
                (checkout/name).touch()
            expected = {'segments': [{'words': [{'start': 0, 'end': .5, 'word': 'Hi'}]}]}
            locations = []

            def fake_whisper(command):
                raw_dir = Path(command[command.index('--output_dir') + 1]).resolve()
                self.assertFalse(raw_dir.is_relative_to(checkout))
                self.assertEqual(raw_dir.parent, Path(tempfile.gettempdir()).resolve())
                locations.append(raw_dir)
                (raw_dir/'take.json').write_text(json.dumps(expected))

            args = ['--script', str(checkout/'script.docx'), '--section', 'Script',
                    '--narration', str(checkout/'take.wav'), '--portrait-a', str(checkout/'a.png'),
                    '--portrait-b', str(checkout/'b.png'), '--whisper-model', str(checkout/'model.pt'),
                    '--plan-only', '--output', str(run)]
            with patch('podcast_video_kit.__main__.command', side_effect=fake_whisper), \
                    patch('podcast_video_kit.__main__.duration_wav', return_value=1):
                self.assertEqual(main(args), 0)
            self.assertFalse(locations[0].exists())
            self.assertEqual(json.loads((run/'words.json').read_text()), expected)
            self.assertEqual({p.name for p in run.iterdir()}, {'words.json', 'plan.json', 'captions.srt'})

    def test_zero_duration_imported_word_fails_before_alignment_without_copying(self):
        src = {'segments': [{'words': [{'start': .3, 'end': .3, 'word': 'hi'},
                                      {'start': .3, 'end': .5, 'word': ' yes'}]}]}
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp)
            docx(p/'script.docx', ['Script', 'A: hi', 'B: yes'])
            for name in ('a.png', 'b.png', 'narration.wav'):
                (p/name).touch()
            (p/'input.json').write_text(json.dumps(src))
            args = ['--script', str(p/'script.docx'), '--section', 'Script',
                    '--narration', str(p/'narration.wav'), '--portrait-a', str(p/'a.png'),
                    '--portrait-b', str(p/'b.png'), '--words-json', str(p/'input.json'),
                    '--plan-only', '--output', str(p/'run')]
            with patch('podcast_video_kit.__main__.duration_wav', return_value=1), \
                    contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(main(args), 1)
            self.assertRegex(error.getvalue(), r'segments\[0\]\.words\[0\] has no positive duration')
            self.assertEqual(json.loads((p/'input.json').read_text()), src)
            self.assertFalse(list((p/'run').iterdir()))

    def test_cli_opt_in_repairs_multiple_zero_spans_without_rewriting_raw_cache(self):
        def word(start, end, text):
            return dict(start=start, end=end, word=text)

        src = {'segments': [dict(text='Hello', words=[word(0, .5, 'Hello')]),
                            dict(text='Yes friend', words=[word(.8, .8, 'Yes'), word(.8, 1, ' friend')]),
                            dict(text='See you later', words=[word(1.3, 1.3, 'See'),
                                 word(1.3, 1.3, ' you'), word(1.3, 1.6, ' later')])]}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = cli_fixture(root, ['Script', 'A: Hello', 'B: Yes friend', 'A: See you later'])
            cache = root / 'input.json'
            cache.write_text(json.dumps(src))
            original = cache.read_bytes()
            out = root / 'run'
            model = root/'model.pt'
            model.touch()

            def fake_whisper(command):
                folder = Path(command[command.index('--output_dir') + 1])
                (folder/'narration.json').write_bytes(original)

            with patch('podcast_video_kit.__main__.duration_wav', return_value=2), \
                    patch('podcast_video_kit.__main__.command', side_effect=fake_whisper) as command, \
                    contextlib.redirect_stderr(io.StringIO()) as warning:
                options = ['--repair-zero-duration', '--plan-only']
                self.assertEqual(main(args + options + ['--words-json', str(cache), '--output', str(out)]), 0)
                command.assert_not_called()
                self.assertEqual(main(args + options + ['--whisper-model', str(model),
                                                       '--output', str(root/'generated')]), 0)
                command.assert_called_once()
            self.assertIn('Estimated timings for 3', warning.getvalue())
            self.assertEqual(cache.read_bytes(), original)
            self.assertEqual((out / 'words.json').read_bytes(), original)
            self.assertEqual((root/'generated'/'words.json').read_bytes(), original)
            plan = json.loads((out / 'plan.json').read_text())
            estimates = plan['estimated_word_timings']
            self.assertEqual([(r['segment'], r['word']) for r in estimates], [(1, 0), (2, 0), (2, 1)])
            self.assertTrue(all(r['start'] < r['end'] for r in estimates))
            self.assertEqual(estimates[0]['end'], .8)
            self.assertEqual(estimates[1]['end'], estimates[2]['start'])
            self.assertEqual(estimates[2]['end'], 1.3)
            self.assertEqual(plan['script_character_coverage'], 1)
            self.assertIn('See you later', (out / 'captions.srt').read_text())

    def test_repair_uses_neighbor_bounds_across_segments_and_keeps_separators(self):
        def word(start, end, text):
            return dict(start=start, end=end, word=text)

        src = {'segments': [dict(words=[word(0, .6, 'Hi'), word(.6, .6, ' there')]),
                            dict(words=[word(.6, .6, ' '), word(.6, .6, 'again'),
                                        word(.8, 1, ' friend'), word(1.2, 1.2, ' yes')]),
                            dict(words=[word(1.2, 1.5, ' indeed')])]}
        raw = json.dumps(src)
        repaired, estimates = repair_zero_duration(src, 2)
        words = read_words(repaired, 2)
        self.assertEqual(json.dumps(src), raw)
        self.assertEqual([text for _, _, text in words], ['Hi', ' there', ' again', ' friend', ' yes', ' indeed'])
        self.assertEqual([words[j][:2] for j in (0, 3, 5)], [(0, .6), (.8, 1), (1.2, 1.5)])
        self.assertEqual([(r['segment'], r['word']) for r in estimates], [(0, 1), (1, 1), (1, 3)])
        self.assertEqual(words[1][0], .6)
        self.assertEqual(words[4][1], 1.2)
        self.assertTrue(all(a < b for a, b, _ in words))
        self.assertTrue(all(a[1] <= b[0] for a, b in zip(words, words[1:])))

    def test_repair_rejects_ambiguous_zero_spans_and_keeps_strict_checks(self):
        def src(*times, text=None):
            seg = dict(words=[dict(start=a, end=b, word=' Yes') for a, b in times])
            if text is not None:
                seg['text'] = text
            return dict(segments=[seg])

        for times in (((.1, .4), (.3, .3), (.5, .7)),
                      ((.39, .4), (.4, .4), (.4, .41)),
                      ((.1, .4), (.5, .5), (.45, .7)),
                      ((.1, .4), (1.01, 1.01)),
                      ((.39, .4), (.4001, .4001), (.401, .411))):
            with self.subTest(times=times), self.assertRaisesRegex(ValueError, 'Cannot estimate.*words\\[1\\]'):
                repair_zero_duration(src(*times), 1)
        clipped, estimates = repair_zero_duration(src((.1, .4), (.38, .5)), 1)
        self.assertFalse(estimates)
        self.assertEqual(read_words(clipped, 1)[1][:2], (.4, .5))
        collapsed, estimates = repair_zero_duration(src((.1, .4), (.38, .4)), 1)
        self.assertFalse(estimates)
        with self.assertRaisesRegex(ValueError, 'no positive duration'):
            read_words(collapsed, 1)
        mismatch, _ = repair_zero_duration(src((.3, .3), (.3, .5), text='Other text'), 1)
        with self.assertRaisesRegex(ValueError, 'does not match'):
            read_words(mismatch, 1)

    def test_repair_can_trim_touching_neighbors_without_rewriting_original(self):
        def word(start, end, text):
            return dict(start=start, end=end, word=text)

        src = {'segments': [dict(words=[word(0, .1, 'Hi'), word(.1, .1, ' there')]),
                            dict(words=[word(.1, .25, ' friend'), word(.25, .25, ' and'),
                                        word(.25, .25, ' then'), word(.25, .29, ' goodbye')])]}
        original = json.dumps(src)
        repaired, records = repair_zero_duration(src, 1)
        self.assertEqual(json.dumps(src), original)
        words = read_words(repaired, 1)
        self.assertEqual([text for _, _, text in words], ['Hi', ' there', ' friend', ' and', ' then', ' goodbye'])
        self.assertTrue(all(a < b for a, b, _ in words))
        self.assertTrue(all(a[1] <= b[0] for a, b in zip(words, words[1:])))
        self.assertAlmostEqual(words[0][1], .08)
        self.assertAlmostEqual(words[2][1], .21)
        self.assertEqual(words[-1][:2], (.25, .29))
        neighbors = [item for item in records if item.get('kind') == 'neighbor_boundary']
        self.assertEqual([(item['segment'], item['word']) for item in neighbors], [(0, 0), (1, 0)])

    def test_repair_can_share_boundary_budget_between_both_neighbors(self):
        words = [dict(start=a, end=b, word=' x') for a, b in ((.16, .2), (.2, .2), (.2, .2), (.2, .24))]
        repaired, records = repair_zero_duration(dict(segments=[dict(words=words)]), 1)
        times = [(a, b) for a, b, _ in read_words(repaired, 1)]
        for actual, expected in zip(times, ((.16, .18), (.18, .2), (.2, .22), (.22, .24))):
            for a, b in zip(actual, expected):
                self.assertAlmostEqual(a, b)
        self.assertEqual(sum(r.get('kind') == 'neighbor_boundary' for r in records), 2)

    def test_concepts_preserve_explicit_body_and_reject_overlap(self):
        turns = [dict(start=0, end=3), dict(start=3.5, end=5)]
        item = dict(first_turn=1, last_turn=2, title='Example', body='1 → 2')
        self.assertEqual(concept_scenes(dict(scenes=[item]), turns),
                         [dict(start=0, end=5, title='Example', body='1 → 2')])
        for scenes in [[item, item], [dict(item, first_turn=0)]]:
            with self.assertRaises(ValueError):
                concept_scenes(dict(scenes=scenes), turns)

    def test_concept_duration_allows_only_roundoff_below_two_seconds(self):
        config = dict(scenes=[dict(first_turn=1, title='Example', body='Details')])
        self.assertEqual(concept_scenes(config, [dict(start=.30, end=2.30)]),
                         [dict(start=.30, end=2.30, title='Example', body='Details')])
        with self.assertRaisesRegex(ValueError, 'at least 2 seconds'):
            concept_scenes(config, [dict(start=.30, end=2.299999999)])


FONT_CANDIDATES = ['/System/Library/Fonts/AppleSDGothicNeo.ttc',
                   '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
FONT = next((x for x in FONT_CANDIDATES if Path(x).is_file()), None)


@unittest.skipUnless(FONT and shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Needs ffmpeg and a local font')
class MediaSmokeTest(unittest.TestCase):
    def test_cached_zero_durations_render_a_verified_preview(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = cli_fixture(root, ['Script', 'A: Hello', 'B: Good morning', 'A: Goodbye friend'])
            with wave.open(str(root/'narration.wav'), 'wb') as wav:
                wav.setparams((1, 2, 24_000, 0, 'NONE', 'not compressed'))
                wav.writeframes(b'\x01\x00' * 48_000)
            for name in ('a', 'b'):
                Image.new('RGB', (64, 80), 'green').save(root/f'{name}.png')
            cache = root/'input.json'
            cache.write_text(json.dumps({'segments': [dict(words=[
                dict(start=0, end=.5, word='Hello'),
                dict(start=.5, end=.5, word=' Good'), dict(start=.5, end=1.1, word=' morning'),
                dict(start=1.1, end=1.1, word=' Goodbye'), dict(start=1.1, end=1.5, word=' friend')])]}))
            out = root/'preview'
            self.assertEqual(main(args + ['--words-json', str(cache), '--repair-zero-duration',
                                          '--font', FONT, '--preview', '2', '--output', str(out)]), 0)
            verification = json.loads((out/'verification.json').read_text())
            self.assertEqual(verification['decode'], 'PASS')
            self.assertEqual(verification['frames'], 48)
            plan = json.loads((out/'plan.json').read_text())
            self.assertEqual(sum(r.get('kind') == 'neighbor_boundary'
                                 for r in plan['estimated_word_timings']), 2)
            self.assertTrue((out/'preview.mp4').is_file())

    def test_preview_passes_with_an_oversized_card_outside_its_window(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = cli_fixture(root, ['Script', 'A: Red', 'B: blue'])
            with wave.open(str(root/'narration.wav'), 'wb') as wav:
                wav.setparams((1, 2, 24_000, 0, 'NONE', 'not compressed'))
                wav.writeframes(b'\x01\x00' * 96_000)
            for name in ('a', 'b'):
                Image.new('RGB', (60, 80), 'green').save(root/f'{name}.png')
            cache, config = root/'input.json', root/'config.json'
            cache.write_text(json.dumps({'segments': [{'words': [
                dict(start=0, end=2, word='Red'), dict(start=2, end=4, word=' blue'),
            ]}]}))
            config.write_text(json.dumps({'scenes': [
                dict(first_turn=1, title='First', body='line\n' * 40),
                dict(first_turn=2, title='Second', body='This fits'),
            ]}))
            args += ['--words-json', str(cache), '--font', FONT, '--config', str(config), '--preview', '.125']
            outside, inside = root/'outside', root/'inside'
            self.assertEqual(main(args + ['--output', str(outside), '--preview-start', '2']), 0)
            self.assertTrue((outside/'preview.mp4').is_file())
            with contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(main(args + ['--output', str(inside)]), 1)
            self.assertIn('scene body at 0s does not fit', error.getvalue())
            for name in ('plan.json', 'captions.srt'):
                self.assertEqual((outside/name).read_bytes(), (inside/name).read_bytes())
            plan = json.loads((outside/'plan.json').read_text())
            self.assertEqual([(s['start'], s['end']) for s in plan['scenes']], [(0, 2), (2, 4)])
            self.assertIn('00:00:02,000 --> 00:00:04,000', (outside/'captions.srt').read_text())

    def test_cue_between_frames_fails_full_render_but_outside_preview_renders(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = cli_fixture(root, ['Script', 'A: Red', 'B: blue'])
            with wave.open(str(root/'narration.wav'), 'wb') as wav:
                wav.setparams((1, 2, 24_000, 0, 'NONE', 'not compressed'))
                wav.writeframes(b'\x01\x00' * 30_000)
            for name in ('a', 'b'):
                Image.new('RGB', (100, 100), 'green').save(root/f'{name}.png')
            cache = root/'input.json'
            cache.write_text(json.dumps({'segments': [{'text': 'Red blue', 'words': [
                dict(start=.9, end=1.01, word='Red'), dict(start=1.01, end=1.03, word=' blue')
            ]}]}))
            args += ['--words-json', str(cache), '--font', FONT]
            with contextlib.redirect_stderr(io.StringIO()) as error:
                self.assertEqual(main(args + ['--output', str(root/'full')]), 1)
            self.assertRegex(error.getvalue(), r'Caption cue 2 \[1\.01, 1\.03\).*24 fps')
            self.assertFalse((root/'full'/'audio.m4a').exists())
            self.assertEqual(main(args + ['--output', str(root/'preview'), '--preview-start', '.875',
                                         '--preview', '.125']), 0)
            self.assertTrue((root/'preview'/'preview.mp4').is_file())

    def test_exact_sample_duration_and_touching_turns_render(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            docx(p/'script.docx', ['Script', 'A: abcdefghi', 'B: yes'])
            with wave.open(str(p/'narration.wav'), 'wb') as w:
                w.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                w.writeframes(b'\x01\x00' * 25_000)
            self.assertEqual(math.ceil(duration_wav(p/'narration.wav') * 24), 25)
            Image.new('RGB', (100, 100), 'blue').save(p/'a.png')
            Image.new('RGB', (100, 100), 'green').save(p/'b.png')
            (p/'input.json').write_text(json.dumps({'segments': [{'words': [
                {'start': .2, 'end': .44, 'word': 'abcdefghi'},
                {'start': .44, 'end': .7, 'word': ' yes'},
            ]}]}))
            switches = ['--script', str(p/'script.docx'), '--section', 'Script',
                        '--narration', str(p/'narration.wav'), '--portrait-a', str(p/'a.png'),
                        '--portrait-b', str(p/'b.png'), '--words-json', str(p/'input.json'), '--font', FONT]
            for name, length, mode in [('full', 25, []), ('tail', 13, ['--preview', '1', '--preview-start', '0.5'])]:
                with self.subTest(mode=name):
                    out = p/name
                    self.assertEqual(main(switches + ['--output', str(out)] + mode), 0)
                    report = json.loads((out/'verification.json').read_text())
                    self.assertEqual(report['decode'], 'PASS')
                    self.assertEqual(report['frames'], length)

    def test_full_and_offset_preview(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory)
            docx(p / 'script.docx', ['7. 팟캐스트 대본', 'A: First', 'B: Second'])
            with wave.open(str(p / 'narration.wav'), 'wb') as w:
                w.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
                w.writeframes(b'\x01\x00' * 60001)
            for name, color in [('a', '#658ba0'), ('b', '#66a683')]:
                Image.new('RGB', (320, 320), color).save(p / f'{name}.png')
            src = {'segments': [{'words': [{'start': .2, 'end': 1.1, 'word': 'First'},
                                          {'start': 1.3, 'end': 2.2, 'word': 'Second'}]}]}
            (p / 'input.json').write_text(json.dumps(src))
            (p / 'config.json').write_text(json.dumps({'scenes': [dict(first_turn=1,last_turn=2,
                                                title='Concept', body='Input → Output')]}))
            switches = ['--script', str(p/'script.docx'), '--narration', str(p/'narration.wav'),
                        '--portrait-a', str(p/'a.png'), '--portrait-b', str(p/'b.png'),
                        '--words-json', str(p/'input.json'), '--font', FONT, '--config', str(p/'config.json')]
            runs = [(p/'full','episode.mp4',61,2.50004,[]),
                    (p/'preview','preview.mp4',24,1.0,['--preview', '1', '--preview-start', '0.5'])]
            for output, filename, frame_count, seconds, mode in runs:
                with self.subTest(mode=filename):
                    self.assertEqual(main(switches+['--output',str(output)]+mode), 0)
                    self.assertTrue((output / filename).is_file())
                    report = json.loads((output / 'verification.json').read_text())
                    self.assertEqual(report['decode'], 'PASS')
                    self.assertEqual(report['frames'], frame_count)
                    self.assertAlmostEqual(report['audio_seconds'], seconds, delta=.05)
            before = (p/'full/episode.mp4').stat().st_size
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(switches+['--output',str(p/'full')]), 1)
            self.assertEqual((p/'full/episode.mp4').stat().st_size, before)


if __name__ == '__main__':
    unittest.main()
