import unittest

from rdpflow.models import (
    EXPERIENCE_DEFAULTS,
    RESOLUTION_AUTO,
    WINDOW_FIT_CLIENT,
    WINDOW_FIT_OFF,
    WINDOW_FIT_SERVER,
    WINDOW_FITS,
    Connection,
    apply_experience_options,
    canvas_for_screen,
    desktop_scale_percent,
    parse_endpoint,
    resolve_canvas,
    resolve_desktop_scale,
)


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


class ExperienceDefaultsTests(unittest.TestCase):
    def test_new_connection_uses_shipped_defaults(self):
        profile = Connection(host="desktop.example")
        for field_name, expected in EXPERIENCE_DEFAULTS.items():
            self.assertEqual(getattr(profile, field_name), expected, field_name)

    def test_with_defaults_applies_custom_defaults(self):
        profile = Connection.with_defaults(
            {"quality": "performance", "clipboard": False},
            host="desktop.example",
            username="alice",
        )
        self.assertEqual(profile.quality, "performance")
        self.assertFalse(profile.clipboard)
        self.assertEqual(profile.username, "alice")

    def test_invalid_defaults_fall_back_to_shipped_values(self):
        resolved = apply_experience_options({"quality": "nonsense", "display_mode": "nope"})
        self.assertEqual(resolved["quality"], EXPERIENCE_DEFAULTS["quality"])
        self.assertEqual(resolved["display_mode"], EXPERIENCE_DEFAULTS["display_mode"])

    def test_default_window_fit_is_client_scaling(self):
        """出厂默认是客户端缩放：只有它不依赖服务端兑现。"""
        profile = Connection(host="desktop.example")
        self.assertEqual(profile.window_fit, WINDOW_FIT_CLIENT)

    def test_window_fit_is_a_single_three_state_value(self):
        """互斥关系由结构保证：只有一个字段，不可能同时取两个值。"""
        self.assertEqual(WINDOW_FITS, (WINDOW_FIT_CLIENT, WINDOW_FIT_SERVER, WINDOW_FIT_OFF))
        for value in WINDOW_FITS:
            self.assertEqual(apply_experience_options({"window_fit": value})["window_fit"], value)

    def test_invalid_window_fit_falls_back_to_the_default(self):
        self.assertEqual(
            apply_experience_options({"window_fit": "both"})["window_fit"], WINDOW_FIT_CLIENT
        )
        self.assertEqual(
            apply_experience_options({"window_fit": None})["window_fit"], WINDOW_FIT_CLIENT
        )

    def test_set_experience_option_keeps_non_boolean_values(self):
        profile = Connection(host="desktop.example")
        profile.set_experience_option("resolution", "2560x1440")
        self.assertEqual(profile.resolution, "2560x1440")
        profile.set_experience_option("quality", "quality")
        self.assertEqual(profile.quality, "quality")

    def test_set_experience_option_writes_window_fit(self):
        profile = Connection(host="desktop.example")
        profile.set_experience_option("window_fit", WINDOW_FIT_SERVER)
        self.assertEqual(profile.window_fit, WINDOW_FIT_SERVER)
        profile.set_experience_option("window_fit", "nonsense")
        self.assertEqual(profile.window_fit, WINDOW_FIT_CLIENT)

    def test_apply_defaults_overwrites_experience_fields(self):
        profile = Connection(host="desktop.example", quality="quality", clipboard=False)
        profile.apply_defaults({"quality": "performance"})
        self.assertEqual(profile.quality, "performance")
        self.assertTrue(profile.clipboard)


class AdaptiveCanvasTests(unittest.TestCase):
    """默认画布必须跟着本机屏幕走 —— 硬编码 1080p 就是"看着特别小"的根源。"""

    def test_default_resolution_follows_screen(self):
        profile = Connection(host="desktop.example")
        self.assertEqual(profile.resolution, RESOLUTION_AUTO)
        self.assertEqual(profile.canvas((1920, 1080), 1), canvas_for_screen((1920, 1080), 1))
        width, height = profile.canvas((2560, 1440), 1)
        self.assertEqual((width, height), (2536, 1344))
        self.assertIn("自动", profile.canvas_label((2560, 1440), 1))

    def test_explicit_resolution_ignores_screen(self):
        profile = Connection(host="desktop.example", resolution="2560x1440")
        self.assertEqual(resolve_canvas(profile, (1366, 768), 1), (2560, 1440))
        self.assertEqual(profile.canvas_label((1366, 768), 1), "2560×1440")

    def test_hidpi_screen_scales_canvas_to_physical_pixels(self):
        self.assertEqual(canvas_for_screen((1920, 1080), 2), (3792, 1968))

    def test_fullscreen_keeps_full_screen(self):
        self.assertEqual(canvas_for_screen((1920, 1080), 1, "fullscreen"), (1920, 1080))

    def test_missing_screen_falls_back(self):
        width, height = canvas_for_screen(None)
        self.assertGreaterEqual(width, 1024)
        self.assertGreaterEqual(height, 640)
        self.assertEqual(Connection(host="h").width, width)

    def test_auto_desktop_scale_follows_hidpi(self):
        self.assertIsNone(resolve_desktop_scale("auto", 1))
        self.assertEqual(resolve_desktop_scale("auto", 2), 200)
        self.assertEqual(resolve_desktop_scale("125", 2), 125)
        self.assertIsNone(desktop_scale_percent("nonsense"))


if __name__ == "__main__":
    unittest.main()
