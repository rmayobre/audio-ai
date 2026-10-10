# Audio AI

Turn an epub into a single, chaptered `.m4b` audiobook using your own [Kokoro-FastAPI](https://github.com/remsky/Kokoro-FastAPI)
server, with a deep narrator voice and the names in the book pronounced correctly.

Most text-to-speech stumbles on invented names (Urza, Tocasia, Kroog). This toolkit finds the words a dictionary
doesn't know, lets you give each one a respelling, and applies those fixes before anything is sent to the server.
Pronunciations are saved per book and per series, so the work carries over to the next book in the same universe.

- Reads the prologue, chapters, interludes and epilogue in order; skips copyright pages, contents, acknowledgments, etc.
- Deep voice from a blend of Kokoro voices plus ffmpeg post-processing (lower pitch, slower pace, bass boost).
- Combines everything into one `.m4b` with chapter markers, ready for any audiobook player.
- Resumable: stop at any point and rerun the same command to carry on.

> Agent and contributor notes live in [AGENTS.md](AGENTS.md).

## How it works

```
book.epub
   │  find_unknown_words.py      words not in an English dictionary  ──►  words.csv
   │                                                                         │ you fill in respellings
   ▼                                                                         ▼
epub_to_kokoro.py  ◄───────────────────────────  glossaries/<series>.csv + words.csv
   │  split into chapters → apply respellings → Kokoro server → ffmpeg deep-voice → chapter_XX.flac
   ▼
output/<slug>/<slug>.m4b   (one file, chapter markers)
```

## Requirements

- Python 3
- `ffmpeg` and `ffprobe` on your `PATH`
- A running Kokoro-FastAPI server you can reach over HTTP(S)

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r tools/requirements.txt
```

Tell the tools where your server is once, instead of passing `--url` every time:

```bash
echo 'export KOKORO_URL=https://your-kokoro-server' >> ~/.bashrc    # or ~/.zshrc
source ~/.bashrc
```

## Making an audiobook

The wrapper `tools/make-audiobook.sh` works in two steps. Run the same command twice.

```bash
cp "/path/to/Some Book.epub" books/

# Step 1: find unusual words and write output/some-book/words.csv, then stop
tools/make-audiobook.sh "books/Some Book.epub" some-book --glossary glossaries/some-series.csv

# Fill in the pronunciation column for any word that sounds wrong (leave the rest blank).
# Then listen to a few before committing to the full run:
python tools/test_pronunciation.py --pronunciations output/some-book/words.csv --max 10 --fx

# Step 2: convert (run the exact same command again)
tools/make-audiobook.sh "books/Some Book.epub" some-book --glossary glossaries/some-series.csv
```

The result is `output/some-book/some-book.m4b`. `--glossary` is optional and can be repeated; the book's own
`words.csv` is applied last and wins on conflicts.

Other things you can do with the wrapper:

```bash
tools/make-audiobook.sh "books/Some Book.epub" some-book --list               # preview which sections would be read
tools/make-audiobook.sh "books/Some Book.epub" some-book -- --tempo 0.88      # extra flags go to the converter after --
tools/make-audiobook.sh "books/Some Book.epub" some-book --refresh            # regenerate words.csv (overwrites it!)
```

### Fixing pronunciations

Open `output/<slug>/words.csv`:

```csv
word,count,pronunciation
Urza,412,Er-zuh
Tocasia,96,
```

Write the pronunciation as a respelling a text-to-speech model will read naturally: lowercase syllables joined by
hyphens, with doubled vowels or a familiar word to carry the sound. Leave it blank where the word already sounds
right, since blank rows are ignored.

- A blank pronunciation (`Urza,` or just `Urza`) means leave Kokoro's own pronunciation alone; the word is not respelled.
- Matching is whole-word and case-sensitive, and longer entries win, so `Urza Planeswalker` beats `Urza`.
- A pronunciation file can be `.csv`, `.json`, `.py` (a `PRONUNCIATIONS = {...}` dict) or `.txt` (`word = pronunciation`).
- When you finish a book, save its pronunciations for the next one in the series:

  ```bash
  python tools/update_glossary.py output/some-book/words.csv glossaries/some-series.csv
  ```

New pronunciations only affect chapters generated afterwards. To redo a chapter, delete its
`output/<slug>/chapters/chapter_XX.flac` and rerun.

### Maintaining one glossary for a series

Books in the same universe share names, so keep **one main glossary per series** in `glossaries/` and feed each new
book into it. New respellings are easiest to trust if they go into a small per-book *staging* glossary first, get
reviewed by ear, and only then are merged into the main one. This is the workflow used for Magic: The Gathering
(`magic-the-gathering.csv`, with staging glossaries such as `magic-the-gathering-bloodlines.csv`):

```bash
# 1. First book of the series: build the main glossary from its filled-in words.csv, then check it by ear
python tools/update_glossary.py output/brothers-war/words.csv glossaries/magic-the-gathering.csv
python tools/test_glossary.py magic-the-gathering
python tools/review_pronunciations.py magic-the-gathering     # 1 / 2 / r; a pick of clip 1 leaves the row blank

# 2. Next book: find its words. Words the main glossary already covers can stay blank in words.csv;
#    fill in only the new names. Then save those as a staging glossary.
tools/make-audiobook.sh "books/Bloodlines.epub" bloodlines --glossary glossaries/magic-the-gathering.csv
python tools/update_glossary.py output/bloodlines/words.csv glossaries/magic-the-gathering-bloodlines.csv

# 3. Review the staging glossary by ear (it is updated as you choose)
python tools/test_glossary.py magic-the-gathering-bloodlines
python tools/review_pronunciations.py magic-the-gathering-bloodlines

# 4. Convert with both glossaries: main first, then the staging one
tools/make-audiobook.sh "books/Bloodlines.epub" bloodlines \
  --glossary glossaries/magic-the-gathering.csv \
  --glossary glossaries/magic-the-gathering-bloodlines.csv

# 5. Happy with it? Preview, then merge the staging glossary into the main one
python tools/update_glossary.py glossaries/magic-the-gathering-bloodlines.csv glossaries/magic-the-gathering.csv --dry-run
python tools/update_glossary.py glossaries/magic-the-gathering-bloodlines.csv glossaries/magic-the-gathering.csv
```

Repeat steps 2 to 5 for each further book. Because every staging glossary only holds words the main one lacks,
merging several of them rarely clashes.

**Which file wins** (the order matters):

| Situation | Rule |
|---|---|
| Converting with several `--glossary` files | Later files override earlier ones, and the book's own `words.csv` is applied last of all. Put the main glossary first and the staging one after it. |
| A blank pronunciation in a later file | Never cancels an earlier respelling. Blank means "nothing to apply", so the earlier file's entry still applies. To drop a respelling, blank or delete it in the file that contains it. |
| `update_glossary.py SOURCE GLOSSARY` | The first file is the one being merged in and the second is the one written. Words missing from GLOSSARY are added. If both have the word with different pronunciations, GLOSSARY keeps its own and the clash is printed as a `conflict`. `--overwrite` makes SOURCE win instead. |
| Merging several sources one after another | Without `--overwrite`, whichever is merged first wins a clash, so run each with `--dry-run` and read the conflicts. To make one source win, merge it last with `--overwrite`. |
| A blank row already in GLOSSARY | Counts as an existing decision ("keep Kokoro's pronunciation") and is kept, even against a filled-in source entry, unless `--overwrite`. |

**Known limitation:** `update_glossary.py` copies only filled-in entries from the source. If you reviewed a staging
glossary and chose Kokoro's own pronunciation for a word (a blank row), that choice is not copied across. To record
it in the main glossary, add the row by hand (`Karn,`), otherwise a later book that respells the word will fill it.

### Voice profiles

A voice profile is a small JSON file in `voices/` holding a voice and its settings. Choose one per book:

```bash
python tools/voice_profiles.py list                                              # what is available
tools/make-audiobook.sh "books/Some Book.epub" some-book --profile deep-narrator
python tools/voice_profiles.py new gravel --from deep-narrator --voice am_michael --pitch 0.9
```

Profiles also work with `test_pronunciation.py` and `test_glossary.py` (`--profile NAME`). Settings are chosen in this
order: a command-line flag, then the profile, then the built-in default. Shipped profiles: `deep-narrator` (the
default sound) and `plain-onyx` (no post-processing). See `voices/README.md` for the file format. The settings used
for a book are saved in `output/<slug>/chapters/voice_settings.json`, and the converter warns if a rerun uses different
ones, since finished chapters keep the old voice.

### Voice and pace

Defaults: voice blend `am_onyx(4)+am_adam(1)`, pitch `0.94`, tempo `0.90`, bass `4` dB. Pass overrides to the converter after `--` (they beat the profile):

| Flag | Meaning |
|---|---|
| `--tempo 0.88` | Final speaking speed. Lower is slower; 0.88 to 0.92 is a good range. |
| `--pitch 0.92` | Pitch shift. Lower is deeper; go in small steps. |
| `--voice am_onyx` | Voice or blend. Use a plain voice if your server rejects blend syntax. |
| `--bass 4` | Low-shelf bass boost in dB. |
| `--no-fx` | Skip the ffmpeg deep-voice processing. |
| `--speed 1.0` | Server-side speed. Leave it near 1.0 and use `--tempo` to slow things down. |
| `--log FILE` | Where to write the progress log. Default: `output/<slug>/chapters/convert.log` (one per book, appended on reruns). |

### Which sections are read

`epub_to_kokoro.py` reads the book's reading order and keeps sections that start with Prologue, Prelude, Chapter,
Epilogue, Interlude, Introduction, Foreword, Preface, Afterword, Part or Book, plus any long section. It skips contents,
copyright, dedication, acknowledgments, about the author, notes and similar. Part and Book title pages are very short,
so they become short clips. Adjust `INCLUDE_RE`, `SKIP_RE` and `MIN_CHARS_OTHER` at the top of the script to change
this, and use `--list` to preview.

**Chapter titles.** Normally a section is titled from its own heading ("Part One: The Golden Boy"). Some epubs show
the chapter title as an image, so the text has no heading; then the title comes from the epub's table of contents, else
from the image's alt text when it is a number ("Chapter 7"), else it continues the numbering. These titles are also
spoken at the start of the section.

**Stray text.** Watermarks such as `OceanofPDF.com` are removed from every section before it is read, and are ignored by
`find_unknown_words.py`. To strip another site's tag, add it to `STRAY_RE` at the top of `epub_to_kokoro.py`.

## Tools

Every script supports `--help`. All flags are listed here.

### `tools/make-audiobook.sh EPUB SLUG [options] [-- converter flags]`

Two-step wrapper: finds words on the first run, converts on the second.

| Flag | Meaning |
|---|---|
| `--glossary FILE` | Shared pronunciations applied first. Repeatable; later files override earlier ones and the book's `words.csv` always wins (see "Maintaining one glossary for a series"). |
| `--url URL` | Kokoro server URL. Default: `$KOKORO_URL`. |
| `--list` | Only preview which sections would be read. |
| `--refresh` | Regenerate `words.csv` even if it exists (overwrites it!). |
| `--profile NAME` | Voice profile from `voices/`. |
| `--list-profiles` | Show the available voice profiles and exit. |
| `-- ...` | Everything after `--` goes to `epub_to_kokoro.py`. |

### `tools/find_unknown_words.py EPUB`

Lists words that are not in an English dictionary (mostly names and places). The result, `words.csv`, holds every unrecognised word (names, invented terms, dialect and the odd fragment), not only names. Books started before the rename have `names.csv`; `make-audiobook.sh` renames it to `words.csv` automatically.

| Flag | Meaning |
|---|---|
| `--out [FILE]` | Save the full list. Format follows the extension: `.csv`, `.json`, `.py`, `.txt`. With no file name, writes `<epub name>_unknown_words.txt`. |
| `--min-count N` | Ignore words seen fewer than N times (default 2). |
| `--top N` | How many words to print (default 80). |
| `--known FILE` | Text file of extra words to treat as known, one per line. |

### `tools/epub_to_kokoro.py EPUB`

Converts an epub to a chaptered `.m4b`. Resumable.

| Flag | Meaning |
|---|---|
| `--url URL` | Kokoro server URL. Default: `$KOKORO_URL`, else `http://localhost:8880`. |
| `--profile NAME` | Voice profile from `voices/` (or a path to a profile `.json`). Flags below override it. |
| `--voice VOICE` | Voice or blend (default `am_onyx(4)+am_adam(1)`). |
| `--speed X` | Server-side speed (default 1.0; keep near 1.0). |
| `--pitch X` | Pitch shift (default 0.94). |
| `--tempo X` | Final speaking speed (default 0.90). |
| `--bass DB` | Low-shelf bass boost in dB (default 4). |
| `--no-fx` | Skip the deep-voice ffmpeg processing. |
| `--pronunciations FILE...` | One or more `.csv`, `.json`, `.py` or `.txt` files. Later files win. |
| `--no-roman-numerals` | Do not spell out Roman numerals. By default II-XX after a name become "the Second", "the Third", ... (`Terenas Menethil II`), and after Part/Book/Chapter/Act/etc. become numbers (`Part II` -> "Part two"). Glossary entries are applied first, so a row like `Menethil II,Menethil the Second` always wins. A lone `I`, `V` or `X` is never changed. |
| `--out FILE` | Output file, `.m4b` or `.mp3`/`.m4a`. Default: `<epub name>.m4b`. |
| `--work DIR` | Folder for chapter files. Default: `<epub name>_chapters`. |
| `--log FILE` | Progress log to append to. Default: `<work>/convert.log`. |
| `--list` | Only list the sections that would be read. |

### `tools/test_pronunciation.py [WORD ...]`

Saves each word as written and respelled so you can compare. With no words, tests the filled-in entries of the
pronunciation files.

| Flag | Meaning |
|---|---|
| `--pronunciations FILE...` | Files to read respellings from. |
| `--url URL` | Kokoro server URL. Default: `$KOKORO_URL`. |
| `--voice VOICE` | Voice or blend (same default as the converter). |
| `--speed X` | Server-side speed (default 1.0). |
| `--fx` | Apply the deep-voice processing so the test matches the real run. |
| `--pitch X`, `--tempo X` | Used with `--fx` (same defaults as the converter). |
| `--sentence TEXT` | Custom test sentence; `{word}` is replaced (default: "The name {word} echoed through the hall."). |
| `--max N` | Limit when testing a whole file (default 20). |
| `--out-dir DIR` | Where the test clips go (default `output/pronunciation_tests`, git-ignored). |

### `tools/test_glossary.py [GLOSSARY ...]`

Renders every entry of the glossaries (default: all of `glossaries/*.csv`) as written and respelled, and joins the
clips into one review file per glossary with a timestamped index, so you can listen straight through and note the
respellings that sound wrong. Clips are reused on reruns; a changed respelling gets a new clip.

| Flag | Meaning |
|---|---|
| `GLOSSARY` | A glossary path or bare name such as `warcraft`. Default: every `glossaries/*.csv`. |
| `--words WORD...` | Only test these words. |
| `--max N`, `--start N` | Test N entries, skipping the first `--start`. |
| `--respelled-only` | Skip the as-written clip. |
| `--list` | Show what would be tested; no server needed. |
| `--url`, `--voice`, `--speed`, `--pitch`, `--tempo`, `--sentence` | Same as `test_pronunciation.py`. |
| `--no-fx` | Skip the deep-voice processing (it is on by default so clips match a real run). |
| `--out-dir DIR` | Default `output/pronunciation_tests` (git-ignored); output is `<dir>/<glossary>/<glossary>_review.flac` and `.txt`. |

### `tools/review_pronunciations.py [TEST_DIR ...]`

Plays the clips made by `test_glossary.py` two at a time (clip 1 is Kokoro's own pronunciation, clip 2 is the
respelling) and asks which sounds best. When every word is decided, the glossary is updated: the respelling is kept
if you pick clip 2, and the second column is left **blank** if you pick clip 1. Choices are saved after every word, so
you can quit and resume. Once a word is decided, its two clips move into `clips/reviewed/`; clips in a folder
called `reviewed` are ignored on later runs, so a rerun only plays what is left (`test_glossary.py` also reuses them
instead of re-rendering).

| Prompt | Meaning |
|---|---|
| `1` / `2` | Clip 1 / clip 2 sounds best. |
| `r` | Hear both clips again. |
| `q` | Save progress and quit (the glossary is only written once all words are decided, or with `--apply`). |

| Flag | Meaning |
|---|---|
| `TEST_DIR` | A folder in `output/pronunciation_tests/` or a glossary name. Default: all of them. |
| `--shuffle` | Randomise which clip plays first (a blind test). `--shuffle-words` randomises the word order. |
| `--show-respelling` | Print the respelling next to each word. |
| `--redo` | Ask again about words already decided, including their clips in `reviewed/`. |
| `--apply` | Write the decisions made so far without asking more. |
| `--dry-run` | Show the glossary changes without writing anything: no glossary edit, no saved choices, no clips moved. |

A book's own `output/<slug>/words.csv` is applied after the glossary and still wins, so edit it too if a book already
carries an old respelling.

### `tools/play_audio.py FILE`

Plays an audio file on Linux, macOS or Windows with whatever is installed (ffplay, mpv, VLC, afplay, pw-play, paplay,
sox, aplay, Windows SoundPlayer), converting to wav with ffmpeg when a player needs it. Verified on Linux only.

| Flag | Meaning |
|---|---|
| `--start TIME` | Start offset such as `90`, `12:05` or `1:30:00` (ffplay, mpv, VLC). |
| `--list-players` | Show the players found on this machine. |
| `AUDIO_PLAYER` (env) | Force a player command, for example `AUDIO_PLAYER="mpv --no-video"`. |

### `tools/voice_profiles.py {list,show,new}`

Manages `voices/*.json`: `list` shows every profile, `show NAME` prints one, and `new NAME` creates one
(`--from PROFILE`, `--description`, `--voice`, `--speed`, `--pitch`, `--tempo`, `--bass-db`, `--fx on|off`,
`--force` to overwrite).

### `tools/update_glossary.py SOURCE GLOSSARY`

Merges a book's pronunciations, or a staging glossary, into a shared series glossary. Only filled-in entries are copied. Existing entries in the target win unless `--overwrite`, and every clash is printed. Blank rows already in the target are kept (they mean Kokoro's own pronunciation was chosen). See "Maintaining one glossary for a series" for the full ordering rules.

