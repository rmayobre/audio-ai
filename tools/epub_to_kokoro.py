#!/usr/bin/env python3
"""
Convert an epub into a single chaptered audiobook using a Kokoro-FastAPI server.

Pipeline:
  epub -> prologue/chapters/interludes/epilogue (in reading order)
       -> paragraph chunks -> Kokoro (/v1/audio/speech) -> chapter_XX.flac
       -> one combined .m4b with chapter markers

Deep voice = a blend of deep male voices on the server, plus an ffmpeg
post-process (pitch drop, slight slowdown, low-shelf boost) on each chapter.

Usage:
  python epub_to_kokoro.py book.epub
  python epub_to_kokoro.py book.epub --url http://localhost:8880 --out arthas.m4b
  python epub_to_kokoro.py book.epub --voice am_onyx --no-fx      # plain voice, no post-processing
  python epub_to_kokoro.py book.epub --list                       # just show which sections it would read
  python epub_to_kokoro.py book.epub --pronunciations words.csv   # respell words from a file (csv/json/py/txt)
  python epub_to_kokoro.py book.epub --pronunciations ../glossaries/series.csv words.csv   # later files win
  KOKORO_URL=https://kokoro.example.com python epub_to_kokoro.py book.epub   # URL from the environment

Pronunciation files (empty pronunciations are ignored):
  words.csv   word,count,pronunciation        (what find_unknown_words.py --out words.csv writes)
  words.json  {"Urza": "Er-zuh"}  or  [{"word": "Urza", "pronunciation": "Er-zuh"}]
  words.py    PRONUNCIATIONS = {"Urza": "Er-zuh"}
  words.txt   Urza = Er-zuh        (one per line, '#' comments)
Chapters already finished are skipped on a rerun, so delete chapter_XX.flac for any chapter you want redone
with new pronunciations.

Requires: pip install ebooklib beautifulsoup4 requests ; ffmpeg + ffprobe on PATH.
Re-running resumes: chapters whose chapter_XX.flac already exists are skipped.

Logging: every line is timestamped, flushed immediately (safe to redirect to a file or `tail -f`) and also
appended to <work>/convert.log (change with --log). It reports per-chunk progress, elapsed time, an ETA, how
often each respelling was applied, retries, ffmpeg failures (full stderr goes to the log) and a final summary.
"""
import argparse
import ast
import csv
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from ebooklib import epub

# ---------------------------------------------------------------- settings
DEFAULT_VOICE = "am_onyx(4)+am_adam(1)"  # Kokoro-FastAPI weighted blend; use plain "am_onyx" if rejected
DEFAULT_PITCH = 0.94    # <1 lowers pitch (0.94 is about -1 semitone)
DEFAULT_TEMPO = 0.90    # final playback speed after the pitch change
BASS_GAIN_DB = 4        # low-shelf boost around 150 Hz
CHUNK_CHARS = 2500      # max characters per request, split at paragraph/sentence edges

# Sections to read even if short (matched against the start of the section text)
INCLUDE_RE = re.compile(
    r"^\W*(prologue|prelude|chapter|epilogue|interlude|introduction|foreword|preface|afterword|part\s+\w+)\b",
    re.I,
)
# Sections to skip (front/back matter)
SKIP_RE = re.compile(
    r"^\W*(contents|table of contents|copyright|about the author|acknowledg\w*|dedication|"
    r"also by|notes|praise|title page|cover|map|glossary|discussion)\b",
    re.I,
)
MIN_CHARS_OTHER = 3000  # sections matching neither pattern are kept only if at least this long

# Respell words the model mispronounces: {"as written": "how it should sound"}
PRONUNCIATIONS = {
    # "Jaina": "Jayna",
}
# -------------------------------------------------------------------------


LOG_FILE = None


def log(msg=""):
    """Print a timestamped line, flushed right away, and append it to LOG_FILE when one is set."""
    line = f"{time.strftime('%H:%M:%S')} {msg}" if msg else ""
    print(line, flush=True)
    if LOG_FILE:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d')} {line}\n")


