import contextlib
from fractions import Fraction
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from podcast_video_kit.__main__ import _render_window, main
from podcast_video_kit.config import load_config
from test_episode import cli_fixture


class ConfigTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.config = self.root / 'episode.json'
        self.settings = cli_fixture(self.root, ['Script', 'A: Hi']) | {
            'words_json': 'words.json', 'output': 'runs/check',
        }

    def load(self, **changes):
        self.config.write_text(json.dumps(self.settings | changes), encoding='utf-8')
        return load_config(self.config)

    def test_paths_use_the_manifest_directory_and_keep_the_font_default(self):
        absolute = self.root.parent / 'asset-test.png'
        args, presentation = self.load(portrait_a=str(absolute), portrait_b='~/b.png',
                                       mouth_motion={'A': [.5, .6, .2]}, title='Synthetic')
        self.assertEqual(args.script, self.root / 'script.docx')
        self.assertEqual(args.words_json, self.root / 'words.json')
        self.assertEqual(args.output, self.root / 'runs/check')
        self.assertEqual(args.portrait_a, absolute)
        self.assertEqual(args.portrait_b, Path.home() / 'b.png')
        self.assertIsNone(args.font)
        self.assertTrue(args.repair_zero_duration)
        self.assertEqual(presentation, {'mouth_motion': {'A': [.5, .6, .2]}, 'title': 'Synthetic'})

    def test_bad_settings_fail_before_any_media_use(self):
        for changes, message in (
            ({'portriat_a': 'typo'}, 'Unknown episode config keys'),
            ({'output': ''}, 'output must be a nonempty path'),
            ({'whisper_model': 'small.pt'}, 'exactly one of words_json or whisper_model'),
            ({'words_json': None}, 'words_json must be a nonempty path'),
            ({'preview': True}, 'preview must be a number'),
            ({'preview': 121}, 'preview must be a number'),
            ({'preview': 1, 'preview_start': -.01}, 'preview_start must be a number'),
            ({'preview_start': 0}, 'preview_start requires preview'),
            ({'preview': 1, 'plan_only': True}, 'plan_only and preview cannot both be set'),
            ({'plan_only': 'false'}, 'plan_only must be true or false'),
            ({'timing_mode': 'guess'}, 'timing_mode must be'),
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                self.load(**changes)
        for key, message in (('output', 'Missing episode config keys'),
                             ('words_json', 'exactly one of words_json or whisper_model')):
            with self.subTest(missing=key), self.assertRaisesRegex(ValueError, message):
                self.config.write_text(json.dumps({k: v for k, v in self.settings.items() if k != key}))
                load_config(self.config)
        self.config.write_text(json.dumps(self.settings | {'preview': True}))
        with patch('podcast_video_kit.__main__.build') as build, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--config', str(self.config)]), 1)
            build.assert_not_called()
        self.assertFalse((self.root / 'runs').exists())

    def test_duplicate_and_non_json_numbers_are_rejected(self):
        for raw, message in (('{"output":"a","output":"b"}', 'Duplicate key'),
                             ('{"preview":NaN}', 'Invalid JSON number')):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, message):
                self.config.write_text(raw)
                load_config(self.config)

    def test_manifest_keeps_exact_preview_boundary(self):
        self.config.write_text(json.dumps(self.settings)[:-1] +
                               ', "preview": 1, "preview_start": 1.039999999999999999}')
        args, _ = load_config(self.config)
        self.assertEqual(_render_window(args, Fraction('1.04')), (24, 25, Fraction(1), Fraction('1.04')))

    def test_old_flags_and_multiple_manifests_are_rejected(self):
        for flags, message in ((['--script', 'script.docx'], 'Move episode flags into episode.json'),
                               (['--config', 'a.json', '--output', 'run'], 'Move episode flags into episode.json'),
                               (['--config', 'a.json', '--config', 'b.json'], 'exactly one --config')):
            with self.subTest(flags=flags), contextlib.redirect_stderr(io.StringIO()) as error:
                with self.assertRaises(SystemExit) as raised:
                    main(flags)
                self.assertEqual(raised.exception.code, 2)
                self.assertIn(message, error.getvalue())

    def test_existing_output_symlink_is_not_followed_or_overwritten(self):
        self.settings.update(output='run', plan_only=True)
        self.load()
        destination = self.root / 'missing'
        (self.root / 'run').symlink_to(destination, target_is_directory=True)
        with patch('podcast_video_kit.__main__.duration_wav', return_value=1), \
                patch('podcast_video_kit.__main__.transcribe') as transcribe, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--config', str(self.config)]), 1)
            transcribe.assert_not_called()
        self.assertTrue((self.root / 'run').is_symlink())
        self.assertFalse(destination.exists())
