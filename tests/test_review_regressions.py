"""Synthetic regressions for source parsing and render preflight."""
import contextlib
from fractions import Fraction
import io
import json
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave
from zipfile import ZipFile

from PIL import Image, ImageFont

from podcast_video_kit.__main__ import _render_window
from podcast_video_kit.episode import align, captions, normalized, read_words, script, srt
from test_episode import FONT, NS, cli_fixture, docx, number_props, run_episode


def write_wave(path, samples):
    with wave.open(str(path), 'wb') as wav:
        wav.setparams((1, 2, 24_000, 0, 'NONE', 'not compressed'))
        wav.writeframes(b'\x01\x00' * samples)


class ReviewRegressions(unittest.TestCase):
    def test_word_alternate_content_reads_only_one_representation(self):
        def paragraph(text):
            return f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>'

        def drawing(text, kind='drawing'):
            return f'<w:{kind}><w:txbxContent>{paragraph(text)}</w:txbxContent></w:{kind}>'

        hello, duplicate = drawing('A: Hello'), drawing('A: Hello', 'pict')
        fallback = drawing('B: Fallback only', 'pict')
        xml = (f'<w:document xmlns:w="{NS}" xmlns:mc="http://schemas.openxmlformats.org/'
               'markup-compatibility/2006" xmlns:wps="http://schemas.microsoft.com/office/word/'
               '2010/wordprocessingShape"><w:body>' + paragraph('Script')
               + f'<w:p><w:r><mc:AlternateContent><mc:Choice Requires="wps">{hello}</mc:Choice>'
               f'<mc:Fallback>{duplicate}</mc:Fallback></mc:AlternateContent></w:r></w:p>'
               ' <w:p><w:r><mc:AlternateContent><mc:Choice Requires="wps"><wps:placeholder/>'
               f'</mc:Choice><mc:Fallback>{fallback}</mc:Fallback></mc:AlternateContent></w:r></w:p>'
               + paragraph('A: Outside fallback') + '</w:body></w:document>')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'example.docx'
            with ZipFile(path, 'w') as z:
                z.writestr('word/document.xml', xml)
            turns, notes = script(path, 'Script')
            self.assertEqual([t['text'] for t in turns], ['Hello', 'Fallback only', 'Outside fallback'])
            self.assertFalse(notes)

    def test_srt_quantization_keeps_positive_nonoverlapping_cues(self):
        cues = [dict(start=.95, end=.9998, speaker='A', text='Hello'),
                dict(start=.9998, end=1.0001, speaker='B', text='Bye'),
                dict(start=1.0001, end=1.13, speaker='A', text='Again')]
        lines = [line for line in srt(cues).splitlines() if ' --> ' in line]
        self.assertEqual(len(lines), 3)
        times = [line.split(' --> ') for line in lines]
        self.assertTrue(all(start < end for start, end in times), times)
        self.assertTrue(all(left[1] <= right[0] for left, right in zip(times, times[1:])), times)
        self.assertEqual(times[0][0], '00:00:00,950')
        self.assertEqual(times[-1][1], '00:00:01,130')

    def test_srt_reports_cues_that_cannot_fit_at_millisecond_precision(self):
        cues = [dict(start=0, end=.0004, speaker='A', text='Hello'),
                dict(start=.0004, end=.0009, speaker='B', text='Bye')]
        with self.assertRaisesRegex(ValueError, 'SRT cue .*millisecond precision'):
            srt(cues)

    def test_combining_marks_distinguish_words_but_keep_canonical_equivalence(self):
        self.assertNotEqual(normalized('काम'), normalized('कम'))
        self.assertEqual(normalized('Cafe\u0301'), normalized('CAFÉ'))
        self.assertEqual(normalized('한글'), normalized('\u1112\u1161\u11ab글'))
        self.assertFalse(normalized('!\u093e'))
        entries = [dict(start=0, end=1, word='कम')]
        with self.assertRaisesRegex(ValueError, r'segments\[0\]\.text does not match'):
            read_words({'segments': [dict(text='काम', words=entries)]}, 1)
        _, _, coverage = align([dict(speaker='A', text='काम')], [(0, 1, 'कम')])
        self.assertLess(coverage, 1)

    def test_textbox_paragraph_is_visited_once(self):
        xml = (f'<w:document xmlns:w="{NS}"><w:body>'
               '<w:p><w:r><w:t>Script</w:t></w:r></w:p>'
               '<w:p><w:r><w:drawing><w:txbxContent><w:p><w:r><w:t>A: Hello</w:t></w:r>'
               '</w:p></w:txbxContent></w:drawing></w:r></w:p>'
               '<w:p><w:r><w:t>B: Bye</w:t></w:r></w:p></w:body></w:document>')
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'example.docx'
            with ZipFile(path, 'w') as z:
                z.writestr('word/document.xml', xml)
            turns, notes = script(path, 'Script')
        self.assertEqual([(t['speaker'], t['text']) for t in turns], [('A', 'Hello'), ('B', 'Bye')])
        self.assertFalse(notes)

    def test_nested_list_number_is_not_a_typed_section_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'example.docx'
            docx(path, ['7. Script', 'A: Red', ('8. Example', number_props(level=1)),
                        'B: Blue', '8. Appendix', 'A: Outside'])
            turns, notes = script(path, '7. Script')
        self.assertEqual([t['text'] for t in turns], ['Red', 'Blue'])
        self.assertEqual([n['text'] for n in notes], ['8. Example'])

    def test_separator_only_tokens_preserve_text_without_own_timing(self):
        for expected, entries in (
            ('red \tblue', [(0, .4, 'red'), (.4, .4, ' '), (.4, .4, '\t'), (.5, 1, 'blue')]),
            ('한글', [(0, .4, '한'), (.5, 1, '글')]),
        ):
            with self.subTest(expected=expected):
                words = read_words({'segments': [dict(text=expected, words=[
                    dict(start=a, end=b, word=t) for a, b, t in entries])]}, 1)
                self.assertEqual([w[:2] for w in words], [(0, .4), (.5, 1)])
                cue, = captions([dict(start=0, end=1, speaker='A')], words)
                self.assertEqual(cue['text'], expected)
                self.assertIn(expected, srt([cue]))
        words = read_words({'segments': [dict(text='red ', words=[dict(start=0, end=.4, word='red'),
                            dict(start=.4, end=.4, word=' ')]),
                            dict(text='blue', words=[dict(start=.5, end=1, word='blue')])]}, 1)
        self.assertEqual(''.join(w[2] for w in words), 'red blue')

    def test_portraits_are_decoded_before_whisper_only_for_render_modes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = cli_fixture(root, ['Script', 'A: Red'])
            font = root/'font.ttf'
            font.write_bytes(ImageFont.load_default(size=36).font_bytes)
            model = root/'model.pt'
            model.touch()
            args.update(font=font.name, whisper_model=model.name)
            for bad, transparent in [('a.png', False), ('b.png', True)]:
                for portrait in ('a.png', 'b.png'):
                    Image.new('RGBA', (12, 16), 'red').save(root/portrait)
                if transparent:
                    Image.new('RGBA', (12, 16)).save(root/bad)
                else:
                    (root/bad).write_bytes(b'not an image')
                for mode in ({}, dict(preview=1)):
                    with self.subTest(bad=bad, mode=mode), \
                            patch('podcast_video_kit.__main__.duration_wav', return_value=2), \
                            patch('podcast_video_kit.__main__.transcribe', return_value=(
                                b'{"segments":[{"words":[{"word":"Red","start":0,"end":1}]}]}')) as whisper, \
                            contextlib.redirect_stderr(io.StringIO()) as error:
                        with tempfile.TemporaryDirectory(dir=root) as temp_out:
                            out = Path(temp_out)/'render'
                            self.assertEqual(run_episode(root, args, output=str(out), **mode), 1)
                            whisper.assert_not_called()
                            self.assertIn(bad, error.getvalue())
                            self.assertFalse(out.exists())
                            self.assertEqual(run_episode(root, args, plan_only=True, output=str(out)), 0)
                            whisper.assert_called_once()
                            self.assertTrue((out/'plan.json').is_file())

    def test_preview_uses_exact_bounds_then_clamps_to_last_available_frame(self):
        for start in ('1.01', '1.001'):
            with self.subTest(start=start), self.assertRaisesRegex(ValueError, 'recording or at its end'):
                _render_window(SimpleNamespace(preview=1, preview_start=start), Fraction('1.001'))
        self.assertEqual(_render_window(SimpleNamespace(preview=1, preview_start='1.035'), Fraction('1.04')),
                         (24, 25, Fraction(1), Fraction('1.04')))
        just_inside = Fraction('1.039999999999999999')
        self.assertEqual(_render_window(SimpleNamespace(preview=1, preview_start=just_inside), Fraction('1.04')),
                         (24, 25, Fraction(1), Fraction('1.04')))
        self.assertEqual(_render_window(SimpleNamespace(preview=.04, preview_start='.06'), Fraction(2)),
                         (1, 2, Fraction(1, 24), Fraction(2, 24)))


