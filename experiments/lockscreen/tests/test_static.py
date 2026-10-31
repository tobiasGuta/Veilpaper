import json
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]


class ExtensionStaticTests(unittest.TestCase):
    def test_metadata(self):
        metadata = json.loads((ROOT / 'lockscreen' / 'metadata.json').read_text())
        self.assertEqual(metadata['shell-version'], ['50'])
        self.assertEqual(metadata['session-modes'], ['user', 'unlock-dialog'])
        self.assertEqual(metadata['uuid'], 'lockscreen@veilpaper.tobiasguta')

    def test_no_auth_or_keyboard_hook(self):
        source = (ROOT / 'lockscreen' / 'extension.js').read_text()
        self.assertIn('proto._createBackground = this._createBackgroundPatch', source)
        for forbidden in ('_showPrompt =', '_ensureAuthPrompt =', 'global.stage.connect', 'KeyController('):
            self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main()
