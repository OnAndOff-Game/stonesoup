# Korean translation sources

The Korean localisation combines three kinds of data:

- the Korean description files already distributed with Dungeon Crawl Stone
  Soup;
- exact-string translations derived from `blmarket/crawl-korean`, branch
  `gettextized`;
- new translations maintained in this fork.

The historical gettext files state that they are distributed under the same
licence as the package. Dungeon Crawl Stone Soup and this fork are distributed
under GPL-2.0-or-later. Historical strings are imported only when their English
source text still matches the current source exactly and their `printf`
placeholder order is unchanged.

Description entries and exact UI/message entries whose comments begin with
`AUTO-GENERATED KOREAN` were filled with
`HPLT/translate-en-ko-v2.0-hplt` so that every current 0.34 description key has
a Korean fallback and current player-facing source strings have broad Korean
coverage. The HPLT model is licensed under CC-BY-4.0. These entries are drafts,
not a claim of human-reviewed literary quality; replacing them in place with
reviewed Korean is encouraged.

Model source and attribution:

- https://huggingface.co/HPLT/translate-en-ko-v2.0-hplt

To rebuild the exact-string catalog, run:

```sh
python crawl-ref/source/util/i18n/build_korean_catalog.py \
  --source crawl-ref/source \
  --output crawl-ref/source/dat/strings/ko/messages.txt \
  Crawl_korean.po Crawl_mutation.po Crawl_verbs.po Crawl_words.po
```

To translate current safe-but-missing description and source-string entries
with a locally converted CTranslate2 copy of the HPLT model, run:

```sh
python crawl-ref/source/util/i18n/translate_missing_descriptions.py --help
python crawl-ref/source/util/i18n/translate_missing_catalog.py --help
```

Completeness can be checked without installing a translation model:

```sh
python crawl-ref/source/util/i18n/audit_korean.py \
  --base crawl-ref/source/dat/descript \
  --korean crawl-ref/source/dat/descript/ko \
  --catalog crawl-ref/source/dat/strings/ko/messages.txt
```
