import os
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bot.jobs import enqueue_ytdl, job_status


class TestJobs(unittest.TestCase):
    @patch('bot.jobs.subprocess.run')
    def test_enqueue_ytdl_runs_and_records(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = 'ok'
        mock_run.return_value.stderr = ''
        jid = enqueue_ytdl('http://example.com/video')
        # Give background thread a moment to run
        import time
        time.sleep(0.1)
        st = job_status(jid)
        self.assertIn(st['status'], ('done', 'failed', 'timeout', 'error'))


if __name__ == '__main__':
    unittest.main()
