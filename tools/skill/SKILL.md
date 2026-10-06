---
name: epub-to-kokoro-audiobook
description: Turn an epub into a chaptered audiobook with Kokoro: find unusual names, research pronunciations using the user's book context, then run the audiobooks repo tools.
---

# Epub to Kokoro audiobook

Builds one chaptered `.m4b` from an epub through a Kokoro-FastAPI server, after fixing how invented names and unusual words are pronounced. It drives the user's `audiobooks` repository (see its `AGENTS.md`).

Repo layout (relative to the repo root):
- `tools/make-audiobook.sh EPUB SLUG [--glossary FILE]... [--list] [--url URL] [-- extra converter args]` is the two-phase wrapper. Phase 1 writes `output/SLUG/names.csv` and stops. Running it again does phase 2 and writes `output/SLUG/SLUG.m4b`.
- `tools/find_unknown_words.py`, `tools/epub_to_kokoro.py`, `tools/test_pronunciation.py`, `tools/update_glossary.py` are the underlying tools.
- `glossaries/<series>.csv` holds shared pronunciations (`word,pronunciation`); `output/SLUG/names.csv` holds one book's (`word,count,pronunciation`).
- `tests/smoke_test.sh` checks the toolchain against a fake server.

## 1. Collect inputs before doing any work

Ask with AskUserQuestion (up to four questions per call; use a second call or plain text for the rest). Do not guess values the user must supply.

**Required**
- Where the repo is (ask once; if it is attached or already in the working directory, use that). If it cannot be found, say so; do not rewrite the scripts from memory.
- Path to the epub, and a short slug for the output folder (for example `brothers-war`).
- Kokoro server URL (never assume `localhost:8880`; the user may have `KOKORO_URL` set, so confirm it).

**Book context (this is what makes the pronunciations good)**
- Title, author, and series or setting (for example a Magic: The Gathering or Warcraft novel).
- Pronunciations the user already knows, and any official audiobook, wiki or glossary they trust.
- Accent preference for names, if it matters.
- Anything to skip or treat specially.
- Whether a series glossary already exists in `glossaries/` to reuse (list the folder and offer the match).

**Settings, offering defaults** (accept "defaults"):
- Voice: default is the server blend `am_onyx(4)+am_adam(1)`; plain `am_onyx` if the server rejects blends.
- Tempo: default `0.90`; `0.88` is noticeably slower. Keep the server speed at 1.0.
- Skip the deep-voice post-processing (`--no-fx`)?

## 2. Check prerequisites

- Python packages from `tools/requirements.txt` (`pip install --break-system-packages -r tools/requirements.txt` if missing) and `ffmpeg`/`ffprobe` on PATH.
- Server reachability: `GET <url>/v1/audio/voices`. The workspace network is often restricted and a home-lab server may be unreachable. If the request is refused or times out, do not retry other routes. Prepare everything up to the final command and give the user the exact command to run where the server is reachable, or use a shell on their computer if one is linked.

## 3. Find the unknown words (phase 1)

```bash
tools/make-audiobook.sh "<epub>" <slug> --glossary glossaries/<series>.csv
```

This writes `output/<slug>/names.csv` and stops. If it already exists, keep it (use `--refresh` only if the user asks, because it overwrites their work). Read the list. Rare but real English words (archaic or technical terms) usually need no change; names, places and invented terms are the focus.

## 4. Fill in pronunciations

Work from the most to the least frequent word.

- Use the user's book context first, then the series glossary (skip words it already covers), then web search for each uncertain name (for example `how to pronounce <name> <series>`), preferring official audiobook narrators, publishers, the author, and trusted wikis. Never invent a pronunciation. If sources disagree or none exist, mark the word uncertain and ask.
- Write a respelling a text-to-speech model reads naturally: lowercase syllables joined by hyphens, with doubled vowels or a familiar word to carry the sound (for example `Er-zuh`, `Toe-kay-zhuh`). Avoid symbols and capitals inside a word. Use `[word](/phonemes/)` markup only if the user asks and the server handles it.
- Leave `pronunciation` blank for words that already sound right. Keep the header `word,count,pronunciation` and the exact casing from the book (replacement is whole-word and case-sensitive). Add multi-word names as their own rows.

Show the user a compact table of word → respelling, with uncertain entries marked and the source for each, and ask them to confirm or correct before synthesis. Save their corrections into `names.csv`.

Optional spot check when the server is reachable:

```bash
python tools/test_pronunciation.py --pronunciations output/<slug>/names.csv --max 10 --fx
```

It writes each word as written and respelled into `pronunciation_tests/`; send the clips to the user and adjust.

## 5. Convert (phase 2)

Preview the sections first and check that the prologue, chapters and epilogue are present and the front and back matter is skipped:

```bash
tools/make-audiobook.sh "<epub>" <slug> --list
```

Then run the same wrapper command again (with `--url` or `KOKORO_URL`, the glossary, and any `-- --tempo X --voice Y` settings):

```bash
tools/make-audiobook.sh "<epub>" <slug> --glossary glossaries/<series>.csv --url <url> -- --tempo 0.9
```

- It is long-running (large books take many minutes to hours). Run it in the background or with a long timeout and check progress. It prints timestamped, flushed progress (per chunk, per chapter, with an ETA) and also writes `output/<slug>/chapters/convert.log` (override with `-- --log FILE`); `tail -f` that file.
- It is resumable: finished chapters are skipped and in-progress chunks reused, so rerun the same command after an interruption.
- New pronunciations only affect chapters generated afterwards. To redo a chapter, delete its `output/<slug>/chapters/chapter_XX.flac` and rerun.
- If the server rejects the voice, rerun with `-- --voice am_onyx`. If synthesis keeps failing, report the server's error instead of looping.

## 6. Finish

- Send the finished `.m4b` and the final `names.csv` with SendUserFile. If the file is too large to send, say where it is.
- Offer to save the new pronunciations for the next book in the series: `python tools/update_glossary.py output/<slug>/names.csv glossaries/<series>.csv`.
- Summarize in two or three lines: sections read, pronunciations applied, and any words left uncertain.
- End with a "Sources:" list of the pages used to confirm pronunciations, as markdown links.

## Principles

- Ask for context and server details up front; do not run the pipeline on assumptions.
- Never fabricate a pronunciation. Say "uncertain" and let the user decide.
- Do not commit or share the user's server URL or the epub itself beyond this task.
