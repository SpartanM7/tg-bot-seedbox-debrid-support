import unittest
from unittest.mock import Mock, patch
from bot.monitor import Monitor

class TestMonitor(unittest.TestCase):
    def setUp(self):
        self.downloader = Mock()
        self.rd = Mock()
        self.sb = Mock()
        self.monitor = Monitor(self.downloader, self.rd, self.sb)
        # Mock state to avoid real FS
        self.monitor.state = Mock()
        self.monitor.state.is_processed.return_value = False
        self.monitor.state.get_intent.return_value = None

    def test_check_realdebrid_downloaded(self):
        # Setup RD mock
        self.rd.list_torrents.return_value = [{'id': 't1', 'status': 'downloaded', 'filename': 'video.mp4'}]
        self.rd.get_torrent_info.return_value = {'links': ['http://host/file']}
        self.rd.unrestrict_link.return_value = {'download': 'http://dl/video.mp4', 'filename': 'video.mp4'}

        self.monitor.check_realdebrid()

        # Check interaction
        self.rd.unrestrict_link.assert_called_with('http://host/file')
        self.downloader.process_item.assert_called_with('http://dl/video.mp4', 'video.mp4', dest='telegram', chat_id=None)
        self.monitor.state.add_processed.assert_called_with('rd_t1')

    def test_check_seedbox_finished(self):
        # Setup Seedbox mock
        self.sb.list_torrents.return_value = [{'name': 'linux.iso', 'hash': 'h1', 'size': 100, 'bytes_done': 100, 'base_path': '/home/user/linux.iso'}]
        
        self.monitor.check_seedbox()

        self.downloader.process_item.assert_called_with('sftp:///home/user/linux.iso', 'linux.iso', dest='telegram', chat_id=None)
        self.monitor.state.add_processed.assert_called_with('sb_h1')

    def test_check_seedbox_gdrive_intent(self):
        # Setup Seedbox mock with GDrive intent
        self.sb.list_torrents.return_value = [{'name': 'linux.iso', 'hash': 'h1', 'size': 100, 'bytes_done': 100, 'base_path': '/home/user/linux.iso'}]
        self.monitor.state.get_intent.return_value = 'gdrive'
        
        self.monitor.check_seedbox()

        self.downloader.process_item.assert_called_with('sftp:///home/user/linux.iso', 'linux.iso', dest='gdrive', chat_id=None)
        self.monitor.state.add_processed.assert_called_with('sb_h1')

    def test_check_seedbox_incomplete_ignored(self):
        self.sb.list_torrents.return_value = [{'name': 'linux.iso', 'hash': 'h1', 'size': 100, 'bytes_done': 50, 'base_path': '/home/user/linux.iso'}]
        self.monitor.check_seedbox()
        self.downloader.process_item.assert_not_called()

if __name__ == '__main__':
    unittest.main()
