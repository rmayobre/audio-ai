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
test -f "$TMP/output/smoke/words.csv"
grep -q "Urza" "$TMP/output/smoke/words.csv"

printf 'word,pronunciation\nMishra,Mish-ruh\n' > "$TMP/gloss.csv"
sed -i 's/^Urza,\([0-9]*\),$/Urza,\1,Er-zuh/' "$TMP/output/smoke/words.csv"

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

echo "== a book started before the rename (names.csv) is migrated, not regenerated"
mv "$TMP/output/smoke/words.csv" "$TMP/output/smoke/names.csv"
"$W" "$EPUB" smoke --glossary "$TMP/gloss.csv" -- --tempo 0.9 > "$TMP/migrate.out"
grep -q "Renamed" "$TMP/migrate.out"
test -f "$TMP/output/smoke/words.csv" && ! test -f "$TMP/output/smoke/names.csv"
grep -q "Urza,[0-9]*,Er-zuh" "$TMP/output/smoke/words.csv"

echo "== update_glossary"
python "$TMP/tools/update_glossary.py" "$TMP/output/smoke/words.csv" "$TMP/gloss.csv" > "$TMP/glossary.out"
head -1 "$TMP/glossary.out"
grep -q "Urza,Er-zuh" "$TMP/gloss.csv"

echo "== test_glossary (list, then render)"
python "$TMP/tools/test_glossary.py" "$TMP/gloss.csv" --list > "$TMP/tl.out"
grep -q "Mishra -> Mish-ruh" "$TMP/tl.out"
python "$TMP/tools/test_glossary.py" "$TMP/gloss.csv" --out-dir "$TMP/gtests" >/dev/null
test -s "$TMP/gtests/gloss/gloss_review.flac"
grep -q "00:00  Mishra -> Mish-ruh" "$TMP/gtests/gloss/gloss_review.txt"
grep -q "Mish-ruh" "$TMP/requests.log"

echo "== blank second column = keep Kokoro's pronunciation"
printf 'Blankword,\nBareword\n' >> "$TMP/gloss.csv"
python "$TMP/tools/test_glossary.py" "$TMP/gloss.csv" --out-dir "$TMP/gtests" > "$TMP/tg.out"
grep -q "2 blank entries skipped" "$TMP/tg.out"
python "$TMP/tools/update_glossary.py" "$TMP/output/smoke/words.csv" "$TMP/gloss.csv" >/dev/null
grep -q "^Blankword,$" "$TMP/gloss.csv" || { echo "blank glossary row was lost by update_glossary"; exit 1; }

echo "== play_audio"
CLIP=$(ls "$TMP"/gtests/gloss/clips/*.flac | head -1)
python "$TMP/tools/play_audio.py" --list-players >/dev/null
AUDIO_PLAYER=true python "$TMP/tools/play_audio.py" "$CLIP"
python "$TMP/tools/play_audio.py" "$TMP/missing.flac" 2>/dev/null && { echo "missing file should fail"; exit 1; } || true

echo "== review_pronunciations (r replays, 1 = clip 1 / native, 2 = clip 2 / respelled)"
export AUDIO_PLAYER=true
printf 'r\n1\n2\n' | python "$TMP/tools/review_pronunciations.py" "$TMP/gtests/gloss" >/dev/null
grep -q "^Mishra,$" "$TMP/gloss.csv" || { echo "choosing clip 1 should blank Mishra"; exit 1; }
grep -q "^Urza,Er-zuh$" "$TMP/gloss.csv" || { echo "choosing clip 2 should keep Urza's respelling"; exit 1; }
grep -q "^Blankword,$" "$TMP/gloss.csv" || { echo "review dropped a blank row"; exit 1; }
! grep -q "Mish-ruh" "$TMP/gloss.csv" || { echo "Mishra respelling should be gone"; exit 1; }
G="$TMP/gtests/gloss/clips"
[ -z "$(ls "$G"/*.flac 2>/dev/null)" ] || { echo "reviewed clips were not moved out of clips/"; exit 1; }
[ "$(ls "$G"/reviewed/*.flac | wc -l)" -eq 4 ] || { echo "expected 4 clips in clips/reviewed/"; exit 1; }
printf '' | python "$TMP/tools/review_pronunciations.py" "$TMP/gtests/gloss" > "$TMP/rv0.out"
grep -q "0 to review" "$TMP/rv0.out" || { echo "clips in reviewed/ should be ignored"; exit 1; }
printf 'q\n' | python "$TMP/tools/review_pronunciations.py" "$TMP/gtests/gloss" --redo > "$TMP/rv.out"
grep -q "0 change(s)" "$TMP/rv.out"  # quitting a --redo keeps earlier decisions; nothing changes
echo "== a changed respelling re-renders only its own clip; the as-written clip is reused from reviewed/"
N1=$(wc -l < "$TMP/requests.log")
sed -i 's/^Urza,Er-zuh$/Urza,Er-zah/' "$TMP/gloss.csv"
python "$TMP/tools/test_glossary.py" "$TMP/gloss.csv" --out-dir "$TMP/gtests" > "$TMP/tg2.out"
N2=$(wc -l < "$TMP/requests.log")
[ $((N2 - N1)) -eq 1 ] || { echo "expected exactly 1 new request, got $((N2 - N1))"; exit 1; }
printf '2\n' | python "$TMP/tools/review_pronunciations.py" "$TMP/gtests/gloss" > "$TMP/rv2.out"
grep -q "^Urza,Er-zah$" "$TMP/gloss.csv" || { echo "new respelling choice was not written"; exit 1; }
[ -z "$(ls "$G"/*.flac 2>/dev/null)" ] || { echo "new clip was not moved to reviewed/"; exit 1; }
unset AUDIO_PLAYER

echo "ALL OK"
