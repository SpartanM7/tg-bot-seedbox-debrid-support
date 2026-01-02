import os
import sys
import unittest
from unittest.mock import patch, Mock
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bot.clients.realdebrid import RDClient, RealDebridNotConfigured, RDAPIError


class TestRDClient(unittest.TestCase):
    def test_no_token_raises(self):
        old = os.environ.pop('RD_ACCESS_TOKEN', None)
        try:
            with self.assertRaises(RealDebridNotConfigured):
                RDClient()
        finally:
            if old is not None:
                os.environ['RD_ACCESS_TOKEN'] = old

    @patch('bot.clients.realdebrid.requests.request')
    def test_is_cached_true(self, mock_request):
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"abcdef123": {"instant": True}}
        mock_resp.text = 'x'
        mock_request.return_value = mock_resp
        c = RDClient(access_token='x')
        self.assertTrue(c.is_cached('magnet:?xt=urn:btih:abcdef'))

    @patch('bot.clients.realdebrid.requests.request')
    def test_add_magnet_calls_api(self, mock_request):
        mock_resp = Mock()
        mock_resp.status_code = 200
        mock_resp.ok = True
        mock_resp.json.return_value = {"id": "123"}
        mock_resp.text = 'x'
        mock_request.return_value = mock_resp
        c = RDClient(access_token='x')
        r = c.add_magnet('magnet:?xt=urn:btih:abc')
        self.assertEqual(r.get('id'), '123')

    @patch('bot.clients.realdebrid.requests.request')
    def test_delete_returns_true(self, mock_request):
        mock_resp = Mock()
        mock_resp.status_code = 204
        mock_resp.ok = True
        mock_resp.text = ''
        mock_request.return_value = mock_resp
        c = RDClient(access_token='x')
        self.assertTrue(c.delete_torrent('123'))


if __name__ == '__main__':
    unittest.main()
