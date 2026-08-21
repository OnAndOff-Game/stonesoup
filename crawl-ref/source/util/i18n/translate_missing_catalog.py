#!/usr/bin/env python3
"""Append safe Korean drafts for current player-facing C++ literals."""

from __future__ import annotations

import argparse
from pathlib import Path
import re

import build_korean_catalog as catalog_tools
import translate_missing_descriptions as translation_tools


DELIMITER = re.compile(r"(?m)^%%%%.*(?:\n|$)")
WORD = re.compile(r"[A-Za-z]{2,}")
SINGLE_UI_WORDS = {
    "ability", "armour", "cancel", "close", "command", "cost", "damage",
    "description", "done", "failure", "free", "health", "inventory",
    "magic", "menu", "message", "none", "okay", "quit", "search",
    "skill", "spell", "status", "success", "target", "weapon", "yes", "no",
}


def read_catalog(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for block in DELIMITER.split(path.read_text(encoding="utf-8"))[1:]:
        lines = block.splitlines()
        while lines and (not lines[0].strip() or lines[0].startswith("#")):
            lines.pop(0)
        if lines:
            result[lines[0]] = "\n".join(lines[1:]).rstrip()
    return result


def player_facing_candidate(text: str) -> bool:
    if not (1 < len(text) <= 500) or "\n" in text or "\0" in text:
        return False
    if text.strip() != text or "%%%%" in text or text.startswith("#"):
        return False
    words = WORD.findall(text)
    if not words:
        return False
    if len(words) == 1 and words[0].casefold() not in SINGLE_UI_WORDS:
        return False
    if re.fullmatch(r"[A-Za-z0-9_./:\\+*?^$|()\[\]{}-]+", text):
        return False
    if re.search(r"\.(?:cc|h|lua|des|txt|png|js|json|db|so|dll)\b", text, re.I):
        return False
    if text.startswith(("http://", "https://", "ASSERT", "DEBUG")):
        return False
    if re.search(r"(?:^|\s)--[A-Za-z-]+(?:=|\s|$)", text):
        return False
    # Regexes and printf implementation fragments are not player prose.
    if ("(?:" in text or "(?=" in text or "(?<" in text
        or "std::" in text or "string::" in text):
        return False
    return True


def collect_units(texts: list[str]) -> list[str]:
    units: list[str] = []
    for text in texts:
        normal, _ = translation_tools.paragraph_units(text)
        units.extend(normal)
        if translation_tools.PROTECTED.search(text):
            units.extend(translation_tools.segmented_units(text))
        units.extend(translation_tools.lua_string_units(text))
    return list(dict.fromkeys(units))


def append_entries(path: Path, entries: list[tuple[str, str]]) -> None:
    if not entries:
        return
    text = path.read_text(encoding="utf-8")
    if text and not text.endswith("\n"):
        text += "\n"
    chunks = [text]
    for english, korean in entries:
        chunks.extend(
            (
                "%%%%\n",
                "# AUTO-GENERATED KOREAN UI DRAFT; keep the English key exact.\n",
                english + "\n",
                korean + "\n",
            )
        )
    path.write_text("".join(chunks), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--sentencepiece", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--beam-size", type=int, default=1)
    parser.add_argument("--count-only", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    current = catalog_tools.current_cpp_strings(args.source)
    existing = read_catalog(args.catalog)
    candidates = sorted(
        (
            text for text in current
            if text not in existing and player_facing_candidate(text)
        ),
        key=lambda text: (text.casefold(), text),
    )
    units = collect_units(candidates)
    print(
        f"Current literals: {len(current)}; existing: {len(existing)}; "
        f"new candidates: {len(candidates)}; units: {len(units)}"
    )
    if args.count_only:
        return 0

    cache = translation_tools.translate_units(
        units,
        args.model,
        args.cache,
        args.batch_size,
        args.beam_size,
        args.sentencepiece,
    )
    translated: list[tuple[str, str]] = []
    rejected = 0
    for english in candidates:
        korean = translation_tools.translate_body(english, cache).replace("\n", " ")
        if not catalog_tools.safe_entry(english, korean, current):
            rejected += 1
            continue
        translated.append((english, korean))
    print(f"Safe translations: {len(translated)}; rejected: {rejected}")
    if args.apply:
        append_entries(args.catalog, translated)
        print(f"Appended {len(translated)} UI/message drafts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
