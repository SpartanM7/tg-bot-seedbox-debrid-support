import os
import sys
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bot import telegram


class DummyMessage:
    def __init__(self):
        self._texts = []

    def reply_text(self, text, **kwargs):
        self._texts.append(text)


class DummyUpdate:
    def __init__(self):
        self.message = DummyMessage()
        self.effective_chat = Mock()
        self.effective_chat.id = 123


class DummyContext:
    def __init__(self, args=None):
        self.args = args or []


class TestTelegramHandlers(unittest.TestCase):
    def test_start(self):
        u = DummyUpdate()
        c = DummyContext()
        telegram.start(u, c)
        self.assertIn('WZML-X v1', u.message._texts[0])

    def test_rd_torrent_usage(self):
        u = DummyUpdate()
        c = DummyContext(args=[])
        # Patch rd_client to ensure we reach usage check
        original_client = telegram.rd_client
        telegram.rd_client = Mock()
        try:
            telegram.rd_torrent(u, c)
            self.assertIn('Usage', u.message._texts[0])
        finally:
            telegram.rd_client = original_client

    @patch('bot.telegram.enqueue_ytdl')
    def test_ytdl_queue(self, mock_enqueue):
        mock_enqueue.return_value = 'job-123'
        u = DummyUpdate()
        c = DummyContext(args=['http://example.com/video'])
        # Ensure job runner is present
        try:
            from bot.jobs import enqueue_ytdl
        except Exception:
            self.skipTest('jobs not available')
        telegram.ytdl(u, c)
        mock_enqueue.assert_called_once()
        self.assertTrue(any('Job queued' in t for t in u.message._texts))


if __name__ == '__main__':
    unittest.main()
