"""界面语言这一件事：说哪种语言、译文从哪来、``_()`` 怎么调用。

负责：把「系统 locale / ``RDPFLOW_LANG``」解析成受支持的语言，绑定该语言的翻译
      目录，并把缺失译文的字符串原样返回（中文既是源语言，也是最终的兜底文案）。
不负责：任何具体文案、任何控件构建 —— 文案留在各自模块里就地 ``_()`` 包裹。

为什么单独一层：语言是"进程启动时确定、之后不再变化"的全局事实，探测规则
（覆盖变量优先、``zh_TW`` 落到简体源文、缺 .mo 时静默回退）只有一份；散在 ui / dialogs
里就会各猜一次，且 models 这类无 GTK 的模块拿不到同一个答案。
"""

from __future__ import annotations

import gettext
import os

from . import runtime

# gettext 域，也是 .mo 的文件名：locale/<lang>/LC_MESSAGES/rdpflow.mo
DOMAIN = "rdpflow"
# 源语言。代码里的 msgid 就是简体中文原文，因此 zh 系不需要 .mo，
# "没有译文"与"中文原文"是同一个东西。
SOURCE_LANGUAGE = "zh_CN"
SUPPORTED_LANGUAGES: tuple[str, ...] = ("zh_CN", "en")
# 强制指定界面语言。LANGUAGE 只覆盖 LC_MESSAGES，管不到 GTK 自己的翻译，
# 想要"系统中文、界面英文"就得有这一个变量。
LANGUAGE_OVERRIDE = "RDPFLOW_LANG"

_translation: gettext.NullTranslations = gettext.NullTranslations()


def environment_tags() -> tuple[str, ...]:
    """这台机器声称的语言，按优先级排列。

    覆盖变量独占一档：一旦设置就只看它，免得被下面的 LANGUAGE 列表盖过去。
    其余按 glibc 的优先级来，LANGUAGE 是用户级的偏好列表（冒号分隔）。
    """
    override = os.environ.get(LANGUAGE_OVERRIDE, "").strip()
    if override:
        return (override,)
    tags: list[str] = []
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        value = os.environ.get(name, "").strip()
        if value:
            tags.extend(part for part in value.split(":") if part.strip())
    return tuple(tags)


def normalize(tag: str) -> str | None:
    """把一个 locale 标签收敛成受支持的语言；认不出来就返回 None。

    形如 ``en_US.UTF-8@euro`` 的尾巴一律丢掉：编码与变体对选哪个 .mo 没有影响。
    """
    cleaned = tag.split(".", 1)[0].split("@", 1)[0].replace("-", "_").strip()
    if not cleaned or cleaned in ("C", "POSIX"):
        return None
    lowered = cleaned.lower()
    if lowered.startswith("zh"):
        # 源文就是简体中文：zh、zh_Hans、zh_TW 一律吃原文，不额外维护译文。
        return SOURCE_LANGUAGE
    if lowered.startswith("en"):
        return "en"
    return None


def resolve_language() -> str:
    """本次进程该用哪种语言。全都认不出来时回到源语言（简体中文）。"""
    for tag in environment_tags():
        language = normalize(tag)
        if language:
            return language
    return SOURCE_LANGUAGE


def translation(language: str | None = None) -> gettext.NullTranslations:
    """取某个语言的翻译表；源语言或缺 .mo 的降级都由这里收口。"""
    language = language or resolve_language()
    if language == SOURCE_LANGUAGE:
        return gettext.NullTranslations()
    # fallback=True：语言目录还没编译（源码树没跑过 build-locales）时退回原文，
    # 界面照常可用，只是仍是中文 —— 比抛异常好。
    return gettext.translation(
        DOMAIN,
        localedir=str(runtime.locale_dir()),
        languages=[language],
        fallback=True,
    )


def install(language: str | None = None) -> str:
    """绑定本次进程的翻译表并返回最终采用的语言。"""
    global _translation
    resolved = language or resolve_language()
    _translation = translation(resolved)
    return resolved


def _(message: str) -> str:
    """取一条文案的译文。

    故意不在 import 期就把结果算进模块级常量里的场景（少数需要动态拼接的字符串）
    也走这里：每次调用都查一次翻译表，语言切换、测试里重装都能立即生效。
    """
    return _translation.gettext(message)


def describe() -> dict[str, object]:
    """当前语言状态，给 ``--self-check`` 与「诊断信息」面板用。"""
    language = resolve_language()
    directory = runtime.locale_dir()
    compiled = sorted(
        child.parent.parent.name
        for child in directory.glob(f"*/LC_MESSAGES/{DOMAIN}.mo")
    )
    return {
        "language": language,
        "supported": list(SUPPORTED_LANGUAGES),
        "environment": list(environment_tags()),
        "domain": DOMAIN,
        "locale_dir": str(directory),
        "compiled": compiled,
    }


# 进程启动即绑定：任何模块的 import 期文案（下拉项标签这类模块级字典）都能拿到
# 正确的语言，调用方不必记得先 install 一次。
install()
