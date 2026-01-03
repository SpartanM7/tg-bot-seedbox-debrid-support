import unittest
import os
import shutil
from bot.state import JsonFileState

class TestJsonState(unittest.TestCase):
    def setUp(self):
        self.filename = "test_state.tmp.json"
        if os.path.exists(self.filename):
            os.remove(self.filename)
        self.state = JsonFileState(self.filename)

    def tearDown(self):
        if os.path.exists(self.filename):
            os.remove(self.filename)

    def test_seen_logic(self):
        url = "http://feed.com"
        self.assertFalse(self.state.is_seen(url, "123"))
        self.state.add_seen(url, "123")
        self.assertTrue(self.state.is_seen(url, "123"))
        
        # reload
        new_state = JsonFileState(self.filename)
        self.assertTrue(new_state.is_seen(url, "123"))

    def test_job_logic(self):
        jid = "job1"
        data = {"status": "ok"}
        self.state.set_job(jid, data)
        self.assertEqual(self.state.get_job(jid), data)
        
        new_state = JsonFileState(self.filename)
        self.assertEqual(new_state.get_job(jid), data)

if __name__ == '__main__':
    unittest.main()
