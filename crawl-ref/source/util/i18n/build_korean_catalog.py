#!/usr/bin/env python3
"""Build the Korean exact-string catalog from GPL-compatible gettext files.

Only translations whose English msgid still occurs verbatim in the current
source are retained. C printf placeholders must also occur in the same order;
this is deliberately stricter than gettext so the catalog is safe on every
platform supported by Crawl.
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import re
from typing import Iterable


CPP_SUFFIXES = {".cc", ".cpp", ".c", ".h", ".hpp"}
CPP_STRING = re.compile(r'(?:u8|u|U|L)?"(?:\\.|[^"\\])*"')
PRINTF_TOKEN = re.compile(
    r"%(?:\d+\$)?[-+ #0']*(?:\d+|\*)?(?:\.(?:\d+|\*))?"
    r"(?:hh|h|ll|l|j|z|t|L)?[diuoxXfFeEgGaAcspn%]"
)


def _po_quoted(line: str) -> str:
    value = line[line.find('"') :]
    return ast.literal_eval(value)


def read_po(path: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    msgid: list[str] = []
    msgstr: list[str] = []
    active: list[str] | None = None
    fuzzy = False

    def finish() -> None:
        nonlocal msgid, msgstr, active, fuzzy
        key = "".join(msgid)
        value = "".join(msgstr)
        if key and value and not fuzzy and key not in entries:
            entries[key] = value
        msgid, msgstr, active, fuzzy = [], [], None, False

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line:
            finish()
        elif line.startswith("#, ") and "fuzzy" in line:
            fuzzy = True
        elif line.startswith("msgid "):
            msgid = [_po_quoted(line)]
            active = msgid
        elif line.startswith("msgstr "):
            msgstr = [_po_quoted(line)]
            active = msgstr
        elif line.startswith('"') and active is not None:
            active.append(_po_quoted(line))
    finish()
    return entries


def _decode_cpp_string(token: str) -> str | None:
    token = re.sub(r"^(?:u8|u|U|L)", "", token)
    try:
        return ast.literal_eval(token)
    except (SyntaxError, ValueError):
        return None


def current_cpp_strings(source_dir: Path) -> set[str]:
    strings: set[str] = set()
    for path in source_dir.rglob("*"):
        if path.suffix not in CPP_SUFFIXES or "contrib" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        tokens = list(CPP_STRING.finditer(text))
        for token in tokens:
            decoded = _decode_cpp_string(token.group())
            if decoded is not None:
                strings.add(decoded)

        # Crawl frequently splits long display strings into adjacent C++
        # literals. Collect those concatenated forms as well.
        run: list[str] = []
        previous_end = -1
        for token in tokens:
            decoded = _decode_cpp_string(token.group())
            between = text[previous_end : token.start()] if previous_end >= 0 else ""
            if run and between.strip():
                if len(run) > 1:
                    strings.add("".join(run))
                run = []
            if decoded is not None:
                run.append(decoded)
            previous_end = token.end()
        if len(run) > 1:
            strings.add("".join(run))
    return strings


def _format_tokens(text: str) -> list[str]:
    return [token for token in PRINTF_TOKEN.findall(text) if token != "%%"]


def safe_entry(english: str, korean: str, current: set[str]) -> bool:
    if english not in current or not any("가" <= c <= "힣" for c in korean):
        return False
    if english.strip() != english or korean.strip() != korean:
        return False
    if "\n" in english or "\n" in korean or "\0" in english or "\0" in korean:
        return False
    if english.startswith("#") or korean.startswith("#"):
        return False
    if "%%%%" in english or "%%%%" in korean:
        return False
    return _format_tokens(english) == _format_tokens(korean)


def write_catalog(output: Path, entries: Iterable[tuple[str, str]]) -> None:
    lines = [
        "###############################################################################",
        "# Korean UI and message translations.",
        "# Exact current-source matches imported from the GPL Korean gettext project.",
        "###############################################################################",
        "%%%%",
        "__korean_catalog_version__",
        "0.34-ko",
    ]
    for english, korean in entries:
        lines.extend(("%%%%", english, korean))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("po", type=Path, nargs="+")
    args = parser.parse_args()

    current = current_cpp_strings(args.source)
    merged: dict[str, str] = {}
    for po_path in args.po:
        for english, korean in read_po(po_path).items():
            if english not in merged and safe_entry(english, korean, current):
                merged[english] = korean

    entries = sorted(merged.items(), key=lambda item: (item[0].casefold(), item[0]))
    write_catalog(args.output, entries)
    print(f"Wrote {len(entries)} safe current translations to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
