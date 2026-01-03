
import unittest
from unittest.mock import Mock, patch, MagicMock
from bot.telegram import rd_torrent_gdrive, sb_torrent_gdrive, ytdl_gdrive

class DummyMessage:
    def __init__(self):
        self.chat = Mock()
        self.chat.id = 123
        self.reply_text = Mock()
        self.effective_chat = Mock()
        self.effective_chat.id = 123

class TestGDriveCommands(unittest.TestCase):
    def setUp(self):
        self.update = Mock()
        self.update.message = DummyMessage()
        self.update.effective_chat.id = 123
        self.context = Mock()
        self.context.args = []

    @patch('bot.telegram.rd_client')
    @patch('bot.telegram.get_state')
    def test_rd_torrent_gdrive(self, mock_get_state, mock_rd):
        self.context.args = ['magnet:?xt=urn:btih:TEST']
        mock_rd.add_magnet.return_value = {'id': 't1'}
        mock_state = Mock()
        mock_get_state.return_value = mock_state

        rd_torrent_gdrive(self.update, self.context)

        # Verify added to RD
        mock_rd.add_magnet.assert_called_once()
        # Verify intent set
        mock_state.set_intent.assert_called_with('rd_t1', 'gdrive')
        # Verify reply
        self.update.message.reply_text.assert_called()
        args, _ = self.update.message.reply_text.call_args
        self.assertIn("Dest: GDrive", args[0])

    @patch('bot.telegram.sb_client')
    @patch('bot.telegram.get_state')
    def test_sb_torrent_gdrive(self, mock_get_state, mock_sb):
        magnet = 'magnet:?xt=urn:btih:ABC123HASH&dn=test'
        self.context.args = [magnet]
        mock_state = Mock()
        mock_get_state.return_value = mock_state

        sb_torrent_gdrive(self.update, self.context)

        # Verify added to SB
        mock_sb.add_torrent.assert_called_with(magnet)
        # Verify intent set with extracted hash
        mock_state.set_intent.assert_called_with('sb_ABC123HASH', 'gdrive')

    @patch('bot.telegram.enqueue_ytdl')
    def test_ytdl_gdrive(self, mock_enqueue):
        self.context.args = ['http://youtube.com/watch?v=123']
        mock_enqueue.return_value = 'job123'

        ytdl_gdrive(self.update, self.context)

        # Verify enqueue with dest='gdrive'
        mock_enqueue.assert_called_with('http://youtube.com/watch?v=123', dest='gdrive', chat_id=123)
