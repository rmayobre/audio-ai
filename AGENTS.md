# AGENTS.md

Guidance for AI coding agents (and humans) working in this repository.

## What this repo does

Turns epubs into single, chaptered `.m4b` audiobooks using a self-hosted
[Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI) server, with a deep voice and corrected
pronunciations for invented names. Pipeline per book:

1. `find_unknown_words.py` lists words that are not in an English dictionary (mostly names and places).
2. A human or agent fills in a respelling for each word that is read wrongly.
3. `epub_to_kokoro.py` sends each prologue/chapter/interlude/epilogue to Kokoro, post-processes the audio with
   ffmpeg (lower pitch, slower tempo, bass boost), and combines everything into one `.m4b` with chapter markers.

## Layout

```
tools/
  epub_to_kokoro.py        main converter (resumable)
  find_unknown_words.py    unrecognised-word finder, exports .csv/.json/.py/.txt
  test_pronunciation.py    renders a word as written vs. respelled so it can be heard
  test_glossary.py         renders every glossary entry into one reviewable audio file with an index
  review_pronunciations.py plays test clips two at a time and writes the chosen result back to the glossary
  play_audio.py            cross-platform audio player (ffplay, mpv, VLC, afplay, pw-play, ...)
  voice_profiles.py        voice profile loader/CLI (voices/*.json); shared by the converter and test scripts
  update_glossary.py       merges a book's pronunciations into a shared series glossary
  make-audiobook.sh        two-phase wrapper tying the above together
  requirements.txt         Python dependencies (ffmpeg/ffprobe come from the OS)
  skill/SKILL.md           copy of the Claude skill that drives this workflow
voices/                    voice profiles, one JSON per voice (tracked); chosen with --profile NAME
glossaries/                shared pronunciations per series (tracked), e.g. magic-the-gathering.csv
books/                     source epubs (git-ignored; copyrighted)
output/<slug>/             per book: words.csv (TRACKED), chapters/ and <slug>.m4b (git-ignored)
tests/                     smoke_test.sh + fake_kokoro_server.py (no real TTS or network needed)
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r tools/requirements.txt      # also needs ffmpeg and ffprobe on PATH
export KOKORO_URL=https://your-kokoro-server
```

## Everyday commands

```bash
# Phase 1: write output/<slug>/words.csv (stops so pronunciations can be filled in)
tools/make-audiobook.sh "books/Some Book.epub" some-book --glossary glossaries/<series>.csv
# Phase 2 (same command again): convert to output/<slug>/<slug>.m4b
tools/make-audiobook.sh "books/Some Book.epub" some-book --glossary glossaries/<series>.csv
# Preview which sections will be read
tools/make-audiobook.sh "books/Some Book.epub" some-book --list
# Hear respellings before a full run
python tools/test_pronunciation.py --pronunciations output/some-book/words.csv --max 10 --fx
# Save a finished book's pronunciations for the next book in the series
python tools/update_glossary.py output/some-book/words.csv glossaries/<series>.csv
```

Extra flags for the converter go after `--`, for example `-- --tempo 0.88 --voice am_onyx`.

## Verify changes

Run `tests/smoke_test.sh` after editing anything under `tools/`. It builds a tiny epub (with an apostrophe in its
title on purpose), runs both wrapper phases against a fake Kokoro server, and checks: names found, respellings (from
both a glossary and the book file) reach the server, three chapters and chapter markers in the `.m4b`, a rerun makes
no new server calls, and the glossary update works. It must print `ALL OK`. Do not test against the real server
unless the user asks, because full runs take a long time.

## Behaviours to preserve

- **Resumable:** finished `chapter_XX.flac` files are skipped, and existing chunk files are reused. Changing a
  pronunciation does not alter finished chapters; delete the chapter's `.flac` to redo it.
- **Paths:** book titles contain spaces and apostrophes ("The Brothers' War"). Use `concat_line()` for ffmpeg
  concat lists, sanitised work-folder names, and quote every shell variable.
- **Pronunciation files:** `.csv` (`word,count,pronunciation` or `word,pronunciation`), `.json`, `.py` (parsed with
  `ast.literal_eval`, never executed), or `.txt` (`word = pronunciation`). Blank pronunciations are ignored (blank = keep Kokoro's own
  pronunciation; glossaries keep blank rows to record that a word was reviewed). Several
  files can be given; later ones win. Replacement is whole-word, case-sensitive, longest match first.
- **Speed vs. tempo:** keep the server `--speed` at 1.0 and use `--tempo` (ffmpeg) to slow delivery. Heavy server-side
  slowing and exaggerated voicepacks caused mispronunciations earlier.
- **Voice settings** come from a flag, else the `--profile` JSON in `voices/`, else the built-in defaults in
  `voice_profiles.py`. The settings used are recorded in `<work>/voice_settings.json` and a rerun with different ones warns.
- **Voice blend syntax** (`am_onyx(4)+am_adam(1)`) is a Kokoro-FastAPI feature. If the server rejects it, fall back
  to a plain voice such as `am_onyx`.
- CSV files are written with `\n` line endings so diffs and `sed` behave.

## Rules for agents

- Never invent a pronunciation. Use what the user says about the book, official audiobook or author guidance, and
  trusted wikis; mark anything uncertain and ask. Leave `pronunciation` blank for words that already sound right.
- Ask for the Kokoro URL and any book context instead of assuming. Do not hardcode a server URL in committed files;
  it comes from `KOKORO_URL` or `--url`.
- Do not commit epubs or generated audio (`.gitignore` covers them). Do commit `output/<slug>/words.csv` and
  glossaries; that is the reusable work.
- Prefer small, additive changes to `tools/`; keep the scripts dependency-light (see `requirements.txt`) and make
  new options discoverable via `--help` and the module docstring.
- The workspace an agent runs in may not be able to reach the user's Kokoro server. If it cannot, prepare everything
  up to the final command and give the user the exact command to run, rather than retrying other routes.

## Skill

`tools/skill/SKILL.md` mirrors the Claude skill `epub-to-kokoro-audiobook`. If workflow steps or flags change,
update that file too; the user re-saves it in Claude from the new text.
