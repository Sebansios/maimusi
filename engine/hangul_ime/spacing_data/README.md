# Informal spacing vocabulary

This directory is offline runtime data. It contains no user input, conversation
logs, personal names mined from messages, or downloaded sentence corpora. The
engine adds POS-tagged analysis candidates before warming Kiwi. It only changes
ASCII spaces; dialect spelling, slang and emoticons remain literal.

## Open Korean Text subset

- Source: [Open Korean Text `noun/slangs.txt`](https://github.com/open-korean-text/open-korean-text/blob/74cc4ae7d3dab232747cd5ddb723e4b73c476e4f/src/main/resources/org/openkoreantext/processor/util/noun/slangs.txt).
- Commit: `74cc4ae7d3dab232747cd5ddb723e4b73c476e4f`.
- Original SHA-256: `c5c9d0d6255361047ef6f663cbeca292bf391e5dd97586d5e39991207dd10339`.
- Copyright 2014 Twitter, Inc.; Apache-2.0, full text in
  `LICENSE-open-korean-text.txt`. Pinned source metadata is in
  `open-korean-text-source.json`.
- Changes: reviewed 78 nominal entries from 179 source lines; added `NNG` and
  score `-3`. Excluded single syllables, predicates, sentence fragments, ordinary
  noun phrases and ambiguous items. The upstream directory name alone is not
  evidence that every entry is a noun.

This is a limited vocabulary, not a normative spelling dictionary. No entries
are downloaded automatically or learned from typing. Apache attribution and
license text are included in the frozen app.

## Authored data and morphology

`authored-nouns.tsv` contains a finite, manually authored set of newer colloquial
nouns, with the same conservative score. `informal.py` preserves the previous
12 authored words/stems, registers a small set of additional stems and dialect
forms, and uses [Kiwi's original-morpheme and rule APIs](https://bab2min.github.io/kiwipiepy/v0.22.1/kr/)
to retain grammatical context. `요→용/욤` variants apply to final endings only.
These registrations do not replace dialects with standard Korean.

No unrestricted `개-`, `-린이`, `-알못` or adjacent-noun joining rule is used.
The broad `요→유` family was rejected after a corpus regression. Three
`개+predicate` aliases were also rejected because they can reinterpret literal
dogs as an intensifier (`이 개 웃기게 생겼다`). The ambiguous noun `억빠` was
withheld after a cross-word false positive. A finite list still cannot resolve
every semantic ambiguity or newly coined word.

The nominal and ending scores were tested at `0`, `-2`, `-4` (the nominal
development results were identical); the final nominal/alias score is `-3`.
See `docs/SPACING_EVALUATION_20261002.md` for before/after measurements, separate
development and held-out evaluations, rejected experiments and remaining gaps.

## Rechecking the external subset

Fetch the pinned URL above, verify the original SHA-256, and check every first
TSV column against the source lines. Fetching is a development task; evaluation
and normal typing require no network. The runtime TSV and original source
checksums intentionally differ because the TSV is a filtered derivative.
