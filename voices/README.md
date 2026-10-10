# Voice profiles

One JSON file per voice. Pick one when making a book:

```bash
tools/make-audiobook.sh "books/Some Book.epub" some-book --profile deep-narrator
python tools/test_glossary.py warcraft --profile plain-onyx
python tools/voice_profiles.py list          # see what is available
```

Create your own by copying a file here, or with the helper:

```bash
python tools/voice_profiles.py new gravel --from deep-narrator --voice am_michael --pitch 0.9 --description "Rougher"
```

Every key is optional; anything left out uses the built-in default.

| Key | Meaning |
|---|---|
| `description` | A note for people; shown by `voice_profiles.py list`. |
| `voice` | Kokoro voice or weighted blend such as `am_onyx(4)+am_adam(1)`. Use a plain voice if the server rejects blends. |
| `speed` | Server-side speed. Keep it near 1.0 and use `tempo` to slow delivery. |
| `pitch` | ffmpeg pitch shift. Below 1 is deeper; change it in small steps. |
| `tempo` | Final playback speed after the pitch change. |
| `bass_db` | Low-shelf bass boost around 150 Hz, in dB. |
| `fx` | `false` skips the ffmpeg post-processing entirely. |

Settings are chosen in this order: a command-line flag (`--voice`, `--pitch`, `--tempo`, `--bass`, `--speed`,
`--no-fx`), then the profile, then the built-in default. The file name (without `.json`) is the profile name.

The settings used for a book are recorded in `output/<slug>/chapters/voice_settings.json`. If you rerun with
different settings, the converter warns you, because chapters already finished keep the old voice.
