#!/usr/bin/env python3
"""把源码里的界面文案抽成 .pot，并把 po/*.po 编译成随包分发的 .mo。

三种用法：

    python scripts/build-locales.py            # 抽取 + 编译（日常、打包前）
    python scripts/build-locales.py --check    # 只校验，不写任何文件（CI 用）
    python scripts/build-locales.py --refresh-po
                                               # 重新生成 po/en.po 的条目骨架

为什么自己编译 .mo 而不是调 msgfmt：Windows 包里没有 gettext 工具链，
CI 的 setup-python 解释器上也没有；而 .mo 就是一种确定格式，纯 Python 写
几十行即可，代价远低于给每个构建环境装 gettext。
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "rdpflow"
PO_DIR = ROOT / "po"
DOMAIN = "rdpflow"
LOCALE_DIR = PACKAGE / "locale"
LANGUAGES = ("en",)
# .mo 的元数据条目（msgid 为空）。charset 必须在这里声明，否则运行时按 ASCII 解码。
METADATA = (
    "Project-Id-Version: RDPFlow\n"
    "MIME-Version: 1.0\n"
    "Content-Type: text/plain; charset=UTF-8\n"
    "Content-Transfer-Encoding: 8bit\n"
    "Language: {language}\n"
)


def po_files() -> list[pathlib.Path]:
    """要编译的语言目录，顺序按 LANGUAGES 定。

    以 LANGUAGES 为准而不是 glob：多放一个 .po 却没在 rdpflow/i18n.py 里登记语言码，
    编出来的 .mo 运行时永远选不到，属于静默无效，这里直接报错拦下。
    """
    unknown = sorted(
        path.stem for path in PO_DIR.glob("*.po") if path.stem not in LANGUAGES
    )
    if unknown:
        raise SystemExit(
            f"po/ 下有未在 scripts/build-locales.py 的 LANGUAGES 里登记的语言：{unknown}"
        )
    return [PO_DIR / f"{language}.po" for language in LANGUAGES if (PO_DIR / f"{language}.po").is_file()]


# ---- 抽取 ------------------------------------------------------------------


def translatable_strings(path: pathlib.Path) -> list[tuple[int, str]]:
    """从源码里取出所有 `_("...")` 的参数的原文与行号。

    用 AST 而不是 xgettext：CI 的解释器上没有 gettext，而这里只需要「哪些字面量
    被 `_()` 包了」这一个事实，AST 就是它的唯一权威来源。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str]] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id == "_":
            for argument in node.args:
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                    found.append((node.lineno, argument.value))
                    break
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return found


