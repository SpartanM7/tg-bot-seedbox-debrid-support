import os
import sys
import unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bot.clients import realdebrid, seedbox


class TestClients(unittest.TestCase):
    def test_real_debrid_not_configured(self):
        # Ensure that constructing RDClient without env var raises the expected error.
        old = os.environ.pop('RD_ACCESS_TOKEN', None)
        try:
            with self.assertRaises(realdebrid.RealDebridNotConfigured):
                realdebrid.RDClient()
        finally:
            if old is not None:
                os.environ['RD_ACCESS_TOKEN'] = old

    def test_seedbox_not_configured(self):
        old_url = os.environ.pop('RUTORRENT_URL', None)
        old_user = os.environ.pop('RUTORRENT_USER', None)
        old_pass = os.environ.pop('RUTORRENT_PASS', None)
        try:
            with self.assertRaises(seedbox.SeedboxNotConfigured):
                seedbox.SeedboxClient()
        finally:
            if old_url: os.environ['RUTORRENT_URL'] = old_url
            if old_user: os.environ['RUTORRENT_USER'] = old_user
            if old_pass: os.environ['RUTORRENT_PASS'] = old_pass


if __name__ == '__main__':
    unittest.main()
