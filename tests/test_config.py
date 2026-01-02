import os
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import importlib


class TestDotenvLoader(unittest.TestCase):
    def test_load_dotenv_file(self):
        # Create a temporary .env file in repo root
        repo = Path(__file__).resolve().parents[1]
        env_path = repo / '.env'
        content = 'TEST_FOO=bar\nTEST_QUOTE="baz"\n#comment\n'
        env_path.write_text(content)
        try:
            # Reload config module to trigger load_dotenv
            if 'bot.config' in sys.modules:
                importlib.reload(sys.modules['bot.config'])
            else:
                importlib.import_module('bot.config')
            import bot.config as cfg
            self.assertEqual(os.getenv('TEST_FOO'), 'bar')
            self.assertEqual(os.getenv('TEST_QUOTE'), 'baz')
        finally:
            try:
                env_path.unlink()
            except Exception:
                pass


if __name__ == '__main__':
    unittest.main()
