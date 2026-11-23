import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import wave
from xml.sax.saxutils import escape
from zipfile import ZipFile

from podcast_video_kit.__main__ import main
from podcast_video_kit.episode import align, captions, concept_scenes, read_words, script, srt


def docx(path, rows):
    xml = ''.join(f'<w:p><w:r><w:t>{escape(row)}</w:t></w:r></w:p>' for row in rows)
    with ZipFile(path, 'w') as z:
        z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                   f'<w:body>{xml}</w:body></w:document>')


class PlanningTests(unittest.TestCase):
    def test_section_boundaries_notes_and_repeat_speaker(self):
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / 'example.docx'
            docx(p, ['A: Outside', '7. 팟캐스트 대본', 'A: 시작', '메모', 'A： 계속', 'B: 끝', '8. Notes', 'A: Outside'])
            turns, notes = script(p, '7. 팟캐스트 대본')
            self.assertEqual([t['speaker'] for t in turns], ['A', 'A', 'B'])
            self.assertEqual(notes, [{'paragraph': 4, 'after_turn': 1, 'text': '메모'}])
            with self.assertRaisesRegex(ValueError, 'one script heading'):
                script(p, 'missing')

    def test_monotonic_alignment_captions_and_unmatched_words(self):
        src = dict(segments=[dict(words=[dict(start=a,end=b,word=text) for a,b,text in
                   [(0.0, .3, 'Unscripted'), (.6, 1.4, 'FIRST'), (1.9, 2.3, 'second'), (2.9, 3.4, 'third')]])])
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

    def test_alignment_fails_instead_of_inventing_missing_turn(self):
        with self.assertRaisesRegex(ValueError, 'No matches for turns: 2'):
            align([dict(speaker='A', text='hello'), dict(speaker='B', text='xyz')], [(0, 1, 'hello')])

    def test_bad_word_coordinates_and_empty_word_list(self):
        for times in [(float('nan'), 1), (-1, 1), (0.4, 0.2), (0, 9)]:
            with self.subTest(times=times), self.assertRaisesRegex(ValueError, 'timestamps'):
                read_words({'segments': [{'words': [{'start': times[0], 'end': times[1], 'word': 'test'}]}]}, 3)
        with self.assertRaisesRegex(ValueError, 'word timestamps'):
            read_words({'segments': [{}]}, 3)

    def test_concepts_preserve_explicit_body_and_reject_overlap(self):
        turns = [dict(start=0, end=3), dict(start=3.5, end=5)]
        item = dict(first_turn=1, last_turn=2, title='Example', body='1 → 2')
        self.assertEqual(concept_scenes(dict(scenes=[item]), turns),
                         [dict(start=0, end=5, title='Example', body='1 → 2')])
        for scenes in [[item, item], [dict(item, first_turn=0)]]:
            with self.assertRaises(ValueError):
                concept_scenes(dict(scenes=scenes), turns)


FONT_CANDIDATES = ['/System/Library/Fonts/AppleSDGothicNeo.ttc',
                   '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
FONT = next((x for x in FONT_CANDIDATES if Path(x).is_file()), None)


@unittest.skipUnless(FONT and shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Needs ffmpeg and a local font')
class MediaSmokeTest(unittest.TestCase):
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
