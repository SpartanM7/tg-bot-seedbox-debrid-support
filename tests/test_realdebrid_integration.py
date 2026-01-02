import os
import sys
import unittest
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bot.clients.realdebrid import RDClient, RealDebridNotConfigured


class TestRDIntegration(unittest.TestCase):
    @unittest.skipUnless(os.getenv('RD_ACCESS_TOKEN_TEST'), 'RD_ACCESS_TOKEN_TEST not set')
    def test_auth_and_list(self):
        token = os.getenv('RD_ACCESS_TOKEN_TEST')
        c = RDClient(access_token=token)
        # This test performs a non-destructive call to list torrents (may be empty)
        items = c.list_torrents()
        self.assertIsInstance(items, list)


if __name__ == '__main__':
    unittest.main()
