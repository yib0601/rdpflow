import json
import stat
import tempfile
import unittest
from pathlib import Path

from rdpflow.models import Connection, default_experience_options
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

    def test_defaults_round_trip(self):
        self.store.set_defaults({"quality": "performance", "clipboard": False})
        self.store.save([Connection(host="192.0.2.10")])
        reloaded = ConnectionStore(self.path)
        reloaded.load()
        self.assertEqual(reloaded.defaults["quality"], "performance")
        self.assertFalse(reloaded.defaults["clipboard"])

    def test_missing_defaults_fall_back_to_shipped_values(self):
        self.path.parent.mkdir(parents=True)
        self.path.write_text(
            json.dumps({"version": 1, "connections": []}), encoding="utf-8"
        )
        self.store.load()
        self.assertEqual(self.store.defaults, default_experience_options())

    def test_reset_defaults_restores_shipped_values(self):
        self.store.set_defaults({"auto_reconnect": False})
        self.store.reset_defaults()
        self.assertEqual(self.store.defaults, default_experience_options())


class MigrationTests(unittest.TestCase):
    """老配置里的 1920x1080 是当年硬编码的出厂默认，必须升级成"自动"。"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "rdpflow" / "connections.json"
        self.path.parent.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def write_document(self, document):
        self.path.write_text(json.dumps(document), encoding="utf-8")

    def test_legacy_default_resolution_becomes_auto(self):
        self.write_document(
            {
                "version": 1,
                "connections": [
                    {"name": "旧连接", "host": "192.0.2.10", "resolution": "1920x1080"},
                    {"name": "手选", "host": "192.0.2.11", "resolution": "2560x1440"},
                ],
            }
        )
        store = ConnectionStore(self.path)
        connections = store.load()
        self.assertTrue(store.migrated)
        self.assertEqual(connections[0].resolution, "auto")
        self.assertEqual(connections[1].resolution, "2560x1440")

    def test_legacy_defaults_block_is_migrated_too(self):
        self.write_document(
            {
                "version": 1,
                "experience_defaults": {"resolution": "1920x1080"},
                "connections": [],
            }
        )
        store = ConnectionStore(self.path)
        store.load()
        self.assertEqual(store.defaults["resolution"], "auto")

    def test_migrated_document_is_written_back_as_current_version(self):
        self.write_document(
            {"version": 1, "connections": [{"name": "旧", "host": "192.0.2.10"}]}
        )
        store = ConnectionStore(self.path)
        store.save(store.load())
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["version"], 2)

    def test_current_version_is_untouched(self):
        self.write_document(
            {
                "version": 2,
                "connections": [{"name": "新", "host": "192.0.2.10", "resolution": "1920x1080"}],
            }
        )
        store = ConnectionStore(self.path)
        connections = store.load()
        self.assertFalse(store.migrated)
        self.assertEqual(connections[0].resolution, "1920x1080")

    def test_unknown_version_is_still_rejected(self):
        self.write_document({"version": 99, "connections": []})
        with self.assertRaises(RuntimeError):
            ConnectionStore(self.path).load()


if __name__ == "__main__":
    unittest.main()
