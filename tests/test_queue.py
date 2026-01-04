import os
import sys
import unittest
from unittest.mock import patch, MagicMock
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from bot.storage_queue import JobQueue, Lock


class TestQueueLocal(unittest.TestCase):
    def test_enqueue_and_get_local(self):
        q = JobQueue()
        jid = 'j1'
        q.enqueue(jid, {'url': 'x', 'status': 'queued'})
        rec = q.get(jid)
        self.assertEqual(rec['url'], 'x')

    def test_lock_local(self):
        l = Lock('t', timeout=1)
        ok = l.acquire()
        self.assertTrue(ok)
        l.release()


if __name__ == '__main__':
    unittest.main()
