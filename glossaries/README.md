# Glossaries

One CSV per series or universe, shared by every book in it. Format:

```csv
word,pronunciation
Urza,Er-zuh
```

- Use the word exactly as it is written in the books (matching is whole-word and case-sensitive).
- Pass a glossary with `tools/make-audiobook.sh ... --glossary glossaries/<series>.csv`. A book's own
  `output/<slug>/words.csv` is applied after it and wins on conflicts.
- See "Maintaining one glossary for a series" in the top-level README for the staging-then-merge workflow and which file wins.
- Grow a glossary from a finished book with
  `python tools/update_glossary.py output/<slug>/words.csv glossaries/<series>.csv`
  (existing entries are kept unless you add `--overwrite`).