| Flag | Meaning |
|---|---|
| `--dry-run` | Print the changes without writing. |
| `--overwrite` | Let the book's entries replace existing glossary entries that differ. |

## Project layout

```
tools/            the scripts above, requirements.txt, and a copy of the Claude skill (skill/SKILL.md)
glossaries/       shared pronunciations per series (tracked in git)
books/            your epubs (git-ignored)
output/<slug>/    words.csv (tracked), chapters/ and the finished .m4b (git-ignored)
tests/            smoke test and a fake Kokoro server
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `No Kokoro server URL` | Set `KOKORO_URL` or pass `--url`. |
| Server rejects the voice | Use `--voice am_onyx` (plain voice instead of a blend). |
| A word is still said wrong | Respell it in `words.csv`, check it with `test_pronunciation.py`, delete the affected chapter's `.flac`, rerun. |
| Pace is too fast | Lower `--tempo` (for example 0.88). Keep the server `--speed` at 1.0. |
| Speech sounds slurred or robotic | Avoid heavy server-side slowing or unusual voice blends; get depth from `--pitch` and the bass boost instead. |
| Chapter missing or wrong order | Run with `--list` and adjust the section patterns at the top of `epub_to_kokoro.py`. |
| Interrupted run | Rerun the same command; finished chapters and chunks are reused. |

## Tests

```bash
tests/smoke_test.sh        # runs everything against a fake server; should end with ALL OK
```

## Using it with Claude

`tools/skill/SKILL.md` is a Claude skill that runs this whole workflow for you: it asks about the book and your
server, finds the unusual words, researches pronunciations using what you tell it about the book, checks them with
you, then runs the conversion. Save it in Claude from that file.

## Notes

Books are copyrighted: keep your epubs and the generated audio for personal use and out of version control (the
included `.gitignore` already excludes them).
