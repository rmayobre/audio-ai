#!/usr/bin/env python3
"""
Hear every pronunciation in the glossaries so wrong respellings can be found and fixed.

For each glossary entry it renders one short sentence as written and respelled (through Kokoro, with the same
deep-voice processing as a real run), then joins the clips into ONE review file per glossary with short pauses,
plus a timestamped index so you can jump to a word and note which ones sound wrong.

Usage:
  python test_glossary.py                                  # every glossaries/*.csv
  python test_glossary.py ../glossaries/warcraft.csv       # one glossary
  python test_glossary.py warcraft --words Jaina Muradin   # a glossary by name, only some words
  python test_glossary.py warcraft --respelled-only        # skip the "as written" clip of each pair
  python test_glossary.py --list                           # show what would be tested, no server needed
  python test_glossary.py warcraft --max 20 --start 40     # entries 41-60 only

Output (default <repo>/output/pronunciation_tests/<glossary>/, which git ignores):
  <glossary>_review.flac   as written, pause, respelled, longer pause, next word...
  <glossary>_review.txt    mm:ss  word -> respelling   (open next to the audio)
  clips/                   one flac per clip; reused on reruns, a changed respelling gets a new clip
  clips/reviewed/          clips review_pronunciations.py has finished with (reused, never played again)
  manifest.json            which clips belong to which word; read by review_pronunciations.py

Entries whose pronunciation is blank in the glossary are skipped: blank means "keep Kokoro's own pronunciation".
After listening, run review_pronunciations.py to choose the best clip for each word and update the glossary.

Options: --url (default $KOKORO_URL), --profile NAME, --voice, --speed, --no-fx, --pitch, --tempo, --bass, --sentence, --out-dir
Requires the same packages as epub_to_kokoro.py, plus a reachable Kokoro-FastAPI server.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from epub_to_kokoro import (add_voice_args, build_filter, concat_line, fmt_secs, load_pronunciations, log, probe,
                            resolve_voice, run, synthesize)
from test_pronunciation import DEFAULT_SENTENCE, slug

REPO_ROOT = Path(__file__).resolve().parent.parent
GLOSSARY_DIR = REPO_ROOT / "glossaries"
DEFAULT_OUT_DIR = REPO_ROOT / "output" / "pronunciation_tests"
PAUSE_WITHIN = 0.6   # seconds between the as-written and respelled clip
PAUSE_BETWEEN = 1.4  # seconds between words


def resolve_glossary(arg):
    """Accept a path, or a bare name such as 'warcraft' (looked up in glossaries/)."""
    p = Path(arg)
    if p.exists():
        return p
    for cand in (GLOSSARY_DIR / arg, GLOSSARY_DIR / f"{arg}.csv"):
        if cand.exists():
            return cand
    sys.exit(f"Glossary not found: {arg}")


def render_clip(text, dest, args):
    """Synthesize `text` to dest (a flac), with the deep-voice processing unless --no-fx.
    A clip already moved to clips/reviewed/ by review_pronunciations.py is reused, not rendered again.
    Returns the path of the clip that exists."""
    for existing in (dest, dest.parent / "reviewed" / dest.name):
        if existing.exists() and existing.stat().st_size > 0:
            return existing
    raw = dest.with_name(f".raw_{dest.name}")
    synthesize(args.url, args.voice, args.speed, text, raw if args.fx else dest, label=dest.stem)
    if args.fx:
        sr = int(probe(raw, "stream=sample_rate", stream=True))
        run(["ffmpeg", "-y", "-v", "error", "-i", str(raw), "-af",
             build_filter(sr, args.pitch, args.tempo, args.bass_db), "-c:a", "flac", str(dest)])
        raw.unlink()
    return dest


def make_silence(seconds, like, dest):
    """A silent flac with the same sample rate and channel count as the clip `like`."""
    sr = probe(like, "stream=sample_rate", stream=True)
    ch = int(probe(like, "stream=channels", stream=True))
    layout = "mono" if ch == 1 else "stereo"
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"anullsrc=r={sr}:cl={layout}",
         "-t", str(seconds), "-c:a", "flac", str(dest)])


def test_glossary(path, args):
    table = load_pronunciations(path)
    words = [w for w in table if not args.words or w in args.words]
    missing = [w for w in (args.words or []) if w not in table]
    if missing:
        log(f"{path.name}: not in this glossary: {', '.join(missing)}")
    words = words[args.start:][: args.max] if args.max else words[args.start:]
    if not words:
        log(f"{path.name}: nothing to test")
        return
    blanks = len(load_pronunciations(path, keep_blank=True)) - len(table)
    log(f"{path.name}: {len(words)} of {len(table)} entries"
        + (f" ({blanks} blank entries skipped: Kokoro's own pronunciation is kept)" if blanks else ""))
    if args.list:
        for w in words:
            log(f"  {w} -> {table[w]}")
        return

    out = Path(args.out_dir) / path.stem
    clips = out / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    started = time.time()

    sequence, index, manifest = [], [], []  # clips in order; (word, respelling, clips per word); per-word clip paths
    for n, word in enumerate(words, 1):
        spoken = table[word]
        pair, entry = [], {"word": word, "respelling": spoken, "as_written": None, "respelled": None}
        if not args.respelled_only:
            pair.append(("as_written", word))
        pair.append(("respelled", spoken))
        for label, said in pair:
            dest = clips / f"{slug(word)}_{label}_{slug(said)}.flac"
            sequence.append(render_clip(args.sentence.format(word=said), dest, args))
            entry[label] = str(dest.relative_to(out))
        manifest.append(entry)
        index.append((word, spoken, len(pair)))
        log(f"  [{n}/{len(words)}] {word} -> {spoken}")

    # join the clips: pause after each clip within a word, a longer one after the word's last clip
    silence_in, silence_out = out / ".pause_in.flac", out / ".pause_out.flac"
    make_silence(PAUSE_WITHIN, sequence[0], silence_in)
    make_silence(PAUSE_BETWEEN, sequence[0], silence_out)

    lines, offsets, t, k = [], [], 0.0, 0
    for word, spoken, count in index:
        offsets.append((t, word, spoken))
        for c in range(count):
            clip = sequence[k]
            k += 1
            gap = silence_out if c == count - 1 else silence_in
            lines += [concat_line(clip), concat_line(gap)]
            t += float(probe(clip, "format=duration")) + (PAUSE_BETWEEN if gap is silence_out else PAUSE_WITHIN)

    lst = out / "review_list.txt"
    lst.write_text("".join(lines))
    review = out / f"{path.stem}_review.flac"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c:a", "flac", str(review)])
    for f in (lst, silence_in, silence_out):
        f.unlink()

    (out / f"{path.stem}_review.txt").write_text("".join(
        f"{int(off // 60):02d}:{int(off % 60):02d}  {w} -> {s}\n" for off, w, s in offsets))
    (out / "manifest.json").write_text(json.dumps(
        {"glossary": str(path.resolve()), "entries": manifest}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log(f"{path.name}: wrote {review} ({fmt_secs(t)}) and its index in {fmt_secs(time.time() - started)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("glossaries", nargs="*", metavar="GLOSSARY",
                    help="glossary file or bare name (default: every glossaries/*.csv)")
    ap.add_argument("--words", nargs="+", metavar="WORD", help="only test these words")
    ap.add_argument("--max", type=int, default=0, help="test at most this many entries (default: all)")
    ap.add_argument("--start", type=int, default=0, help="skip the first N entries")
    ap.add_argument("--respelled-only", action="store_true", help="skip the as-written clip")
    ap.add_argument("--list", action="store_true", help="show what would be tested and exit (no server needed)")
    ap.add_argument("--url", default=os.environ.get("KOKORO_URL"))
    add_voice_args(ap)
    ap.add_argument("--sentence", default=DEFAULT_SENTENCE)
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                    help="where the review files go (default: <repo>/output/pronunciation_tests)")
    args = ap.parse_args()
    resolve_voice(args)

    if "{word}" not in args.sentence:
        sys.exit("--sentence must contain {word}")
    if not args.list and not args.url:
        sys.exit("No server URL. Pass --url or set KOKORO_URL.")

    paths = [resolve_glossary(g) for g in args.glossaries] or sorted(GLOSSARY_DIR.glob("*.csv"))
    if not paths:
        sys.exit(f"No glossaries found in {GLOSSARY_DIR}")
    for p in paths:
        test_glossary(p, args)
    if not args.list:
        log(f"Listen to the *_review.flac files in {args.out_dir}/ with the .txt index beside them, or run "
            "tools/review_pronunciations.py to pick the best clip for each word and update the glossary.")


if __name__ == "__main__":
    main()
