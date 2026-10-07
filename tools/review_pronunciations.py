#!/usr/bin/env python3
"""
Listen to the pronunciation tests two clips at a time and pick the one that sounds best. The glossary is then
updated: the respelling is kept when you pick it, and the second column is left blank when you pick Kokoro's own
pronunciation (blank means "leave Kokoro alone", so that word is not sent as a correction).

Run tools/test_glossary.py first; it writes the clips and a manifest.json into output/pronunciation_tests/<glossary>/.

Usage:
  python review_pronunciations.py                                   # every test folder under output/pronunciation_tests
  python review_pronunciations.py ../output/pronunciation_tests/warcraft
  python review_pronunciations.py warcraft                          # a test folder by glossary name
  python review_pronunciations.py warcraft --shuffle                # randomise which clip plays first (blind test)
  python review_pronunciations.py warcraft --redo                   # ask again about words already decided
  python review_pronunciations.py warcraft --apply                  # write decisions made so far, without finishing
  python review_pronunciations.py --dry-run                         # show what would change, write nothing

For each word you hear clip 1, then clip 2, then choose:
  1  clip 1 sounds best      2  clip 2 sounds best      r  hear both again      (q  save progress and quit)
By default clip 1 is Kokoro's own pronunciation (the word as written) and clip 2 is the respelling.

Once a word is decided, its two clips are moved into clips/reviewed/ next to the others, and clips in a folder
called "reviewed" are ignored on later runs (they are not played again). Use --redo to review them again.

Choices are saved to review_results.json after every word, so you can quit and resume later. The glossary is
updated once every word has been decided, or earlier with --apply. Needs a terminal to answer in and an audio player
(see play_audio.py --list-players). Note: a book's own output/<slug>/words.csv is applied after the glossary and
still wins for that book, so edit it too if a book already carries the old respelling.
"""
import argparse
import csv
import json
import random
import sys
import time
from pathlib import Path

from epub_to_kokoro import load_pronunciations
from play_audio import play

TESTS_DIR = Path(__file__).resolve().parent.parent / "output" / "pronunciation_tests"
PAUSE_BETWEEN_CLIPS = 0.4
REVIEWED = "reviewed"  # clips in a folder with this name are finished with and ignored


def find_test_dirs(targets):
    """Resolve CLI targets (a folder, or a glossary name) to folders holding a manifest.json."""
    if not targets:
        dirs = sorted(p.parent for p in TESTS_DIR.glob("*/manifest.json"))
        if not dirs:
            sys.exit(f"No pronunciation tests found in {TESTS_DIR}. Run tools/test_glossary.py first.")
        return dirs
    dirs = []
    for t in targets:
        for cand in (Path(t), TESTS_DIR / t):
            if (cand / "manifest.json").exists():
                dirs.append(cand)
                break
        else:
            sys.exit(f"No manifest.json in {t} (or {TESTS_DIR / t}). Run tools/test_glossary.py first.")
    return dirs


def locate(folder, rel):
    """The clip's path if it is where the manifest says, else its copy in the sibling reviewed/ folder, else None."""
    p = folder / rel
    if p.exists():
        return p
    moved = p.parent / REVIEWED / p.name
    return moved if moved.exists() else None


def move_to_reviewed(folder, entry):
    """Move the entry's clips into reviewed/ (replacing any older copy there)."""
    for key in ("as_written", "respelled"):
        src = folder / entry[key]
        if src.exists():
            (src.parent / REVIEWED).mkdir(exist_ok=True)
            src.replace(src.parent / REVIEWED / src.name)


def ask(prompt):
    """Read one choice; returns '1', '2', 'r' or 'q'."""
    while True:
        try:
            ans = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "q"
        if ans in ("1", "2", "r", "q"):
            return ans
        print("  Please type 1, 2, r (hear both again) or q (save and quit).")


def play_pair(first, second):
    print("  clip 1 ...", flush=True)
    play(first)
    time.sleep(PAUSE_BETWEEN_CLIPS)
    print("  clip 2 ...", flush=True)
    play(second)