@unittest.skipUnless(shutil.which('ffprobe'), 'Needs ffprobe')
class ProbeRegressions(unittest.TestCase):
    def test_plan_accepts_dash_prefixed_local_wav(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            args = cli_fixture(root, ['Script', 'A: Hello'])
            wav = root / '-take.wav'
            write_wave(wav, 24_000)
            words = root / 'input.json'
            words.write_text(json.dumps({'segments': [{'words': [dict(start=0, end=1, word='Hello')]}]}))
            self.assertEqual(run_episode(root, args, narration=wav.name, words_json=words.name,
                                         plan_only=True, output='result'), 0)
            self.assertTrue((root/'result/plan.json').is_file())


@unittest.skipUnless(FONT and shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Needs ffmpeg and a local font')
class TailMediaRegressions(unittest.TestCase):
    def run_tail(self, root, preview):
        args = cli_fixture(root, ['Script', 'A: Hello', 'B: Bye'])
        write_wave(root / 'narration.wav', 24_001)
        for portrait in ('a', 'b'):
            Image.new('RGB', (64, 80), 'green').save(root / f'{portrait}.png')
        words = root / 'input.json'
        words.write_text(json.dumps({'segments': [{'words': [dict(start=0, end=.95, word='Hello'),
                                                             dict(start=1, end=1.01, word=' Bye')]}]}))
        out = root / 'result'
        args.update(words_json=words.name, font=FONT, output=out.name)
        if preview:
            args.update(preview_start=1, preview=1)
        self.assertEqual(run_episode(root, args), 0)
        verify = json.loads((out / 'verification.json').read_text())
        self.assertEqual(verify['decode'], 'PASS')
        self.assertEqual(verify['frames'], 1 if preview else 25)
        return (out / 'captions.srt').read_text()

    def test_final_frame_preview_renders_one_sample_excerpt(self):
        with tempfile.TemporaryDirectory() as temp:
            self.run_tail(Path(temp), preview=True)

    def test_full_render_srt_preserves_caption_clipped_at_wav_end(self):
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_tail(Path(temp), preview=False)
            self.assertIn('00:00:01,000 --> 00:00:01,001\nB: Bye', result)
