import unittest

from rdpflow.models import Connection, parse_endpoint


class EndpointTests(unittest.TestCase):
    def test_parses_rdp_scheme_and_custom_port(self):
        self.assertEqual(parse_endpoint("rdp://desktop.example:3390"), ("desktop.example", 3390))

    def test_parses_bracketed_ipv6(self):
        self.assertEqual(parse_endpoint("[2001:db8::1]:3389"), ("2001:db8::1", 3389))

    def test_rejects_invalid_port(self):
        with self.assertRaises(ValueError):
            parse_endpoint("desktop.example:70000")


class ConnectionTests(unittest.TestCase):
    def test_password_is_not_serialized(self):
        profile = Connection(host="desktop.example", password="secret")
        data = profile.to_dict()
        self.assertNotIn("password", data)
        self.assertNotIn("secret", str(data))

    def test_round_trip_preserves_connection_fields(self):
        profile = Connection(
            name="Office",
            host="desktop.example",
            port=3390,
            username="alice",
            domain="EXAMPLE",
            quality="compatibility",
            shared_folder="/tmp",
        )
        restored = Connection.from_dict(profile.to_dict())
        self.assertEqual(restored.to_dict(), profile.to_dict())

    def test_empty_host_is_invalid(self):
        profile = Connection()
        self.assertIn("host", profile.validate())

    def test_endpoint_formats_ipv6(self):
        profile = Connection(host="[2001:db8::2]:3390")
        self.assertEqual(profile.endpoint, "[2001:db8::2]:3390")


if __name__ == "__main__":
    unittest.main()
