#!/usr/bin/env python3
"""
Hear how Kokoro says a word before committing to a whole book.

For each word it renders one short sentence twice (as written, and with your respelling applied)
so you can compare, and saves the clips as audio files.

Usage:
  python test_pronunciation.py Urza Mishra --pronunciations ../output/brothers-war/names.csv
  python test_pronunciation.py --pronunciations names.csv --max 10        # test the first 10 filled-in entries
  python test_pronunciation.py Tocasia --pronunciations names.csv --fx    # include the deep-voice post-processing
  python test_pronunciation.py Urza --sentence "{word} drew his sword."   # custom sentence, {word} is replaced

Options: --url (default $KOKORO_URL), --voice, --speed, --pitch, --tempo, --out-dir (default <repo>/output/pronunciation_tests)
Requires the same packages as epub_to_kokoro.py, plus a reachable Kokoro-FastAPI server.
"""
import argparse
import os
import re
import sys
from pathlib import Path

from epub_to_kokoro import (DEFAULT_PITCH, DEFAULT_TEMPO, DEFAULT_VOICE, apply_pronunciations,
                            build_filter, load_pronunciations, probe, run, synthesize)

DEFAULT_SENTENCE = "The name {word} echoed through the hall."
DEFAULT_OUT_DIR = Path(__file__).resolve().parent.parent / "output" / "pronunciation_tests"


def slug(word):
    return re.sub(r"[^\w-]+", "_", word).strip("_") or "word"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("words", nargs="*", help="words to test; default: every filled-in entry of the pronunciation files")
    ap.add_argument("--pronunciations", nargs="+", default=[], metavar="FILE")
    ap.add_argument("--url", default=os.environ.get("KOKORO_URL"))
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--fx", action="store_true", help="apply the deep-voice pitch/tempo/bass processing")
    ap.add_argument("--pitch", type=float, default=DEFAULT_PITCH)
    ap.add_argument("--tempo", type=float, default=DEFAULT_TEMPO)
    ap.add_argument("--sentence", default=DEFAULT_SENTENCE)
    ap.add_argument("--max", type=int, default=20, help="limit when testing a whole file (default 20)")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                    help="where the clips go (default: <repo>/output/pronunciation_tests)")
    args = ap.parse_args()

    if not args.url:
        sys.exit("No server URL. Pass --url or set KOKORO_URL.")
    if "{word}" not in args.sentence:
        sys.exit("--sentence must contain {word}")

    table = {}
    for f in args.pronunciations:
        table.update(load_pronunciations(f))

    targets = args.words or list(table)[: args.max]
    if not targets:
        sys.exit("Nothing to test: give words, or a pronunciation file with filled-in entries.")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    for word in targets:
        variants = [("as_written", word)]
        if word in table:
            variants.append(("respelled", apply_pronunciations(word, {word: table[word]})))
        for label, spoken in variants:
            text = args.sentence.format(word=spoken)
            dest = out / f"{slug(word)}_{label}.flac"
            raw = out / f".raw_{dest.name}"
            synthesize(args.url, args.voice, args.speed, text, raw if args.fx else dest)
            if args.fx:
                sr = int(probe(raw, "stream=sample_rate", stream=True))
                run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-af",
                     build_filter(sr, args.pitch, args.tempo), "-c:a", "flac", str(dest)])
                raw.unlink()
            print(f"{dest}   [{spoken}]")

    print(f"\nListen to the clips in {out}/ and adjust the respellings that still sound wrong.")


if __name__ == "__main__":
    main()
