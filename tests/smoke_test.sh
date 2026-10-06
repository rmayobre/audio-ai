#!/usr/bin/env bash
# End-to-end check of the whole toolchain against a fake Kokoro server (no real TTS, no network).
# Builds a tiny epub whose title has an apostrophe, runs both wrapper phases, and verifies that
# pronunciations were applied, chapters were produced, and the .m4b has chapter markers.
#
# usage: tests/smoke_test.sh          (needs: python deps from tools/requirements.txt, ffmpeg, ffprobe)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/.venv/bin/activate" ] && source "$ROOT/.venv/bin/activate"
TMP="$(mktemp -d)"; PORT=18999
trap 'kill $SERVER_PID 2>/dev/null || true; rm -rf "$TMP"' EXIT

python - "$TMP" <<'EOF'
import sys
from ebooklib import epub
b = epub.EpubBook(); b.set_identifier("smoke"); b.set_title("Smoke"); b.set_language("en")
chapters = []
for i, body in enumerate([
    "<h1>Prologue</h1><p>Urza waited. Tocasia nodded, and the night was quiet.</p>",
    "<h1>Chapter 1</h1><p>Urza's brother Mishra arrived. " + "They spoke at length. " * 40 + "</p>",
    "<h1>Epilogue</h1><p>Mishra remembered everything.</p>"], 1):
    c = epub.EpubHtml(title=f"c{i}", file_name=f"c{i}.xhtml", lang="en"); c.content = body
    b.add_item(c); chapters.append(c)
b.spine = chapters; b.add_item(epub.EpubNcx()); b.add_item(epub.EpubNav())
epub.write_epub(f"{sys.argv[1]}/The Brothers' War - Smoke (2000).epub", b)
EOF
EPUB="$TMP/The Brothers' War - Smoke (2000).epub"

python "$ROOT/tests/fake_kokoro_server.py" $PORT "$TMP/requests.log" & SERVER_PID=$!
sleep 1
export KOKORO_URL="http://127.0.0.1:$PORT"
cd "$TMP"; mkdir -p tools output; cp -r "$ROOT/tools/." tools/   # run against a scratch copy of the repo layout
W="$TMP/tools/make-audiobook.sh"

echo "== phase 1: find unknown words"
"$W" "$EPUB" smoke --glossary "$TMP/gloss.csv" 2>&1 | tail -3 || true
test -f "$TMP/output/smoke/names.csv"
grep -q "Urza" "$TMP/output/smoke/names.csv"

printf 'word,pronunciation\nMishra,Mish-ruh\n' > "$TMP/gloss.csv"
sed -i 's/^Urza,\([0-9]*\),$/Urza,\1,Er-zuh/' "$TMP/output/smoke/names.csv"

echo "== phase 2: convert"
"$W" "$EPUB" smoke --glossary "$TMP/gloss.csv" -- --tempo 0.9

M4B="$TMP/output/smoke/smoke.m4b"
test -s "$M4B"
CH=$(ffprobe -v error -show_chapters -of csv=p=0 "$M4B" | wc -l)
[ "$CH" -eq 3 ] || { echo "expected 3 chapters, got $CH"; exit 1; }
grep -q "Er-zuh" "$TMP/requests.log" || { echo "Urza respelling was not sent to the server"; exit 1; }
grep -q "Mish-ruh" "$TMP/requests.log" || { echo "glossary respelling was not sent to the server"; exit 1; }
grep -q "Urza" "$TMP/requests.log" && { echo "unreplaced name reached the server"; exit 1; }

echo "== resume: second run must not call the server again"
N1=$(wc -l < "$TMP/requests.log")
"$W" "$EPUB" smoke --glossary "$TMP/gloss.csv" -- --tempo 0.9 >/dev/null
N2=$(wc -l < "$TMP/requests.log")
[ "$N1" -eq "$N2" ] || { echo "resume re-synthesized chapters"; exit 1; }

echo "== update_glossary"
python "$TMP/tools/update_glossary.py" "$TMP/output/smoke/names.csv" "$TMP/gloss.csv" > "$TMP/glossary.out"
head -1 "$TMP/glossary.out"
grep -q "Urza,Er-zuh" "$TMP/gloss.csv"

echo "ALL OK"
