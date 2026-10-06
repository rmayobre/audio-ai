#!/usr/bin/env python3
"""
Merge a finished book's pronunciations into a shared series glossary so the next book in the same
universe starts with them already filled in.

Usage:
  python update_glossary.py ../output/brothers-war/names.csv ../glossaries/magic-the-gathering.csv
  python update_glossary.py names.csv glossary.csv --dry-run      # show what would change
  python update_glossary.py names.csv glossary.csv --overwrite     # let the book's entries replace existing ones

Only entries with a filled-in pronunciation are copied. Existing glossary entries are kept unless --overwrite
is given; conflicts are always reported. The glossary is written as a `word,pronunciation` CSV sorted by word.
"""
import argparse
import csv
import sys
from pathlib import Path

from epub_to_kokoro import load_pronunciations


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="book pronunciation file (.csv/.json/.py/.txt)")
    ap.add_argument("glossary", help="glossary CSV to create or update")
    ap.add_argument("--overwrite", action="store_true", help="replace existing glossary entries that differ")
    ap.add_argument("--dry-run", action="store_true", help="print the changes without writing")
    args = ap.parse_args()

    gloss_path = Path(args.glossary)
    source = load_pronunciations(args.source)
    glossary = load_pronunciations(gloss_path) if gloss_path.exists() else {}

    added, changed, conflicts = [], [], []
    for word, spoken in source.items():
        if word not in glossary:
            glossary[word] = spoken
            added.append(word)
        elif glossary[word] != spoken:
            if args.overwrite:
                changed.append(f"{word}: {glossary[word]!r} -> {spoken!r}")
                glossary[word] = spoken
            else:
                conflicts.append(f"{word}: keeping {glossary[word]!r}, book has {spoken!r}")

    print(f"{len(added)} added, {len(changed)} replaced, {len(conflicts)} conflicts kept as-is, "
          f"{len(glossary)} total in glossary")
    for line in changed:
        print("  replaced ", line)
    for line in conflicts:
        print("  conflict ", line, "(use --overwrite to replace)")

    if args.dry_run:
        print("Dry run: nothing written.")
        return
    gloss_path.parent.mkdir(parents=True, exist_ok=True)
    with open(gloss_path, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, lineterminator="\n")
        wr.writerow(["word", "pronunciation"])
        wr.writerows(sorted(glossary.items(), key=lambda kv: kv[0].lower()))
    print(f"Wrote {gloss_path}")


if __name__ == "__main__":
    sys.exit(main())
