"""Fix UTF-8 text that was mis-decoded as Latin-1/Windows-1252 (mojibake)."""

from __future__ import annotations

import re

_MOJIBAKE_MARKERS = re.compile(r"â[\u0080-\u00BF]|Ã.|Â.|\ufffd", re.UNICODE)


def fix_mojibake(text: str | None) -> str:
    if not text:
        return ""

    out = text

    if _MOJIBAKE_MARKERS.search(out):
        try:
            recovered = out.encode("latin-1").decode("utf-8")
            if recovered.count("\ufffd") <= out.count("\ufffd"):
                out = recovered
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass

    # Remaining cp1252 mojibake fragments after partial recovery
    out = re.sub(r"â€.", "\u2014", out)
    out = out.replace("â€™", "\u2019")
    out = out.replace("â€œ", "\u201c")
    out = out.replace("â€\u009d", "\u201d")
    out = out.replace("â†'", "\u2192")
    out = out.replace("â†\u0090", "\u2190")
    out = out.replace("Ã©", "é")
    out = out.replace("Ã¯", "ï")
    out = out.replace("Â·", "\u00b7")
    out = out.replace("Â ", " ")

    # U+FFFD often substituted for em dash in indexed titles
    out = re.sub(r"Handoff\s+\ufffd\s+", "Handoff \u2014 ", out)
    out = re.sub(r"Handoff\s+(?=\d{4}-)", "Handoff \u2014 ", out)
    out = re.sub(r"(\S)\ufffd(\s)", lambda m: f"{m.group(1)}\u2014{m.group(2)}", out)

    return out
