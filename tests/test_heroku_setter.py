import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts import heroku_config_setter as setter


class TestHerokuSetter(unittest.TestCase):
    def test_parse_env_file(self):
        tmp = Path(__file__).resolve().parents[1] / '.env.test'
        tmp.write_text('A=1\nB=\n#comment\nC="3"\n')
        try:
            d = setter.parse_env_file(tmp)
            self.assertEqual(d, {'A': '1', 'C': '3'})
        finally:
            tmp.unlink()

    @patch('subprocess.run')
    def test_set_heroku_config_dry_run(self, mock_run):
        pairs = {'A': '1', 'B': '2'}
        count, results = setter.set_heroku_config('myapp', pairs, dry_run=True)
        self.assertEqual(count, 2)
        self.assertTrue(all(r[1] for r in results))

    @patch('subprocess.run')
    def test_set_heroku_config_exec(self, mock_run):
        mock = MagicMock()
        mock.returncode = 0
        mock.stdout = 'Config vars set'
        mock.stderr = ''
        mock_run.return_value = mock
        pairs = {'A': '1'}
        count, results = setter.set_heroku_config('myapp', pairs, dry_run=False)
        self.assertEqual(count, 1)
        self.assertTrue(results[0][1])


if __name__ == '__main__':
    unittest.main()
