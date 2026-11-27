#!/usr/bin/env python3
"""版本号一致性检查：包版本、spec、CHANGELOG、tag 只说一个数。

CI 用它挡住"改了 __version__ 忘了改 spec"这种低错：发布工作流拿 tag 去比对版本，
一旦三处不同就整条 release 中止，代价比在这里跑 20ms 高得多。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VERSION_INIT = re.compile(r'^__version__\s*=\s*"([^"]+)"', re.MULTILINE)
VERSION_SPEC = re.compile(r"^Version:\s*(\S+)", re.MULTILINE)
VERSION_CHANGELOG = re.compile(r"^## \[([0-9][^\]]*)\]", re.MULTILINE)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def package_version() -> str:
    found = VERSION_INIT.search(read(ROOT / "rdpflow" / "__init__.py"))
    if not found:
        raise SystemExit("rdpflow/__init__.py 里找不到 __version__")
    return found.group(1)


def spec_version() -> str:
    found = VERSION_SPEC.search(read(ROOT / "rdpflow.spec"))
    if not found:
        raise SystemExit("rdpflow.spec 里找不到 Version:")
    return found.group(1)


def changelog_versions() -> list[str]:
    return VERSION_CHANGELOG.findall(read(ROOT / "CHANGELOG.md"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--expect",
        help="期望版本号（通常是去掉 v 的 tag），例如 0.2.0",
    )
    args = parser.parse_args(argv)

    version = package_version()
    spec = spec_version()
    changelog = changelog_versions()

    problems: list[str] = []
    print(f"package:    {version}")
    print(f"spec:       {spec}")
    print(f"changelog:  {', '.join(changelog) or '(空)'}")

    if version != spec:
        problems.append(f"rdpflow.spec 的 Version ({spec}) 与包版本 ({version}) 不一致")
    if version not in changelog:
        problems.append(f"CHANGELOG.md 里没有 ## [{version}] 小节")
    if args.expect and args.expect.lstrip("v") != version:
        problems.append(f"tag ({args.expect}) 与包版本 ({version}) 不一致")

    for problem in problems:
        print(f"::error::{problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