def fmt_secs(sec):
    sec = int(sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log(f"Command failed (exit {r.returncode}): {' '.join(cmd)}\n{r.stderr}")  # full stderr goes to the log
        sys.exit(f"Command failed: {' '.join(cmd)}\n{r.stderr[-1500:]}")
    return r.stdout


def probe(path, entry, stream=False):
    sel = ["-select_streams", "a:0"] if stream else []
    out = run(["ffprobe", "-v", "error", *sel, "-show_entries", entry,
               "-of", "default=nw=1:nk=1", str(path)])
    return out.strip()


def extract_sections(epub_path):
    """Return [(title, text)] in reading (spine) order, filtered to real story sections."""
    book = epub.read_epub(epub_path, options={"ignore_ncx": True})
    sections = []
    for idref, _linear in book.spine:
        item = book.get_item_with_id(idref)
        if item is None or not item.get_name().lower().endswith((".html", ".xhtml", ".htm")):
            continue
        soup = BeautifulSoup(item.get_content(), "html.parser")
        paras = [re.sub(r"\s+", " ", p.get_text(" ", strip=True)) for p in soup.find_all(["h1", "h2", "h3", "p"])]
        paras = [p for p in paras if p]
        text = "\n".join(paras)
        if not text:
            continue
        head = text[:200]
        if SKIP_RE.match(head):
            continue
        if not INCLUDE_RE.match(head) and len(text) < MIN_CHARS_OTHER:
            continue
        title = re.split(r"(?<=[.!?:])\s", paras[0], maxsplit=1)[0][:60].strip(" .") or f"Section {len(sections) + 1}"
        sections.append((title.title() if title.isupper() else title, text))
    return sections


def load_pronunciations(path, keep_blank=False):
    """Read a {word: pronunciation} table from a file. Entries with an empty pronunciation are skipped.

    A blank pronunciation (e.g. `Urza,` or just `Urza`) means "leave Kokoro's own pronunciation alone", so the
    word is never respelled. Pass keep_blank=True to keep those rows (value ""), which is how glossaries record
    that a word was reviewed and Kokoro's version was chosen.

    .csv   header row with 'word' and 'pronunciation' columns (the file from find_unknown_words.py --out x.csv)
    .json  {"word": "pronunciation"}  or  [{"word": ..., "pronunciation": ...}]
    .py    a file containing  PRONUNCIATIONS = {...}  (read safely, never executed)
    other  one entry per line:  word = pronunciation   (or tab separated); '#' starts a comment
    """
    p = Path(path)
    if not p.exists():
        sys.exit(f"Pronunciation file not found: {p}")
    ext = p.suffix.lower()
    table = {}
    if ext == ".csv":
        with open(p, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                table[row.get("word", "")] = row.get("pronunciation", "")
    elif ext == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            table = {str(k): str(v) for k, v in data.items()}
        else:
            table = {str(d.get("word", "")): str(d.get("pronunciation", "")) for d in data}
    elif ext == ".py":
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in tree.body:
            if (isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "PRONUNCIATIONS" for t in node.targets)):
                table = ast.literal_eval(node.value)
        if not table:
            sys.exit(f"No PRONUNCIATIONS = {{...}} found in {p}")
    else:
        for line in p.read_text(encoding="utf-8").splitlines():
            line = re.split(r"(?:^|\s)#", line, maxsplit=1)[0].strip()  # '#' starts a comment
            if not line:
                continue
            sep = "\t" if "\t" in line else "="
            if sep not in line:
                continue
            word, spoken = line.split(sep, 1)
            table[word.strip()] = spoken.strip()
    return {w.strip(): (s or "").strip() for w, s in table.items()
            if w.strip() and (keep_blank or (s or "").strip())}


def apply_pronunciations(text, table, hits=None):
    """Replace each whole word (case-sensitive, longest first) with its pronunciation.
    If `hits` (a Counter) is given, it is incremented for every replacement made."""
    if not table:
        return text
    words = sorted(table, key=len, reverse=True)
    pattern = re.compile(r"\b(?:" + "|".join(re.escape(w) for w in words) + r")\b")

    def sub(m):
        if hits is not None:
            hits[m.group(0)] += 1
        return table[m.group(0)]
    return pattern.sub(sub, text)


def chunk_text(text, limit=CHUNK_CHARS):
    chunks, cur = [], ""
    for para in text.split("\n"):
        pieces = [para] if len(para) <= limit else re.split(r"(?<=[.!?])\s+", para)
        for piece in pieces:
            if cur and len(cur) + len(piece) + 1 > limit:
                chunks.append(cur)
                cur = ""
            cur = f"{cur}\n{piece}" if cur else piece
        if cur and len(cur) > limit * 0.7:  # keep paragraph-ish boundaries
            chunks.append(cur)
            cur = ""
    if cur:
        chunks.append(cur)
    return chunks


def synthesize(url, voice, speed, text, dest, retries=3, label="chunk"):
    payload = {"model": "kokoro", "input": text, "voice": voice,
               "response_format": "flac", "speed": speed}
    for attempt in range(1, retries + 1):
        try:
            r = requests.post(f"{url}/v1/audio/speech", json=payload, timeout=900)
            if r.status_code == 200 and r.content:
                dest.write_bytes(r.content)
                return
            err = f"HTTP {r.status_code}: {r.text[:300]}"
        except requests.RequestException as e:
            err = str(e)
        log(f"    {label}: attempt {attempt}/{retries} failed: {err}")
        if r_is_voice_error(err):
            sys.exit("The server rejected the voice. Try --voice am_onyx (no blend syntax).")
        if attempt < retries:
            log(f"    {label}: retrying in {3 * attempt}s")
            time.sleep(3 * attempt)
    log(f"    {label}: giving up after {retries} attempts")
    sys.exit("Giving up on a chunk after repeated failures.")


def r_is_voice_error(err):
    return "voice" in err.lower() and ("not found" in err.lower() or "invalid" in err.lower())


def build_filter(sr, pitch, tempo):
    # asetrate shifts pitch (and speed by the same factor); atempo then sets the final speed.
    return (f"asetrate={int(sr * pitch)},aresample={sr},"
            f"atempo={tempo / pitch:.5f},bass=g={BASS_GAIN_DB}:f=150")


def concat_line(path):
    # ffmpeg concat list entries are single-quoted; a literal ' must be written as '\''
    return "file '" + str(Path(path).resolve()).replace("'", "'\\''") + "'\n"


def concat_to_chapter(chunk_files, dest, work, fx):
    lst = work / f"{dest.stem}_list.txt"
    lst.write_text("".join(concat_line(c) for c in chunk_files))
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst)]
    if fx:
        sr = int(probe(chunk_files[0], "stream=sample_rate", stream=True))
        cmd += ["-af", build_filter(sr, *fx)]
    cmd += ["-c:a", "flac", str(dest)]
    run(cmd)


