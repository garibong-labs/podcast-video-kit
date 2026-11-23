"""Synthetic regressions for source parsing and render preflight."""
import contextlib
from fractions import Fraction
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from PIL import Image, ImageFont

from podcast_video_kit.__main__ import _render_window, finite_seconds, main
from podcast_video_kit.episode import align, captions, normalized, read_words, script, srt
from test_episode import NS, cli_fixture, docx, number_props


class ReviewRegressions(unittest.TestCase):
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
            args += ['--font', str(font), '--whisper-model', str(model)]
            for bad, transparent in [('a.png', False), ('b.png', True)]:
                for portrait in ('a.png', 'b.png'):
                    Image.new('RGBA', (12, 16), 'red').save(root/portrait)
                if transparent:
                    Image.new('RGBA', (12, 16)).save(root/bad)
                else:
                    (root/bad).write_bytes(b'not an image')
                for mode in ([], ['--preview', '1']):
                    with self.subTest(bad=bad, mode=mode), \
                            patch('podcast_video_kit.__main__.duration_wav', return_value=2), \
                            patch('podcast_video_kit.__main__.transcribe', return_value=(
                                b'{"segments":[{"words":[{"word":"Red","start":0,"end":1}]}]}')) as whisper, \
                            contextlib.redirect_stderr(io.StringIO()) as error:
                        with tempfile.TemporaryDirectory(dir=root) as temp_out:
                            out = Path(temp_out)/'render'
                            self.assertEqual(main(args + mode + ['--output', str(out)]), 1)
                            whisper.assert_not_called()
                            self.assertIn(bad, error.getvalue())
                            self.assertFalse(out.exists())
                            self.assertEqual(main(args + ['--plan-only','--output',str(out)]), 0)
                            whisper.assert_called_once()
                            self.assertTrue((out/'plan.json').is_file())

    def test_preview_uses_exact_bounds_then_clamps_to_last_available_frame(self):
        for start in ('1.01', '1.001'):
            with self.subTest(start=start), self.assertRaisesRegex(ValueError, 'recording or at its end'):
                _render_window(SimpleNamespace(preview=1, preview_start=start), Fraction('1.001'))
        self.assertEqual(_render_window(SimpleNamespace(preview=1, preview_start='1.035'), Fraction('1.04')),
                         (24, 25, Fraction(1), Fraction('1.04')))
        just_inside = finite_seconds('1.039999999999999999')
        self.assertEqual(_render_window(SimpleNamespace(preview=1, preview_start=just_inside), Fraction('1.04')),
                         (24, 25, Fraction(1), Fraction('1.04')))
        self.assertEqual(_render_window(SimpleNamespace(preview=.04, preview_start='.06'), Fraction(2)),
                         (1, 2, Fraction(1, 24), Fraction(2, 24)))
