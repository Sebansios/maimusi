#!/usr/bin/env python3
"""Convert a reference-implementation JSON spacing model to the HSPM binary.

The weights are the naive-Bayes log-odds contributions the Python reference
computes at run time, precomputed once so the native core only sums them:

    weight(key) = log((cs+a)/(S+a*V)) - log((cn+a)/(N+a*V))
    default(family) = the same with cs = cn = 0 (unseen key)
    word bonus = known_bonus + w_word * log((f+a)/(total+a*|words|))

Usage: convert_ngram_model.py model.json [morph_lex.json] -o spacing.hspm
The output contains only statistics; check the training data licence before
distributing it (see docs/LICENSING.md).
"""
import argparse
import json
import math
import struct

FAMILIES = ["P", "L", "R", "TL", "TR", "JL", "EL", "UR", "ADNU"]
SEP = "\t"


def table(rows, weighted):
    rows = sorted(rows, key=lambda r: r[0])
    blob = b"".join(k for k, _ in rows)
    out = [struct.pack("<II", len(rows), len(blob))]
    off = 0
    offsets = [0]
    for k, _ in rows:
        off += len(k)
        offsets.append(off)
    out.append(struct.pack(f"<{len(offsets)}I", *offsets))
    out.append(blob)
    if weighted:
        out.append(struct.pack(f"<{len(rows)}f", *(w for _, w in rows)))
    return b"".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("lexicon", nargs="?")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--w-morph", type=float, default=1.0)
    args = ap.parse_args()

    with open(args.model, encoding="utf-8") as f:
        m = json.load(f)
    a, S, N = m["alpha"], m["S"], m["N"]
    fam_vocab = m["fam_vocab"]

    def contribution(cs, cn, V):
        return math.log((cs + a) / (S + a * V)) - math.log((cn + a) / (N + a * V))

    defaults = [contribution(0, 0, fam_vocab.get(f, 1)) for f in FAMILIES]
    feats = []
    for key, (cs, cn) in m["feats"].items():
        fam, value = key.split(SEP, 1)
        fid = FAMILIES.index(fam)
        feats.append((bytes([fid]) + value.encode("utf-8"), contribution(cs, cn, fam_vocab.get(fam, 1))))

    V = max(1, len(m["word_freq"]))
    total = m["total_words"]
    words = []
    for w, f in m["word_freq"].items():
        if f:
            bonus = m.get("known_bonus", 1.2) + m.get("w_word", 0.6) * math.log((f + a) / (total + a * V))
            words.append((w.encode("utf-8"), bonus))

    nouns, stems = [], []
    if args.lexicon:
        with open(args.lexicon, encoding="utf-8") as f:
            lex = json.load(f)
        nouns = [(w.encode("utf-8"), 0.0) for w in lex.get("noun", {})]
        stems = [(w.encode("utf-8"), 0.0) for w in lex.get("stem", {})]

    prior = math.log((S + a) / (N + a))
    header = b"HSPM" + struct.pack(
        "<IffffI", 1, prior, m.get("space_penalty", 0.0), m.get("oov_char", -0.55),
        args.w_morph if args.lexicon else 0.0, m.get("max_word", 12),
    )
    header += struct.pack("<I", len(FAMILIES)) + struct.pack(f"<{len(FAMILIES)}f", *defaults)
    body = table(feats, True) + table(words, True) + table(nouns, False) + table(stems, False)
    with open(args.output, "wb") as f:
        f.write(header + body)
    print(f"features {len(feats)}, words {len(words)}, nouns {len(nouns)}, stems {len(stems)}, "
          f"{(len(header) + len(body)) / 1e6:.1f} MB -> {args.output}")


if __name__ == "__main__":
    main()
