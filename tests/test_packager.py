import os
import sys
import shutil
import tempfile
import unittest
# Ensure project root is on sys.path so `bot` package can be imported when tests
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from bot.utils import packager


class TestPackager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)
        # Ensure any global locks are released for tests that may have left them
        try:
            from bot.queue import Lock
            l = Lock('packager:lock')
            l.release()
        except Exception:
            pass

    def _make_folder_with_files(self, name, file_count=3, file_size=1024):
        path = os.path.join(self.tmpdir, name)
        os.makedirs(path, exist_ok=True)
        for i in range(file_count):
            with open(os.path.join(path, f"f{i}.bin"), "wb") as f:
                f.write(b"0" * file_size)
        return path

    def test_should_zip_true(self):
        self.assertTrue(packager.should_zip("my_pics"))
        self.assertTrue(packager.should_zip("IMAGE_folder"))

    def test_zip_folder_creates_zip(self):
        folder = self._make_folder_with_files("pics_example", file_count=2, file_size=512)
        zip_path = packager.zip_folder(folder)
        self.assertTrue(os.path.exists(zip_path))
        self.assertTrue(zip_path.endswith('.zip'))

    def test_prepare_skips_large_for_telegram(self):
        # set small limit
        original = packager.MAX_ZIP_SIZE_BYTES
        packager.MAX_ZIP_SIZE_BYTES = 1024  # 1KB
        try:
            folder = self._make_folder_with_files("pics_big", file_count=4, file_size=512)
            results = packager.prepare(self.tmpdir, dest="telegram")
            rec = next(r for r in results if r['name'] == 'pics_big')
            self.assertTrue(rec['skipped'])
            self.assertIn('too large', rec['reason'])
        finally:
            packager.MAX_ZIP_SIZE_BYTES = original

    def test_prepare_zips_for_gdrive_even_if_large(self):
        original = packager.MAX_ZIP_SIZE_BYTES
        packager.MAX_ZIP_SIZE_BYTES = 1024  # 1KB
        try:
            folder = self._make_folder_with_files("pics_big2", file_count=4, file_size=512)
            results = packager.prepare(self.tmpdir, dest="gdrive")
            rec = next(r for r in results if r['name'] == 'pics_big2')
            self.assertFalse(rec['skipped'])
            self.assertTrue(rec['zipped'])
            self.assertTrue(os.path.exists(rec['zip_path']))
        finally:
            packager.MAX_ZIP_SIZE_BYTES = original


if __name__ == '__main__':
    unittest.main()
