#!/usr/bin/env python3
"""
List the words in an epub that aren't in an English dictionary (mostly character
and place names), so you can check how Kokoro pronounces them and add fixes to
the PRONUNCIATIONS dictionary in your epub-to-audiobook script.

Usage:
  python find_unknown_words.py book.epub
  python find_unknown_words.py book.epub --min-count 3 --top 100
  python find_unknown_words.py book.epub --known my_words.txt   # extra words to ignore, one per line
  python find_unknown_words.py book.epub --out words.csv        # save the full list; format follows the extension
  python find_unknown_words.py book.epub --out words.py         # save a PRONUNCIATIONS dict template
  python find_unknown_words.py book.epub --out                  # save to <epub name>_unknown_words.txt

Requires: pip install ebooklib beautifulsoup4 pyspellchecker
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from bs4 import BeautifulSoup
from ebooklib import epub, ITEM_DOCUMENT
from spellchecker import SpellChecker

WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)*")


def read_text(epub_path):
    book = epub.read_epub(epub_path, options={"ignore_ncx": True})
    parts = []
    for item in book.get_items_of_type(ITEM_DOCUMENT):
        soup = BeautifulSoup(item.get_content(), "html.parser")
        parts.append(soup.get_text(" "))
    text = " ".join(parts)
    # normalise curly quotes and treat hyphens/dashes as word separators
    text = text.replace("’", "'").replace("‘", "'")
    return re.sub(r"[‐-―-]+", " ", text)


def strip_suffix(word):
    """Reduce possessives and contractions to the base word: Urza's -> Urza, don't stays don't."""
    if word.lower().endswith("'s"):
        return word[:-2]
    if word.lower().endswith("s'"):
        return word[:-1]
    return word


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("epub")
    ap.add_argument("--min-count", type=int, default=2, help="ignore words seen fewer times (default 2)")
    ap.add_argument("--top", type=int, default=80, help="how many to print (default 80)")
    ap.add_argument("--known", help="text file of extra words to treat as known, one per line")
    ap.add_argument("--out", nargs="?", const="", metavar="FILE",
                    help="save the full list to FILE. Format follows the extension: .txt (count<TAB>word), "
                         ".csv, .json, or .py (a PRONUNCIATIONS dict template). "
                         "Give --out with no name to use <epub name>_unknown_words.txt")
    args = ap.parse_args()

    text = read_text(args.epub)
    spell = SpellChecker()

    extra = set()
    if args.known:
        extra = {w.strip().lower() for w in Path(args.known).read_text().splitlines() if w.strip()}

    counts = Counter()                 # lowercase base word -> occurrences
    forms = defaultdict(Counter)       # lowercase base word -> {surface form: occurrences}
    for raw in WORD_RE.findall(text):
        w = strip_suffix(raw)
        if len(w) < 3 or "'" in w:     # skip tiny words and contractions (don't, we'll, ...)
            continue
        low = w.lower()
        counts[low] += 1
        forms[low][w] += 1

    unknown = [w for w in counts if w not in extra and w in spell.unknown([w])]
    rows = sorted(((counts[w], max(forms[w], key=forms[w].get)) for w in unknown), reverse=True)
    rows = [(n, w) for n, w in rows if n >= args.min_count]

    if not rows:
        print("No unknown words found.")
        return

    print(f"{len(rows)} unrecognised words (seen at least {args.min_count} times). Top {min(args.top, len(rows))}:\n")
    for n, w in rows[: args.top]:
        print(f"{n:6}  {w}")

    print("\nPaste-ready template for PRONUNCIATIONS (fill in how each should sound, delete the rest):\n")
    print("PRONUNCIATIONS = {")
    for _, w in rows[: args.top]:
        print(f'    "{w}": "",')
    print("}")

    if args.out is not None:
        out = Path(args.out) if args.out else Path(f"{Path(args.epub).stem}_unknown_words.txt")
        ext = out.suffix.lower()
        if ext == ".csv":
            with open(out, "w", newline="", encoding="utf-8") as f:
                wr = csv.writer(f, lineterminator="\n")
                wr.writerow(["word", "count", "pronunciation"])
                wr.writerows((w, n, "") for n, w in rows)
        elif ext == ".json":
            out.write_text(json.dumps([{"word": w, "count": n} for n, w in rows], indent=2), encoding="utf-8")
        elif ext == ".py":
            body = "".join(f'    "{w}": "",  # seen {n}x\n' for n, w in rows)
            out.write_text(f"PRONUNCIATIONS = {{\n{body}}}\n", encoding="utf-8")
        else:
            out.write_text("".join(f"{n}\t{w}\n" for n, w in rows), encoding="utf-8")
        print(f"\nFull list ({len(rows)} words) saved to {out}")


if __name__ == "__main__":
    sys.exit(main())