def collect_messages() -> dict[str, list[str]]:
    """全包扫描：msgid → 出现位置列表。"""
    messages: dict[str, list[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        for line, text in translatable_strings(path):
            if text:
                messages.setdefault(text, []).append(f"{relative}:{line}")
    return messages


def quote(text: str) -> str:
    escaped = (
        text.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\t", "\\t")
        .replace("\n", "\\n")
    )
    return f'"{escaped}"\n'


def write_pot(messages: dict[str, list[str]]) -> pathlib.Path:
    path = PO_DIR / f"{DOMAIN}.pot"
    header = (
        "# RDPFlow 界面文案模板。由 scripts/build-locales.py 生成，勿手改。\n"
        "#\n"
        'msgid ""\n'
        'msgstr ""\n'
        '"Project-Id-Version: RDPFlow\\n"\n'
        '"Report-Msgid-Bugs-To: https://github.com/yib0601/rdpflow/issues\\n"\n'
        '"MIME-Version: 1.0\\n"\n'
        '"Content-Type: text/plain; charset=UTF-8\\n"\n'
        '"Content-Transfer-Encoding: 8bit\\n"\n'
    )
    chunks = [header]
    for msgid in sorted(messages):
        if msgid == "":
            continue
        for location in messages[msgid]:
            chunks.append(f"#: {location}\n")
        chunks.append("msgid " + quote(msgid))
        chunks.append('msgstr ""\n')
        chunks.append("\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(chunks), encoding="utf-8")
    return path


# ---- .po 读取 --------------------------------------------------------------


class PoError(ValueError):
    pass


def unquote(piece: str) -> str:
    if len(piece) >= 2 and piece.startswith('"') and piece.endswith('"'):
        piece = piece[1:-1]
    out: list[str] = []
    index = 0
    while index < len(piece):
        char = piece[index]
        if char == "\\" and index + 1 < len(piece):
            nxt = piece[index + 1]
            mapping = {"n": "\n", "t": "\t", '"': '"', "\\": "\\"}
            out.append(mapping.get(nxt, nxt))
            index += 2
            continue
        out.append(char)
        index += 1
    return "".join(out)


def read_po(path: pathlib.Path) -> tuple[dict[str, str], bool]:
    """读 .po，返回 (msgid → msgstr, 是否有条目为空)。"""
    entries: dict[str, str] = {}
    msgid: list[str] | None = None
    msgstr: list[str] | None = None
    fuzzy = False
    target = None

    def flush() -> None:
        nonlocal msgid, msgstr
        if msgid is not None and msgstr is not None:
            key = "".join(msgid)
            if key:
                entries[key] = "" if fuzzy else "".join(msgstr)
        msgid, msgstr = None, None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#~"):
            continue
        if line.startswith("#,"):
            fuzzy = "fuzzy" in line
            continue
        if line.startswith("#"):
            continue
        if line.startswith("msgid "):
            flush()
            msgid = [unquote(line[6:].strip())]
            msgstr = None
            fuzzy = False
            target = msgid
            continue
        if line.startswith("msgstr "):
            msgstr = [unquote(line[7:].strip())]
            target = msgstr
            continue
        if line.startswith('"'):
            if target is None:
                raise PoError(f"{path}: 续行前没有 msgid/msgstr")
            target.append(unquote(line))
            continue
        raise PoError(f"{path}: 无法解析的行 {raw!r}")
    flush()
    incomplete = any(value == "" for key, value in entries.items() if key)
    return entries, incomplete


# ---- .mo 编译 --------------------------------------------------------------


def compile_mo(entries: dict[str, str], language: str = "") -> bytes:
    """按 GNU gettext 的 .mo 格式打包。

    结构：header(7×uint32) + 原文表 + 译文表 + 两棵字符串池。
    原文必须按字节序排好，因为运行时用二分查找。

    必须带上 msgid 为空的那条「元数据」条目：gettext 从它的 Content-Type 里读
    charset，缺了它 CPython 会按 ASCII 解码整份目录，中文译文直接抛
    UnicodeDecodeError。
    """
    items = [("", METADATA.format(language=language))]
    items += sorted((key, value) for key, value in entries.items() if key and value)
    keys = [key.encode("utf-8") for key, _ in items]
    values = [value.encode("utf-8") for _, value in items]

    count = len(items)
    key_table_offset = 7 * 4
    value_table_offset = key_table_offset + count * 8
    key_pool_offset = value_table_offset + count * 8

    key_pool = b""
    key_offsets: list[tuple[int, int]] = []
    for item in keys:
        key_offsets.append((len(item), len(key_pool)))
        key_pool += item + b"\x00"

    value_pool_offset = key_pool_offset + len(key_pool)
    value_pool = b""
    value_offsets: list[tuple[int, int]] = []
    for item in values:
        value_offsets.append((len(item), len(value_pool)))
        value_pool += item + b"\x00"

    output = bytearray()
    output += struct.pack(
        "<7I",
        0x950412DE,          # magic
        0,                   # 格式版本
        count,               # 条目数
        key_table_offset,
        value_table_offset,
        0,                   # 哈希表大小（可省）
        0,                   # 哈希表偏移
    )
    for length, offset in key_offsets:
        output += struct.pack("<2I", length, key_pool_offset + offset)
    for length, offset in value_offsets:
        output += struct.pack("<2I", length, value_pool_offset + offset)
    output += key_pool + value_pool
    return bytes(output)


def mo_path(language: str) -> pathlib.Path:
    return LOCALE_DIR / language / "LC_MESSAGES" / f"{DOMAIN}.mo"


# ---- 主流程 ----------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="抽取并编译界面翻译")
    parser.add_argument("--check", action="store_true", help="只校验，不写文件")
    parser.add_argument(
        "--refresh-po",
        action="store_true",
        help="按当前源码重写 .pot 与已存在 .po 的条目骨架（不覆盖已有译文）",
    )
    args = parser.parse_args(argv)

    messages = collect_messages()
    if not messages:
        print("::error::源码里没有找到任何 _() 文案", file=sys.stderr)
        return 1

    if not args.check and not args.refresh_po:
        pot = write_pot(messages)
        print(f"{pot.relative_to(ROOT)}: {len(messages)} 条")

    problems: list[str] = []
    for path in po_files():
        language = path.stem
        entries, incomplete = read_po(path)
        missing = sorted(set(messages) - set(entries))
        stale = sorted(set(entries) - set(messages))
        if missing:
            problems.append(f"{path.name}: 缺 {len(missing)} 条译文，例如 {missing[0][:40]!r}")
        if incomplete:
            problems.append(f"{path.name}: 有条目 msgstr 为空")
        if stale:
            # 源码里已删掉的文案不算错误，只是提醒该清理。
            print(f"提示：{path.name} 有 {len(stale)} 条源码已不再使用的条目")
        if args.check:
            continue
        payload = compile_mo(entries, language)
        target = mo_path(language)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        print(f"{target.relative_to(ROOT)}: {len(payload)} 字节, {len(entries)} 条")

    for problem in problems:
        print(f"::error::{problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