def ff_escape(s):
    return re.sub(r"([=;#\\\n])", r"\\\1", s)


def combine(chapter_files, titles, out_path, work):
    # chapter markers
    meta = [";FFMETADATA1", f"title={ff_escape(out_path.stem)}"]
    t = 0
    for f, title in zip(chapter_files, titles):
        dur_ms = int(float(probe(f, "format=duration")) * 1000)
        meta += ["[CHAPTER]", "TIMEBASE=1/1000", f"START={t}", f"END={t + dur_ms}",
                 f"title={ff_escape(title)}"]
        t += dur_ms
    meta_file = work / "chapters_meta.txt"
    meta_file.write_text("\n".join(meta) + "\n")

    lst = work / "all_chapters.txt"
    lst.write_text("".join(concat_line(f) for f in chapter_files))

    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
           "-i", str(meta_file), "-map", "0:a", "-map_metadata", "1", "-map_chapters", "1",
           "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart"]
    if out_path.suffix.lower() == ".m4b":
        cmd += ["-f", "ipod"]
    cmd.append(str(out_path))
    run(cmd)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("epub")
    ap.add_argument("--url", default=os.environ.get("KOKORO_URL", "http://localhost:8880"),
                    help="Kokoro-FastAPI base URL (default: $KOKORO_URL, else http://localhost:8880)")
    ap.add_argument("--voice", default=DEFAULT_VOICE)
    ap.add_argument("--speed", type=float, default=1.0, help="server-side speed (keep near 1.0)")
    ap.add_argument("--pitch", type=float, default=DEFAULT_PITCH)
    ap.add_argument("--tempo", type=float, default=DEFAULT_TEMPO)
    ap.add_argument("--no-fx", action="store_true", help="skip the deep-voice ffmpeg post-processing")
    ap.add_argument("--out", help="output file (.m4b or .mp3/.m4a); default: <epub name>.m4b")
    ap.add_argument("--work", help="folder for chapter files; default: <epub name>_chapters")
    ap.add_argument("--list", action="store_true", help="only list the sections that would be read")
    ap.add_argument("--log", help="log file to append to; default: <work>/convert.log")
    ap.add_argument("--pronunciations", nargs="+", metavar="FILE", default=[],
                    help="one or more files of words and how they should sound (.csv, .json, .py or .txt). "
                         "Later files override earlier ones, and all override the PRONUNCIATIONS dict in this script")
    args = ap.parse_args()

    pron = dict(PRONUNCIATIONS)
    for pfile in args.pronunciations:
        loaded = load_pronunciations(pfile)
        pron.update(loaded)
        log(f"Loaded {len(loaded)} pronunciations from {pfile}")

    stem = Path(args.epub).stem
    out_path = Path(args.out) if args.out else Path(f"{stem}.m4b")
    safe_stem = re.sub(r"[^\w.-]+", "_", stem).strip("_")  # no spaces/apostrophes in folder names
    work = Path(args.work) if args.work else Path(f"{safe_stem}_chapters")

    sections = extract_sections(args.epub)
    if not sections:
        sys.exit("No readable sections found.")
    log(f"{len(sections)} sections:")
    for i, (title, text) in enumerate(sections, 1):
        log(f"  {i:02d}  {len(text):>6} chars  {title}")
    if args.list:
        return

    work.mkdir(exist_ok=True)
    global LOG_FILE
    LOG_FILE = Path(args.log) if args.log else work / "convert.log"
    log(f"Logging to {LOG_FILE}; server {args.url}; voice {args.voice}; pitch {args.pitch} tempo {args.tempo}"
        + (" (no fx)" if args.no_fx else ""))
    fx = None if args.no_fx else (args.pitch, args.tempo)
    chapter_files, titles = [], []
    hits = Counter()
    todo_chars = sum(len(t) for k, (_, t) in enumerate(sections, 1) if not (work / f"chapter_{k:02d}.flac").exists())
    done_chars = 0
    started = time.time()

    for i, (title, text) in enumerate(sections, 1):
        chapter = work / f"chapter_{i:02d}.flac"
        chapter_files.append(chapter)
        titles.append(title)
        if chapter.exists():
            log(f"[{i}/{len(sections)}] {title}: already done, skipping")
            continue
        chunks = chunk_text(apply_pronunciations(text, pron, hits))
        log(f"[{i}/{len(sections)}] {title}: {len(text)} chars, {len(chunks)} chunks")
        chapter_start = time.time()
        chunk_files = []
        for j, chunk in enumerate(chunks, 1):
            cf = work / f"chapter_{i:02d}_part_{j:03d}.flac"
            if cf.exists() and cf.stat().st_size > 0:  # reuse chunks from an interrupted run
                log(f"    chunk {j}/{len(chunks)}: reusing existing file")
            else:
                t0 = time.time()
                synthesize(args.url, args.voice, args.speed, chunk, cf, label=f"chunk {j}/{len(chunks)}")
                log(f"    chunk {j}/{len(chunks)}: {len(chunk)} chars in {fmt_secs(time.time() - t0)}")
            chunk_files.append(cf)
        concat_to_chapter(chunk_files, chapter, work, fx)
        for cf in chunk_files:
            cf.unlink()
        done_chars += len(text)
        elapsed = time.time() - started
        eta = elapsed / done_chars * (todo_chars - done_chars) if done_chars else 0
        audio = float(probe(chapter, "format=duration"))
        log(f"[{i}/{len(sections)}] {title}: done in {fmt_secs(time.time() - chapter_start)}, "
            f"{fmt_secs(audio)} of audio. Elapsed {fmt_secs(elapsed)}, about {fmt_secs(eta)} left")

    if pron:
        used = ", ".join(f"{w} x{n}" for w, n in hits.most_common()) or "none"
        log(f"Pronunciations applied this run: {used}")

    log("Combining chapters...")
    combine(chapter_files, titles, out_path, work)
    total = sum(float(probe(f, "format=duration")) for f in chapter_files)
    n_chap = len(probe(out_path, "chapter=id").splitlines())
    log(f"Done: {out_path} ({out_path.stat().st_size / 1e6:.1f} MB, {fmt_secs(total)} of audio, "
        f"{n_chap} chapter markers, {fmt_secs(time.time() - started)} this run)")


if __name__ == "__main__":
    main()