def write_glossary(path, updates):
    """Apply {word: respelling or ""} to the glossary CSV, keeping every other row; blank = Kokoro's own."""
    rows = load_pronunciations(path, keep_blank=True)
    rows.update(updates)
    with open(path, "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, lineterminator="\n")
        wr.writerow(["word", "pronunciation"])
        wr.writerows(sorted(rows.items(), key=lambda kv: kv[0].lower()))


def review_dir(folder, args):
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    glossary = Path(manifest["glossary"])
    entries = [e for e in manifest["entries"] if e.get("as_written") and e.get("respelled")]
    skipped = len(manifest["entries"]) - len(entries)
    results_file = folder / "review_results.json"
    results = json.loads(results_file.read_text(encoding="utf-8")) if results_file.exists() else {}

    persist = not args.dry_run  # a dry run neither saves choices nor moves clips

    def is_decided(e):  # a decision belongs to a specific respelling; if the glossary changed since, ask again
        return results.get(e["word"], {}).get("respelling") == e["respelling"]

    if persist:  # housekeeping: clips of words decided earlier belong in reviewed/
        for e in entries:
            if is_decided(e):
                move_to_reviewed(folder, e)

    # clips in reviewed/ are ignored unless --redo. The as-written clip may be reused from reviewed/, because it
    # does not change when only the respelling does.
    todo = [e for e in entries
            if locate(folder, e["as_written"])
            and ((folder / e["respelled"]).exists() and not is_decided(e)
                 or (args.redo and locate(folder, e["respelled"])))]
    print(f"\n=== {glossary.name}: {len(entries)} words with two clips, {sum(map(is_decided, entries))} decided, "
          f"{len(todo)} to review" + (f" ({skipped} without an as-written clip skipped)" if skipped else ""))

    if not args.apply:
        order = random.sample(todo, len(todo)) if args.shuffle_words else todo
        for n, e in enumerate(order, 1):
            clips = [("native", locate(folder, e["as_written"])), ("respelled", locate(folder, e["respelled"]))]
            if args.shuffle:
                random.shuffle(clips)
            print(f"\n[{n}/{len(order)}] {e['word']}   (respelling: {e['respelling']})" if args.show_respelling
                  else f"\n[{n}/{len(order)}] {e['word']}")
            play_pair(clips[0][1], clips[1][1])
            while True:
                ans = ask("  1 = clip 1 best, 2 = clip 2 best, r = hear both again, q = save and quit > ")
                if ans != "r":
                    break
                play_pair(clips[0][1], clips[1][1])
            if ans == "q":
                break
            picked = clips[int(ans) - 1][0]
            results[e["word"]] = {"choice": picked, "respelling": e["respelling"]}
            if persist:
                results_file.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
                move_to_reviewed(folder, e)
            print("  -> " + (f"keep Kokoro's own pronunciation of {e['word']} (second column left blank)"
                             if picked == "native" else f"use the respelling {e['respelling']!r}"))

    decided = {e["word"]: results[e["word"]] for e in entries if is_decided(e)}
    remaining = len(entries) - len(decided)
    if remaining and not args.apply:
        print(f"\n{remaining} word(s) in {folder.name} still undecided; the glossary was not changed. "
              "Run again to continue, or use --apply to write the decisions made so far.")
        return False
    if not decided:
        print("Nothing decided yet.")
        return False

    updates = {w: ("" if r["choice"] == "native" else r["respelling"]) for w, r in decided.items()}
    current = load_pronunciations(glossary, keep_blank=True)
    changes = {w: v for w, v in updates.items() if current.get(w) != v}
    blanked = [w for w, v in changes.items() if v == ""]
    print(f"\n{glossary.name}: {len(updates)} decided, {len(changes)} change(s), "
          f"{len(blanked)} set to Kokoro's own pronunciation (blank)")
    for w, v in sorted(changes.items(), key=lambda kv: kv[0].lower()):
        print(f"  {w}: {current.get(w)!r} -> {v!r}")
    if args.dry_run:
        print("Dry run: glossary not written.")
        return True
    if changes:
        write_glossary(glossary, changes)
        print(f"Updated {glossary}")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("tests", nargs="*", metavar="TEST_DIR",
                    help="test folder or glossary name (default: every folder in output/pronunciation_tests)")
    ap.add_argument("--shuffle", action="store_true", help="randomise which clip plays first, per word (blind test)")
    ap.add_argument("--shuffle-words", action="store_true", help="randomise the order of the words")
    ap.add_argument("--show-respelling", action="store_true", help="print the respelling next to each word")
    ap.add_argument("--redo", action="store_true", help="ask again about words that were already decided")
    ap.add_argument("--apply", action="store_true", help="write the decisions made so far without asking more")
    ap.add_argument("--dry-run", action="store_true", help="show what would change in the glossary, write nothing")
    args = ap.parse_args()

    for folder in find_test_dirs(args.tests):
        try:
            review_dir(folder, args)
        except (FileNotFoundError, RuntimeError) as e:
            sys.exit(f"review_pronunciations: {e}")


if __name__ == "__main__":
    main()
