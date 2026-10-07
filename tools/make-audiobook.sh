#!/usr/bin/env bash
# Two-phase wrapper around the audiobook tools.
#
#   Phase 1 (first run for a book): finds unrecognised words and writes output/<slug>/words.csv, then stops
#           so you can fill in the pronunciation column.
#   Phase 2 (run it again):         converts the epub with those pronunciations into output/<slug>/<slug>.m4b.
#
# usage: tools/make-audiobook.sh EPUB SLUG [options] [-- extra epub_to_kokoro.py args]
#   --glossary FILE   shared pronunciations to apply first (repeatable); the book's words.csv always wins
#   --url URL         Kokoro server URL (default: $KOKORO_URL)
#   --list            only preview which sections would be read
#   --refresh         regenerate words.csv even if it exists (overwrites it!)
#
# examples:
#   tools/make-audiobook.sh "books/The Brothers' War - Jeff Grubb (1998).epub" brothers-war \
#       --glossary glossaries/magic-the-gathering.csv
#   tools/make-audiobook.sh "books/Arthas.epub" arthas -- --tempo 0.88 --voice am_onyx
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TOOLS="$ROOT/tools"

if [ $# -lt 2 ]; then sed -n '2,22p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 1; fi
EPUB="$1"; SLUG="$2"; shift 2

URL="${KOKORO_URL:-}"; GLOSSARIES=(); LIST=0; REFRESH=0; EXTRA=()
while [ $# -gt 0 ]; do
  case "$1" in
    --glossary) GLOSSARIES+=("$2"); shift 2 ;;
    --url)      URL="$2"; shift 2 ;;
    --list)     LIST=1; shift ;;
    --refresh)  REFRESH=1; shift ;;
    --)         shift; EXTRA=("$@"); break ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

[ -f "$EPUB" ] || { echo "Epub not found: $EPUB" >&2; exit 1; }
[ -f "$ROOT/.venv/bin/activate" ] && source "$ROOT/.venv/bin/activate"
command -v ffmpeg >/dev/null || { echo "ffmpeg is required but not on PATH" >&2; exit 1; }

OUT="$ROOT/output/$SLUG"
WORDS="$OUT/words.csv"
mkdir -p "$OUT"
# books started before the rename have names.csv: move it so their respellings keep working
if [ ! -f "$WORDS" ] && [ -f "$OUT/names.csv" ]; then
  mv "$OUT/names.csv" "$WORDS"
  echo "Renamed $OUT/names.csv to words.csv"
fi

if [ "$LIST" -eq 1 ]; then
  exec python "$TOOLS/epub_to_kokoro.py" "$EPUB" --list
fi

# ---- Phase 1: find unrecognised words ----
if [ ! -f "$WORDS" ] || [ "$REFRESH" -eq 1 ]; then
  python "$TOOLS/find_unknown_words.py" "$EPUB" --out "$WORDS"
  echo
  echo "Wrote $WORDS"
  echo "Next: fill in the 'pronunciation' column (leave blank where a word already sounds right),"
  echo "      optionally spot-check with tools/test_pronunciation.py, then run this command again."
  exit 0
fi

# ---- Phase 2: convert ----
if [ -z "$URL" ]; then
  echo "No Kokoro server URL. Set KOKORO_URL or pass --url https://your-server" >&2
  exit 1
fi

PRON=()
for g in ${GLOSSARIES[@]+"${GLOSSARIES[@]}"}; do PRON+=("$g"); done
PRON+=("$WORDS")

exec python "$TOOLS/epub_to_kokoro.py" "$EPUB" \
  --url "$URL" \
  --pronunciations "${PRON[@]}" \
  --work "$OUT/chapters" \
  --out "$OUT/$SLUG.m4b" \
  ${EXTRA[@]+"${EXTRA[@]}"}
