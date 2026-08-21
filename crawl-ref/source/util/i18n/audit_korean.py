#!/usr/bin/env python3
"""Audit Korean description and exact-string catalog completeness."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import re
import sys


DELIMITER = re.compile(r"(?m)^%%%%.*(?:\n|$)")
TOKEN = re.compile(
    r"\[\[.*?\]\]|@[A-Za-z0-9_ -]+@|</?[^>\n]+>"
    r"|\$[A-Za-z_]+\[[^\]\n]+\]"
    r"|<[A-Za-z]+(?=\s|$)"
    r"|%(?! of\b)(?:\d+\$)?[-+ #0']*(?:\d+|\*)?(?:\.(?:\d+|\*))?"
    r"(?:hh|h|ll|l|j|z|t|L)?[diuoxXfFeEgGaAcspn%]",
    re.DOTALL,
)
LUA_BLOCK = re.compile(r"\{\{.*?\}\}", re.DOTALL)
LUA_STRING = re.compile(r'"(?:\\.|[^"\\])*"')
ENGLISH_WORD = re.compile(r"\b[A-Za-z]{3,}\b")


def entries(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for block in DELIMITER.split(path.read_text(encoding="utf-8"))[1:]:
        lines = block.splitlines()
        while lines and (not lines[0].strip() or lines[0].startswith("#")):
            lines.pop(0)
        if lines:
            result[lines[0].strip()] = "\n".join(lines[1:]).rstrip()
    return result


def entry_blocks(path: Path) -> list[tuple[str, str, bool]]:
    """Return every raw entry so duplicate keys cannot hide in a dict."""
    if not path.exists():
        return []
    result: list[tuple[str, str, bool]] = []
    for block in DELIMITER.split(path.read_text(encoding="utf-8"))[1:]:
        generated = "AUTO-GENERATED KOREAN" in block
        lines = block.splitlines()
        while lines and (not lines[0].strip() or lines[0].startswith("#")):
            lines.pop(0)
        if lines:
            result.append(
                (lines[0].strip(), "\n".join(lines[1:]).rstrip(), generated)
            )
    return result


def generated_keys(path: Path) -> set[str]:
    if not path.exists():
        return set()
    result: set[str] = set()
    for block in DELIMITER.split(path.read_text(encoding="utf-8"))[1:]:
        generated = "AUTO-GENERATED KOREAN" in block
        lines = block.splitlines()
        while lines and (not lines[0].strip() or lines[0].startswith("#")):
            lines.pop(0)
        if generated and lines:
            result.add(lines[0].strip())
    return result


def is_code_or_alias(body: str) -> bool:
    value = body.strip()
    return bool(
        not value
        or re.fullmatch(r"<[^>]+>", value, re.DOTALL)
        or re.fullmatch(r"\[\[.*\]\]", value, re.DOTALL)
        or re.fullmatch(r"\{\{.*\}\}", value, re.DOTALL)
    )


def _lua_code_literal(block: str, start: int) -> bool:
    prefix = block[:start].rstrip()
    if re.search(r"(?:==|~=)\s*$", prefix):
        return True
    return bool(
        re.search(
            r"(?:find|get_[A-Za-z0-9_]+|has_[A-Za-z0-9_]+)\s*\(\s*$",
            prefix,
        )
    )


def protected_signature(body: str) -> tuple[Counter[str], list[str], list[str]]:
    skeletons: list[str] = []
    code_literals: list[str] = []

    def normalise_lua(match: re.Match[str]) -> str:
        block = match.group(0)
        for literal in LUA_STRING.finditer(block):
            if _lua_code_literal(block, literal.start()):
                code_literals.append(literal.group(0))
        skeletons.append(LUA_STRING.sub('""', block))
        return "{{LUA_BLOCK}}"

    outside = LUA_BLOCK.sub(normalise_lua, body)
    return Counter(TOKEN.findall(outside)), skeletons, code_literals


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--korean", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    args = parser.parse_args()

    failures: list[str] = []
    total = translated = residue = 0
    print(f"{'file':24} {'base':>6} {'ko':>6} {'missing':>8} {'no-hangul':>10}")
    for base_file in sorted(args.base.glob("*.txt")):
        base = entries(base_file)
        ko_file = args.korean / base_file.name
        ko = entries(ko_file)
        generated = generated_keys(ko_file)
        missing = sorted(set(base) - set(ko))
        no_hangul = [
            key
            for key, body in ko.items()
            if key in base
            and not is_code_or_alias(body)
            and ENGLISH_WORD.search(body)
            and not any("가" <= char <= "힣" for char in body)
        ]
        for key in set(base) & set(ko) & generated:
            base_tokens = protected_signature(base[key])
            ko_tokens = protected_signature(ko[key])
            # An alias is intentionally copied and already handled above.
            if not is_code_or_alias(base[key]) and base_tokens != ko_tokens:
                failures.append(f"{base_file.name}:{key}: protected-token mismatch")
        print(
            f"{base_file.name:24} {len(base):6} {len(set(base) & set(ko)):6}"
            f" {len(missing):8} {len(no_hangul):10}"
        )
        total += len(base)
        translated += len(set(base) & set(ko))
        residue += len(no_hangul)
        failures.extend(f"{base_file.name}: missing {key}" for key in missing)
        failures.extend(f"{base_file.name}: no Hangul in {key}" for key in no_hangul)

    catalog_blocks = entry_blocks(args.catalog)
    catalog = {key: body for key, body, _generated in catalog_blocks}
    catalog_keys = Counter(key for key, _body, _generated in catalog_blocks)
    duplicate_catalog_keys = sorted(
        key for key, count in catalog_keys.items() if count > 1
    )
    failures.extend(
        f"messages.txt: duplicate key {key}" for key in duplicate_catalog_keys
    )
    generated_catalog_count = 0
    for key, body, generated in catalog_blocks:
        if key == "__korean_catalog_version__" or not generated:
            continue
        generated_catalog_count += 1
        if ENGLISH_WORD.search(body) and not any("가" <= char <= "힣" for char in body):
            failures.append(f"messages.txt: generated entry has no Hangul: {key}")
        key_tokens = TOKEN.findall(key)
        body_tokens = TOKEN.findall(body)
        key_printf = [token for token in key_tokens if token.startswith("%")]
        body_printf = [token for token in body_tokens if token.startswith("%")]
        if Counter(key_tokens) != Counter(body_tokens) or key_printf != body_printf:
            failures.append(f"messages.txt: format-token mismatch: {key}")
    catalog_count = len(catalog) - int("__korean_catalog_version__" in catalog)
    print(
        f"TOTAL {translated}/{total}; exact UI/message catalog: {catalog_count}"
        f" ({generated_catalog_count} generated drafts)"
    )
    if failures:
        print(f"FAIL: {len(failures)} issue(s)", file=sys.stderr)
        for failure in failures[:80]:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print("PASS: every current description key has a Korean entry")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
