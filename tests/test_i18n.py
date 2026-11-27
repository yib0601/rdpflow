"""界面语言：解析规则、译文覆盖、.mo 与源码一致性。

这个文件的存在理由：文案散在 7 个模块里，靠人眼保证「新增的界面字符串都包了 `_()`」
是不现实的。这里用 AST 扫全包，把三件事钉成回归项：

1. 源码里不许有未包裹的中文字面量（new 的界面文案不会被静默漏翻）；
2. po/en.po 覆盖源码里每一条 `_()` 原文（翻译不会悄悄过期）；
3. 编译进包的 .mo 与 po/en.po 内容一致（打包时没漏跑 build-locales）。
"""

import ast
import importlib.util
import pathlib
import unittest

from rdpflow import i18n

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "rdpflow"


def load_build_locales():
    """把 scripts/build-locales.py 当模块加载：它的取词与编译逻辑就是被测对象。"""
    path = ROOT / "scripts" / "build-locales.py"
    spec = importlib.util.spec_from_file_location("build_locales", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def cjk_strings(path: pathlib.Path) -> list[tuple[int, str]]:
    """源码里所有含中文、且没有被 `_()` 包住的字符串字面量。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            body = getattr(node, "body", [])
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                docstrings.add(id(body[0].value))

    wrapped: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_":
            for argument in node.args:
                wrapped.add(id(argument))

    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in docstrings or id(node) in wrapped:
            continue
        if any("\u4e00" <= character <= "\u9fff" for character in node.value):
            found.append((node.lineno, node.value))
    return found


class LanguageResolutionTests(unittest.TestCase):
    def test_override_wins_over_every_locale_variable(self):
        with self.override({"RDPFLOW_LANG": "en_US.UTF-8", "LANGUAGE": "zh_CN", "LANG": "zh_CN.UTF-8"}):
            self.assertEqual(i18n.resolve_language(), "en")

    def test_override_is_authoritative_even_when_unrecognised(self):
        # 设了覆盖变量却写成认不出的值：回到源语言，不偷偷读系统 locale。
        with self.override({"RDPFLOW_LANG": "tlh", "LANG": "en_US.UTF-8"}):
            self.assertEqual(i18n.resolve_language(), i18n.SOURCE_LANGUAGE)

    def test_language_list_is_honoured(self):
        with self.override({"RDPFLOW_LANG": "", "LANGUAGE": "en_US:zh_CN.UTF-8"}):
            self.assertEqual(i18n.resolve_language(), "en")

    def test_traditional_chinese_falls_back_to_the_source_text(self):
        # 源文就是简体中文，zh_TW 吃原文而不是显示英文。
        with self.override({"RDPFLOW_LANG": "", "LANG": "zh_TW.UTF-8"}):
            self.assertEqual(i18n.resolve_language(), "zh_CN")

    def test_unknown_locale_falls_back_to_the_source_language(self):
        with self.override({"RDPFLOW_LANG": "", "LANG": "fr_FR.UTF-8"}):
            self.assertEqual(i18n.resolve_language(), i18n.SOURCE_LANGUAGE)

    def test_missing_catalog_degrades_to_the_source_text(self):
        # 源码树没编译过 .mo 时界面必须照常可用，只是仍是中文。
        with self.override({"RDPFLOW_LANG": "en", "RDPFLOW_LOCALE_DIR": "/nonexistent"}):
            table = i18n.translation("en")
            self.assertEqual(table.gettext("快速连接"), "快速连接")

    def override(self, values: dict[str, str]):
        return _Environment(values)


class _Environment:
    """临时改写 locale 相关环境变量。"""

    def __init__(self, values: dict[str, str]) -> None:
        import os

        self.os = os
        self.values = values
        self.saved: dict[str, str | None] = {}

    def __enter__(self) -> None:
        for name, value in self.values.items():
            self.saved[name] = self.os.environ.get(name)
            if value:
                self.os.environ[name] = value
            else:
                self.os.environ.pop(name, None)

    def __exit__(self, *_exc: object) -> None:
        for name, value in self.saved.items():
            if value is None:
                self.os.environ.pop(name, None)
            else:
                self.os.environ[name] = value


class TranslationCoverageTests(unittest.TestCase):
    """三条门禁：都包了 `_()`、都有译文、.mo 与 .po 一致。"""

    def test_every_visible_chinese_literal_is_wrapped(self):
        offenders: list[str] = []
        for path in sorted(PACKAGE.rglob("*.py")):
            for line, text in cjk_strings(path):
                offenders.append(f"{path.relative_to(ROOT)}:{line}: {text[:50]}")
        self.assertEqual(
            offenders,
            [],
            "这些中文字面量没有被 _() 包裹，界面切到英文时不会翻译：\n" + "\n".join(offenders),
        )

    def test_english_catalog_covers_every_extracted_string(self):
        module = load_build_locales()
        messages = module.collect_messages()
        entries, incomplete = module.read_po(ROOT / "po" / "en.po")
        missing = sorted(set(messages) - set(entries))
        self.assertEqual(missing, [], f"po/en.po 缺这些译文：{missing[:5]}")
        self.assertFalse(incomplete, "po/en.po 里有 msgstr 为空的条目")

    def test_compiled_catalog_matches_the_po_file(self):
        module = load_build_locales()
        entries, _ = module.read_po(ROOT / "po" / "en.po")
        compiled = module.mo_path("en")
        self.assertTrue(compiled.is_file(), "先跑 scripts/build-locales.py 生成 .mo")
        self.assertEqual(compiled.read_bytes(), module.compile_mo(entries, "en"))

    def test_english_catalog_really_translates(self):
        catalog = i18n.translation("en")
        self.assertEqual(catalog.gettext("快速连接"), "Quick connect")
        # 中文源语言不查表，原文返回。
        self.assertEqual(i18n.translation("zh_CN").gettext("快速连接"), "快速连接")

    def test_format_placeholders_survive_translation(self):
        """译文里的 {placeholder} 必须与原文一一对应，否则 .format() 会炸。"""
        import re

        module = load_build_locales()
        entries, _ = module.read_po(ROOT / "po" / "en.po")
        pattern = re.compile(r"\{(\w+)\}")
        for msgid, translated in entries.items():
            self.assertEqual(
                set(pattern.findall(msgid)),
                set(pattern.findall(translated)),
                f"占位符不一致：{msgid!r} → {translated!r}",
            )


if __name__ == "__main__":
    unittest.main()
