import unittest

from rdpflow.layout import dialog_height, dialog_width, fit_to_screen, window_default_size, window_min_size


class FitToScreenTests(unittest.TestCase):
    """默认尺寸必须跟着屏幕走：1366×768 的笔记本上 680×760 的对话框会直接出界。"""

    def test_no_screen_keeps_preferred(self):
        self.assertEqual(fit_to_screen((680, 760), None), (680, 760))

    def test_small_screen_shrinks_to_usage_ratio(self):
        self.assertEqual(fit_to_screen((680, 760), (1366, 768)), (680, 706))

    def test_big_screen_keeps_preferred(self):
        self.assertEqual(fit_to_screen((680, 760), (3840, 2160)), (680, 760))

    def test_floor_wins_over_hairline_screen(self):
        self.assertEqual(fit_to_screen((680, 760), (640, 480), floor=(360, 240)), (588, 441))


class WindowSizeTests(unittest.TestCase):
    def test_window_grows_with_a_1080p_screen(self):
        width, height = window_default_size((1920, 1080), 1)
        # 1180×780 只占 1080p 屏幕的 44%，内容被压得又密又小。
        self.assertGreater(width, 1180)
        self.assertGreater(height, 780)
        self.assertLessEqual(width, int(1920 * 0.92))
        self.assertLessEqual(height, int(1080 * 0.92))

    def test_window_never_exceeds_small_screen(self):
        width, height = window_default_size((1024, 600), 1)
        self.assertLessEqual(width, int(1024 * 0.92))
        self.assertLessEqual(height, int(600 * 0.92))

    def test_minimum_size_stays_inside_tiny_screen(self):
        width, height = window_min_size((800, 600), 1)
        self.assertLessEqual(width, 800)
        self.assertLessEqual(height, 600)
        self.assertGreaterEqual(width, 560)

    def test_missing_screen_gives_regular_sizes(self):
        self.assertEqual(window_default_size(None), (1180, 780))
        self.assertEqual(window_min_size(None), (860, 620))


class DialogSizeTests(unittest.TestCase):
    def test_dialog_helpers_return_even_in_headless_run(self):
        # 无显示器时也要给出可用尺寸，绝不能返回 0 或抛异常。
        self.assertGreaterEqual(dialog_width(680), 360)
        self.assertGreaterEqual(dialog_height(760), 240)


if __name__ == "__main__":
    unittest.main()
