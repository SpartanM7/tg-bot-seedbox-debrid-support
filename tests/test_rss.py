import os
import sys
import unittest
from unittest.mock import Mock
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bot.rss import FeedManager, Router, FeedConfig


class DummyRD:
    def __init__(self, cached=False):
        self.cached = cached

    def is_cached(self, link):
        return self.cached


class TestRSSRouting(unittest.TestCase):
    def test_forced_backend(self):
        rd = DummyRD(cached=False)
        r = Router(rd_client=rd)
        cfg = FeedConfig('http://x', forced_backend='rd')
        backend = r.decide(cfg, {'link': 'magnet:?xt=urn:btih:abc'})
        self.assertEqual(backend, 'rd')

    def test_private_torrent_routes_sb(self):
        rd = DummyRD(cached=True)
        r = Router(rd_client=rd)
        cfg = FeedConfig('http://x', private_torrents=True)
        backend = r.decide(cfg, {'link': 'magnet:?xt=urn:btih:abc'})
        self.assertEqual(backend, 'sb')

    def test_cached_to_rd(self):
        rd = DummyRD(cached=True)
        r = Router(rd_client=rd)
        cfg = FeedConfig('http://x')
        backend = r.decide(cfg, {'link': 'magnet:?xt=urn:btih:abc'})
        self.assertEqual(backend, 'rd')

    def test_uncached_to_sb(self):
        rd = DummyRD(cached=False)
        r = Router(rd_client=rd)
        cfg = FeedConfig('http://x')
        backend = r.decide(cfg, {'link': 'magnet:?xt=urn:btih:abc'})
        self.assertEqual(backend, 'sb')


if __name__ == '__main__':
    unittest.main()
