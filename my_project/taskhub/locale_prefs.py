from __future__ import annotations

import re

SUPPORTED_LANGUAGE_META: dict[str, dict[str, str]] = {
    "zh-CN": {
        "label": "中文",
        "bot_label": "🇨🇳 中文",
        "intl": "zh-CN",
        "dir": "ltr",
    },
    "en": {
        "label": "English",
        "bot_label": "🇬🇧 English",
        "intl": "en-US",
        "dir": "ltr",
    },
    "ru": {
        "label": "Русский",
        "bot_label": "🇷🇺 Русский",
        "intl": "ru-RU",
        "dir": "ltr",
    },
    "ar": {
        "label": "العربية",
        "bot_label": "🇸🇦 العربية",
        "intl": "ar",
        "dir": "rtl",
    },
    "fr": {
        "label": "Français",
        "bot_label": "🇫🇷 Français",
        "intl": "fr-FR",
        "dir": "ltr",
    },
    "pt-BR": {
        "label": "Português",
        "bot_label": "🇧🇷 Português",
        "intl": "pt-BR",
        "dir": "ltr",
    },
    "es": {
        "label": "Español",
        "bot_label": "🇪🇸 Español",
        "intl": "es-ES",
        "dir": "ltr",
    },
    "vi": {
        "label": "Tiếng Việt",
        "bot_label": "🇻🇳 Tiếng Việt",
        "intl": "vi-VN",
        "dir": "ltr",
    },
}

SUPPORTED_LANGUAGE_CHOICES = tuple((code, meta["label"]) for code, meta in SUPPORTED_LANGUAGE_META.items())

DEFAULT_PREFERRED_LANGUAGE = "en"
LANGUAGE_START_PREFIX = "lang_"
_LANG_TOKEN_RE = re.compile(r"^(?:lang|locale)[_-](?P<value>.+)$", re.IGNORECASE)

_LANGUAGE_ALIASES = {
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
    "cn": "zh-CN",
    "chs": "zh-CN",
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
    "ru": "ru",
    "ru-ru": "ru",
    "ar": "ar",
    "ar-sa": "ar",
    "fr": "fr",
    "fr-fr": "fr",
    "pt": "pt-BR",
    "pt-br": "pt-BR",
    "br": "pt-BR",
    "es": "es",
    "es-es": "es",
    "es-419": "es",
    "vi": "vi",
    "vi-vn": "vi",
}


def normalize_preferred_language(raw: str | None) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    if text in SUPPORTED_LANGUAGE_META:
        return text
    lowered = text.replace("_", "-").lower()
    if lowered in _LANGUAGE_ALIASES:
        return _LANGUAGE_ALIASES[lowered]
    short = lowered.split("-", 1)[0]
    return _LANGUAGE_ALIASES.get(short)


def locale_meta(code: str | None) -> dict[str, str]:
    normalized = normalize_preferred_language(code) or DEFAULT_PREFERRED_LANGUAGE
    return SUPPORTED_LANGUAGE_META[normalized]


def supported_languages_for_bot() -> list[list[tuple[str, str]]]:
    rows = [
        ("en", "zh-CN"),
        ("ru", "ar"),
        ("fr", "pt-BR"),
        ("es", "vi"),
    ]
    return [
        [(SUPPORTED_LANGUAGE_META[left]["bot_label"], left), (SUPPORTED_LANGUAGE_META[right]["bot_label"], right)]
        for left, right in rows
    ]


def make_language_start_payload(code: str) -> str:
    normalized = normalize_preferred_language(code) or DEFAULT_PREFERRED_LANGUAGE
    return f"{LANGUAGE_START_PREFIX}{normalized}"


def split_start_payload_language(raw: str | None) -> tuple[str | None, str | None]:
    text = (raw or "").strip()
    if not text:
        return None, None
    lang: str | None = None
    rest: list[str] = []
    for part in [seg.strip() for seg in text.split("__") if seg.strip()]:
        matched = _LANG_TOKEN_RE.match(part)
        if matched:
            parsed = normalize_preferred_language(matched.group("value"))
            if parsed:
                lang = parsed
                continue
        rest.append(part)
    if lang is None:
        matched = _LANG_TOKEN_RE.match(text)
        if matched:
            return normalize_preferred_language(matched.group("value")), None
    return lang, ("__".join(rest) or None)
