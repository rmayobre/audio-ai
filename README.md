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
   │  find_unknown_words.py      words not in an English dictionary  ──►  names.csv
   │                                                                         │ you fill in respellings
   ▼                                                                         ▼
epub_to_kokoro.py  ◄───────────────────────────  glossaries/<series>.csv + names.csv
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

# Step 1: find unusual words and write output/some-book/names.csv, then stop
tools/make-audiobook.sh "books/Some Book.epub" some-book --glossary glossaries/some-series.csv

# Fill in the pronunciation column for any word that sounds wrong (leave the rest blank).
# Then listen to a few before committing to the full run:
python tools/test_pronunciation.py --pronunciations output/some-book/names.csv --max 10 --fx

# Step 2: convert (run the exact same command again)
tools/make-audiobook.sh "books/Some Book.epub" some-book --glossary glossaries/some-series.csv
```

The result is `output/some-book/some-book.m4b`. `--glossary` is optional and can be repeated; the book's own
`names.csv` is applied last and wins on conflicts.

Other things you can do with the wrapper:

```bash
tools/make-audiobook.sh "books/Some Book.epub" some-book --list               # preview which sections would be read
tools/make-audiobook.sh "books/Some Book.epub" some-book -- --tempo 0.88      # extra flags go to the converter after --
tools/make-audiobook.sh "books/Some Book.epub" some-book --refresh            # regenerate names.csv (overwrites it!)
```

### Fixing pronunciations

Open `output/<slug>/names.csv`:

```csv
word,count,pronunciation
Urza,412,Er-zuh
Tocasia,96,
```

Write the pronunciation as a respelling a text-to-speech model will read naturally: lowercase syllables joined by
hyphens, with doubled vowels or a familiar word to carry the sound. Leave it blank where the word already sounds
right, since blank rows are ignored.

- Matching is whole-word and case-sensitive, and longer entries win, so `Urza Planeswalker` beats `Urza`.
- A pronunciation file can be `.csv`, `.json`, `.py` (a `PRONUNCIATIONS = {...}` dict) or `.txt` (`word = pronunciation`).
- When you finish a book, save its pronunciations for the next one in the series:

  ```bash
  python tools/update_glossary.py output/some-book/names.csv glossaries/some-series.csv
  ```

New pronunciations only affect chapters generated afterwards. To redo a chapter, delete its
`output/<slug>/chapters/chapter_XX.flac` and rerun.

### Voice and pace

Defaults: voice blend `am_onyx(4)+am_adam(1)`, pitch `0.94`, tempo `0.95`. Pass overrides to the converter after `--`:

| Flag | Meaning |
|---|---|
| `--tempo 0.88` | Final speaking speed. Lower is slower; 0.88 to 0.92 is a good range. |
| `--pitch 0.92` | Pitch shift. Lower is deeper; go in small steps. |
| `--voice am_onyx` | Voice or blend. Use a plain voice if your server rejects blend syntax. |
| `--no-fx` | Skip the ffmpeg deep-voice processing. |
| `--speed 1.0` | Server-side speed. Leave it near 1.0 and use `--tempo` to slow things down. |

### Which sections are read

`epub_to_kokoro.py` reads the book's reading order and keeps sections that start with Prologue, Prelude, Chapter,
Epilogue, Interlude, Introduction, Foreword, Preface, Afterword or Part, plus any long section. It skips contents,
copyright, dedication, acknowledgments, about the author, notes and similar. Part title pages are very short, so they
become one-second clips. Adjust `INCLUDE_RE`, `SKIP_RE` and `MIN_CHARS_OTHER` at the top of the script to change this,
and use `--list` to preview.

## Tools

| Script | What it does |
|---|---|
| `tools/make-audiobook.sh` | Two-step wrapper: find words, then convert. |
| `tools/find_unknown_words.py` | Lists words not in an English dictionary. `--out names.csv` (also `.json`, `.py`, `.txt`), `--min-count`, `--top`, `--known FILE`. |
| `tools/epub_to_kokoro.py` | Epub to chaptered `.m4b`. `--pronunciations FILE...`, `--url`, `--voice`, `--tempo`, `--pitch`, `--out`, `--work`, `--list`. |
| `tools/test_pronunciation.py` | Saves each word as written and respelled so you can compare. |
| `tools/update_glossary.py` | Merges a book's pronunciations into a series glossary. `--dry-run`, `--overwrite`. |

Every script supports `--help`.

## Project layout

```
tools/            the scripts above, requirements.txt, and a copy of the Claude skill (skill/SKILL.md)
glossaries/       shared pronunciations per series (tracked in git)
books/            your epubs (git-ignored)
output/<slug>/    names.csv (tracked), chapters/ and the finished .m4b (git-ignored)
tests/            smoke test and a fake Kokoro server
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `No Kokoro server URL` | Set `KOKORO_URL` or pass `--url`. |
| Server rejects the voice | Use `--voice am_onyx` (plain voice instead of a blend). |
| A word is still said wrong | Respell it in `names.csv`, check it with `test_pronunciation.py`, delete the affected chapter's `.flac`, rerun. |
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
