#!/usr/bin/env python3
"""Fill missing Korean description entries with an offline MT draft.

Existing Korean entries are never modified. Crawl markup, Lua expressions,
substitution keys, printf placeholders, and URLs are protected before text is
sent to the model and restored afterwards.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
import json
from pathlib import Path
import re
from typing import NamedTuple

import ctranslate2
import sentencepiece as sentencepiece


DELIMITER = re.compile(r"(?m)^%%%%.*(?:\n|$)")
PROTECTED = re.compile(
    r"\{\{.*?\}\}|\[\[.*?\]\]|@[A-Za-z0-9_ -]+@|</?[^>\n]+>"
    r"|\$[A-Za-z_]+\[[^\]\n]+\]"
    r"|%(?! of\b)(?:\d+\$)?[-+ #0']*(?:\d+|\*)?(?:\.(?:\d+|\*))?"
    r"(?:hh|h|ll|l|j|z|t|L)?[diuoxXfFeEgGaAcspn%]"
    r"|<[A-Za-z]+(?=\s|$)|https?://\S+|\\[nrt]",
    re.DOTALL,
)
LUA_BLOCK = re.compile(r"\{\{.*?\}\}", re.DOTALL)
LUA_STRING = re.compile(r'"(?:\\.|[^"\\])*"')
PARAGRAPH_BREAK = re.compile(r"(\n[ \t]*\n+)")
SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+")
ENGLISH_WORD = re.compile(r"[A-Za-z]{2,}")

RESIDUE_GLOSSARY = {
    "dungeon": "던전",
    "spells": "주문",
    "spellcasting": "주문 시전술",
    "spellbook": "주문서",
    "spellpower": "주문력",
    "spell": "주문",
    "caster": "시전자",
    "undead": "언데드",
    "melee": "근접",
    "foes": "적들",
    "foe": "적",
    "willpower": "의지력",
    "invocations": "기도술",
    "evocations": "발동술",
    "shapeshifting": "변신술",
    "necromancy": "강령술",
    "conjurations": "요술",
    "summonings": "소환술",
    "translocations": "전이술",
    "forgecraft": "대장술",
    "alchemy": "연금술",
    "hexes": "주술",
    "staves": "봉술",
    "maces": "철퇴술",
    "axes": "도끼술",
    "polearms": "창술",
    "zot": "조트",
    "abyss": "심연",
    "pandemonium": "판데모니엄",
    "crypt": "납골당",
    "cocytus": "코키투스",
    "gehenna": "게헨나",
    "tartarus": "타르타로스",
    "vaults": "금고",
    "yredelemnul": "이레데렘눌",
    "yredelemnull": "이레데렘눌",
    "yredemnull": "이레데렘눌",
    "ashenzari": "아셴자리",
    "ignis": "이그니스",
    "makhleb": "마크레브",
    "makleb": "마크레브",
    "beogh": "베오그",
    "beough": "베오그",
    "beog": "베오그",
    "uskayaw": "우스카요",
    "qazlal": "콰즈랄",
    "kikubaaqudgha": "키쿠바쿠드하",
    "gozag": "고자그",
    "trog": "트로그",
    "zin": "진",
    "xom": "좀",
    "orb": "오브",
    "rune": "룬",
    "potion": "물약",
    "artefacts": "아티팩트",
    "artefact": "아티팩트",
    "amulet": "부적",
    "magic": "마법",
    "orc": "오크",
    "elf": "엘프",
    "dragon": "용",
    "armour": "갑옷",
    "stasis": "정지",
    "formicids": "포미시드",
    "djinn": "진",
    "armataurs": "아마타우르",
    "oni": "오니",
    "kobolds": "코볼트",
    "coglins": "코글린",
    "barachim": "바라킴",
    "gnolls": "놀",
    "fire": "불",
    "air": "대기",
    "ice": "얼음",
    "earth": "대지",
    "flails": "도리깨술",
    "spriggans": "스프리건",
    "fedhas": "페다스",
    "asmodeus": "아스모데우스",
    "cerebov": "세레보브",
    "mnoleg": "므놀렉",
    "lom": "롬",
    "lobon": "로본",
    "glorx": "글로르크스",
    "vloq": "블로크",
    "arcane": "비전",
    "shapeshifters": "변신술사",
    "hexslingers": "주술사수",
    "delvers": "탐험가",
    "acolytes": "사도",
    "ironbound": "철갑",
    "bolas": "볼라",
    "oozing": "스며드는",
    "aloft": "비행 중",
    "auto": "자동",
    "explore": "탐색",
    "rest": "휴식",
    "enter": "엔터",
    "exclude": "제외",
}

KOREAN_GLOSSARY = {
    "철자": "주문",
    "캐스터": "시전자",
    "스케일": "비늘",
}


class Entry(NamedTuple):
    key: str
    body: str


def read_entries(path: Path) -> list[Entry]:
    if not path.exists():
        return []
    blocks = DELIMITER.split(path.read_text(encoding="utf-8"))[1:]
    entries: list[Entry] = []
    for block in blocks:
        lines = block.splitlines()
        while lines and (not lines[0].strip() or lines[0].startswith("#")):
            lines.pop(0)
        if not lines:
            continue
        entries.append(Entry(lines[0].strip(), "\n".join(lines[1:]).rstrip()))
    return entries


def placeholder_name(index: int) -> str:
    letters = ""
    value = index
    while True:
        letters = chr(ord("A") + value % 26) + letters
        value = value // 26 - 1
        if value < 0:
            break
    return "ZXQPH" + letters.rjust(4, "A")


def protect(text: str) -> tuple[str, dict[str, str]]:
    replacements: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        marker = placeholder_name(len(replacements))
        replacements[marker] = match.group(0)
        return marker

    return PROTECTED.sub(replace, text), replacements


def restore(text: str, replacements: dict[str, str]) -> str:
    for marker, original in replacements.items():
        # SentencePiece can occasionally put spaces inside an unknown token.
        spaced = r"\s*".join(re.escape(char) for char in marker)
        text, count = re.subn(spaced, lambda _: original, text)
        if count != 1:
            raise ValueError(f"protected marker {marker} was lost")
    return text


def split_long_text(text: str, max_words: int = 95) -> list[str]:
    if len(text.split()) <= max_words:
        return [text]
    sentences = SENTENCE_BREAK.split(text)
    result: list[str] = []
    current: list[str] = []
    for sentence in sentences:
        words = sentence.split()
        if len(words) > max_words:
            if current:
                result.append(" ".join(current))
                current = []
            result.extend(
                " ".join(words[i : i + max_words])
                for i in range(0, len(words), max_words)
            )
        elif current and len(" ".join(current).split()) + len(words) > max_words:
            result.append(" ".join(current))
            current = [sentence]
        else:
            current.append(sentence)
    if current:
        result.append(" ".join(current))
    return result


def paragraph_units(body: str) -> tuple[list[str], dict[str, str]]:
    protected, replacements = protect(body)
    pieces = PARAGRAPH_BREAK.split(protected)
    units: list[str] = []
    for piece in pieces:
        if not piece or PARAGRAPH_BREAK.fullmatch(piece):
            continue
        joined = " ".join(line.strip() for line in piece.splitlines()).strip()
        if not ENGLISH_WORD.search(joined):
            continue
        units.extend(split_long_text(joined))
    return units, replacements


def segmented_units(body: str) -> list[str]:
    """Return translatable text between markup tokens.

    This lower-context form is a safety fallback for markup-heavy tutorial and
    hint paragraphs, where an MT model may duplicate or drop placeholders.
    """
    units: list[str] = []
    position = 0
    for match in PROTECTED.finditer(body):
        units.extend(_plain_units(body[position : match.start()]))
        position = match.end()
    units.extend(_plain_units(body[position:]))
    return units


def _plain_units(text: str) -> list[str]:
    units: list[str] = []
    for piece in PARAGRAPH_BREAK.split(text):
        if not piece or PARAGRAPH_BREAK.fullmatch(piece):
            continue
        joined = " ".join(line.strip() for line in piece.splitlines()).strip()
        if ENGLISH_WORD.search(joined):
            units.extend(split_long_text(joined))
    return units


def _apply_glossary_plain(text: str) -> str:
    for english, korean in RESIDUE_GLOSSARY.items():
        text = re.sub(
            rf"(?<![A-Za-z]){re.escape(english)}(?![A-Za-z])",
            korean,
            text,
            flags=re.IGNORECASE,
        )
    for source, target in KOREAN_GLOSSARY.items():
        text = text.replace(source, target)
    return text


def apply_glossary(text: str) -> str:
    output: list[str] = []
    position = 0
    for match in PROTECTED.finditer(text):
        output.append(_apply_glossary_plain(text[position : match.start()]))
        output.append(match.group(0))
        position = match.end()
    output.append(_apply_glossary_plain(text[position:]))
    return "".join(output)


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


def lua_string_units(body: str) -> list[str]:
    units: list[str] = []
    for lua_match in LUA_BLOCK.finditer(body):
        block = lua_match.group(0)
        for string_match in LUA_STRING.finditer(block):
            if _lua_code_literal(block, string_match.start()):
                continue
            content = string_match.group(0)[1:-1]
            units.extend(_plain_units(content))
    return units


def translate_lua_strings(text: str, cache: dict[str, str]) -> str:
    def translate_block(lua_match: re.Match[str]) -> str:
        block = lua_match.group(0)
        output: list[str] = []
        position = 0
        for string_match in LUA_STRING.finditer(block):
            output.append(block[position : string_match.start()])
            literal = string_match.group(0)
            if _lua_code_literal(block, string_match.start()):
                output.append(literal)
            else:
                content = literal[1:-1]
                translated = _translate_plain(content, cache)
                translated = _apply_glossary_plain(translated)
                translated = translated.replace('"', '\\"')
                output.append('"' + translated + '"')
            position = string_match.end()
        output.append(block[position:])
        return "".join(output)

    return LUA_BLOCK.sub(translate_block, text)


def load_cache(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_cache(path: Path, cache: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def translate_units(
    units: list[str], model_dir: Path, cache_path: Path, batch_size: int,
    beam_size: int, tokenizer_path: Path
) -> dict[str, str]:
    cache = load_cache(cache_path)
    pending = [unit for unit in OrderedDict.fromkeys(units) if unit not in cache]
    if not pending:
        return cache

    tokenizer = sentencepiece.SentencePieceProcessor(
        model_file=str(tokenizer_path)
    )
    translator = ctranslate2.Translator(
        str(model_dir), device="cpu", inter_threads=1, intra_threads=0
    )
    for start in range(0, len(pending), batch_size):
        batch = pending[start : start + batch_size]
        tokenized = [tokenizer.encode(text, out_type=str) for text in batch]
        results = translator.translate_batch(
            tokenized, beam_size=beam_size, max_batch_size=min(32, batch_size)
        )
        for original, result in zip(batch, results):
            cache[original] = tokenizer.decode(result.hypotheses[0])
        save_cache(cache_path, cache)
        done = min(start + batch_size, len(pending))
        print(f"Translated {done}/{len(pending)} new text units", flush=True)
    return cache


def translate_body(body: str, cache: dict[str, str]) -> str:
    stripped = body.strip()
    if (
        not stripped
        or re.fullmatch(r"<[^>]+>", stripped, re.DOTALL)
        or re.fullmatch(r"\[\[.*\]\]", stripped, re.DOTALL)
    ):
        return body

    protected, replacements = protect(body)
    if len(replacements) > 5:
        return translate_body_segmented(body, cache)
    pieces = PARAGRAPH_BREAK.split(protected)
    output: list[str] = []
    for piece in pieces:
        if not piece or PARAGRAPH_BREAK.fullmatch(piece):
            output.append(piece)
            continue
        joined = " ".join(line.strip() for line in piece.splitlines()).strip()
        if not ENGLISH_WORD.search(joined):
            output.append(piece)
            continue
        translated = " ".join(cache[unit] for unit in split_long_text(joined))
        output.append(translated)

    try:
        translated_body = restore("".join(output), replacements)
    except ValueError:
        return translate_body_segmented(body, cache)
    translated_body = translate_lua_strings(translated_body, cache)
    translated_body = apply_glossary(translated_body)
    return translated_body


def _translate_plain(text: str, cache: dict[str, str]) -> str:
    pieces = PARAGRAPH_BREAK.split(text)
    output: list[str] = []
    for piece in pieces:
        if not piece or PARAGRAPH_BREAK.fullmatch(piece):
            output.append(piece)
            continue
        joined = " ".join(line.strip() for line in piece.splitlines()).strip()
        if not ENGLISH_WORD.search(joined):
            output.append(piece)
            continue
        translated = " ".join(cache[unit] for unit in split_long_text(joined))
        leading = piece[: len(piece) - len(piece.lstrip())]
        trailing = piece[len(piece.rstrip()) :]
        output.append(leading + translated + trailing)
    return "".join(output)


def translate_body_segmented(body: str, cache: dict[str, str]) -> str:
    output: list[str] = []
    position = 0
    for match in PROTECTED.finditer(body):
        output.append(_translate_plain(body[position : match.start()], cache))
        output.append(match.group(0))
        position = match.end()
    output.append(_translate_plain(body[position:], cache))
    translated = translate_lua_strings("".join(output), cache)
    return apply_glossary(translated)


def remove_generated_entries(path: Path) -> int:
    if not path.exists():
        return 0
    text = path.read_text(encoding="utf-8")
    matches = list(DELIMITER.finditer(text))
    if not matches:
        return 0
    output = [text[: matches[0].start()]]
    removed = 0
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block = text[match.end() : end]
        if "AUTO-GENERATED KOREAN DRAFT" in block:
            removed += 1
        else:
            output.append(match.group(0))
            output.append(block)
    path.write_text("".join(output), encoding="utf-8")
    return removed


def append_entries(path: Path, entries: list[Entry]) -> None:
    if not entries:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    prefix = path.read_text(encoding="utf-8") if path.exists() else ""
    if prefix and not prefix.endswith("\n"):
        prefix += "\n"
    chunks: list[str] = [prefix]
    for entry in entries:
        chunks.extend(
            (
                "%%%%\n",
                "# AUTO-GENERATED KOREAN DRAFT; preserve the key when editing.\n",
                entry.key + "\n",
                entry.body.rstrip() + "\n",
            )
        )
    path.write_text("".join(chunks), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--korean", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument(
        "--sentencepiece",
        type=Path,
        help="SentencePiece model (defaults to ../sentencepiece.model)",
    )
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--batch-size", type=int, default=96)
    parser.add_argument("--beam-size", type=int, default=2)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--refresh-auto", action="store_true")
    args = parser.parse_args()

    if args.refresh_auto:
        removed = sum(
            remove_generated_entries(path) for path in args.korean.glob("*.txt")
        )
        print(f"Removed {removed} prior generated entries")

    jobs: dict[Path, list[Entry]] = {}
    all_units: list[str] = []
    for base_file in sorted(args.base.glob("*.txt")):
        ko_file = args.korean / base_file.name
        base_entries = read_entries(base_file)
        ko_keys = {entry.key for entry in read_entries(ko_file)}
        missing = [entry for entry in base_entries if entry.key not in ko_keys]
        jobs[ko_file] = missing
        for entry in missing:
            units, _ = paragraph_units(entry.body)
            all_units.extend(units)
            if PROTECTED.search(entry.body):
                all_units.extend(segmented_units(entry.body))
            all_units.extend(lua_string_units(entry.body))
        print(f"{base_file.name}: {len(missing)} missing entries")

    print(f"Translation units: {len(OrderedDict.fromkeys(all_units))}")
    tokenizer_path = args.sentencepiece or args.model.parent / "sentencepiece.model"
    cache = translate_units(
        all_units,
        args.model,
        args.cache,
        args.batch_size,
        args.beam_size,
        tokenizer_path,
    )

    if not args.apply:
        print("Dry run complete; pass --apply to append generated entries.")
        return 0

    for ko_file, entries in jobs.items():
        translated = [Entry(entry.key, translate_body(entry.body, cache)) for entry in entries]
        append_entries(ko_file, translated)
    print(f"Appended drafts for {sum(map(len, jobs.values()))} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
