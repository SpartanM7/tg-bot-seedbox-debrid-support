import os
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bot import telegram


class DummyMessage:
    def __init__(self):
        self._texts = []

    def reply_text(self, text):
        self._texts.append(text)


class DummyUpdate:
    def __init__(self):
        self.message = DummyMessage()


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
        telegram.rd_torrent(u, c)
        self.assertIn('Usage', u.message._texts[0])

    def test_ytdl_queue(self):
        u = DummyUpdate()
        c = DummyContext(args=['http://example.com/video'])
        # Ensure job runner is present
        try:
            from bot.jobs import enqueue_ytdl
        except Exception:
            self.skipTest('jobs not available')
        telegram.ytdl(u, c)
        self.assertTrue(any('yt-dlp job queued' in t for t in u.message._texts))


if __name__ == '__main__':
    unittest.main()
