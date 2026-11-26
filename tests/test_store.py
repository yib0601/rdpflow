import json
import stat
import tempfile
import unittest
from pathlib import Path

from rdpflow.models import Connection
from rdpflow.store import ConnectionStore


class ConnectionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "rdpflow" / "connections.json"
        self.store = ConnectionStore(self.path)

    def tearDown(self):
        self.temporary.cleanup()

    def test_save_and_load(self):
        profile = Connection(name="Office", host="192.0.2.10", username="alice")
        self.store.save([profile])
        loaded = self.store.load()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].to_dict(), profile.to_dict())

    def test_file_permissions_are_private(self):
        self.store.save([Connection(host="192.0.2.10")])
        mode = stat.S_IMODE(self.path.stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_corrupt_file_is_backed_up(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            self.store.load()
        backups = list(self.path.parent.glob("connections.json.corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "{broken")
        self.assertFalse(self.path.exists())

    def test_saved_json_contains_no_password_field(self):
        profile = Connection(host="192.0.2.10", password="secret")
        self.store.save([profile])
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertNotIn("password", payload["connections"][0])


if __name__ == "__main__":
    unittest.main()
