#!/usr/bin/env python3
"""
Voice profiles: named sets of voice settings kept as small JSON files in the voices/ folder, so a voice can be
chosen with --profile NAME when making an audiobook (or testing pronunciations) instead of retyping flags.

A profile is a JSON file voices/NAME.json. Every key is optional; anything left out uses the built-in default:
  {
    "description": "Deep narrator for fantasy",
    "voice": "am_onyx(4)+am_adam(1)",   Kokoro voice or weighted blend (use a plain voice if the server rejects blends)
    "speed": 1.0,                        server-side speed; keep near 1.0
    "pitch": 0.94,                       ffmpeg pitch shift; below 1 is deeper
    "tempo": 0.90,                       final playback speed after the pitch change
    "bass_db": 4,                        low-shelf boost around 150 Hz, in dB
    "fx": true                           false skips the ffmpeg post-processing entirely
  }

Settings are chosen in this order: a flag on the command line, then the profile, then the built-in default.

Usage:
  python voice_profiles.py list                                 # profiles in voices/ and their settings
  python voice_profiles.py show deep-narrator
  python voice_profiles.py new gravel --voice am_michael --pitch 0.9 --description "Rougher, deeper"
  python voice_profiles.py new gravel2 --from gravel --tempo 0.85    # start from an existing profile
  tools/make-audiobook.sh "books/Some Book.epub" some-book --profile gravel
"""
import argparse
import json
import sys
from pathlib import Path

DEFAULT_VOICE = "am_onyx(4)+am_adam(1)"  # Kokoro-FastAPI weighted blend; use plain "am_onyx" if rejected
DEFAULT_PITCH = 0.94    # <1 lowers pitch (0.94 is about -1 semitone)
DEFAULT_TEMPO = 0.90    # final playback speed after the pitch change
BASS_GAIN_DB = 4        # low-shelf boost around 150 Hz

VOICES_DIR = Path(__file__).resolve().parent.parent / "voices"
BUILTIN = {"voice": DEFAULT_VOICE, "speed": 1.0, "pitch": DEFAULT_PITCH, "tempo": DEFAULT_TEMPO,
           "bass_db": BASS_GAIN_DB, "fx": True}
NUMBERS = ("speed", "pitch", "tempo", "bass_db")
KEYS = {"description", "voice", *NUMBERS, "fx"}


def _fail(msg):
    sys.exit(f"voice profile: {msg}")


def profile_path(name):
    """Find a profile by name (voices/NAME.json) or by an explicit path to a .json file."""
    p = Path(name)
    if p.suffix.lower() == ".json" and p.is_file():
        return p
    cand = VOICES_DIR / f"{name}.json"
    if cand.is_file():
        return cand
    names = ", ".join(sorted(f.stem for f in VOICES_DIR.glob("*.json"))) or "none yet"
    _fail(f"no profile named {name!r} in {VOICES_DIR} (available: {names})")


def validate(data, where):
    if not isinstance(data, dict):
        _fail(f"{where} must contain a JSON object")
    unknown = sorted(set(data) - KEYS)
    if unknown:
        _fail(f"{where} has unknown key(s) {', '.join(unknown)}; allowed: {', '.join(sorted(KEYS))}")
    for k in NUMBERS:
        if k in data and (isinstance(data[k], bool) or not isinstance(data[k], (int, float)) or data[k] <= 0):
            _fail(f"{where}: {k} must be a positive number")
    for k in ("voice", "description"):
        if k in data and not isinstance(data[k], str):
            _fail(f"{where}: {k} must be text")
    if "voice" in data and not data["voice"].strip():
        _fail(f"{where}: voice must not be empty")
    if "fx" in data and not isinstance(data["fx"], bool):
        _fail(f"{where}: fx must be true or false")
    return data


def load_profile(name):
    path = profile_path(name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        _fail(f"{path} is not valid JSON: {e}")
    return validate(data, path.name)


def list_profiles():
    """{name: settings} for every voices/*.json, in name order."""
    return {f.stem: load_profile(f) for f in sorted(VOICES_DIR.glob("*.json"))}


def add_voice_args(ap, opt_in_fx=False):
    """Add --profile and the voice flags to a parser. Defaults are None so resolve_voice can tell what was typed."""
    ap.add_argument("--profile", metavar="NAME", help="voice profile from voices/ (or a path to a profile .json); "
                    "flags below override it")
    ap.add_argument("--voice", help=f"Kokoro voice or blend (default {DEFAULT_VOICE})")
    ap.add_argument("--speed", type=float, help="server-side speed (keep near 1.0)")
    ap.add_argument("--pitch", type=float, help=f"pitch shift, below 1 is deeper (default {DEFAULT_PITCH})")
    ap.add_argument("--tempo", type=float, help=f"final playback speed (default {DEFAULT_TEMPO})")
    ap.add_argument("--bass", type=float, dest="bass_db", metavar="DB",
                    help=f"low-shelf bass boost in dB (default {BASS_GAIN_DB})")
    if opt_in_fx:
        ap.add_argument("--fx", action="store_true", help="apply the deep-voice pitch/tempo/bass processing "
                        "(on by itself when a --profile is given, unless the profile sets fx to false)")
    ap.add_argument("--no-fx", action="store_true", help="skip the deep-voice ffmpeg post-processing")


def resolve_voice(args, fx_default=True):
    """Fill args.voice/speed/pitch/tempo/bass_db and args.fx (bool) from flags, then the profile, then defaults."""
    profile = load_profile(args.profile) if getattr(args, "profile", None) else {}
    base = {**BUILTIN, **{k: v for k, v in profile.items() if k != "description"}}
    for k in ("voice", "speed", "pitch", "tempo", "bass_db"):
        if getattr(args, k, None) is None:
            setattr(args, k, base[k])
    if getattr(args, "no_fx", False):
        fx = False
    elif getattr(args, "fx", False):
        fx = True
    elif "fx" in profile:
        fx = profile["fx"]
    elif getattr(args, "profile", None):
        fx = BUILTIN["fx"]
    else:
        fx = fx_default
    args.fx = fx
    return args


def settings_of(args):
    """The effective settings as a plain dict (what is recorded next to a book's chapters)."""
    return {"voice": args.voice, "speed": args.speed, "pitch": args.pitch, "tempo": args.tempo,
            "bass_db": args.bass_db, "fx": bool(args.fx)}


def describe(name, data):
    merged = {**BUILTIN, **{k: v for k, v in data.items() if k != "description"}}
    fx = "on" if merged["fx"] else "off"
    line = (f"{name}: voice {merged['voice']}, speed {merged['speed']}, pitch {merged['pitch']}, "
            f"tempo {merged['tempo']}, bass {merged['bass_db']} dB, fx {fx}")
    return line + (f"\n    {data['description']}" if data.get("description") else "")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list the profiles in voices/")
    sh = sub.add_parser("show", help="show one profile")
    sh.add_argument("name")
    nw = sub.add_parser("new", help="create voices/NAME.json")
    nw.add_argument("name", help="letters, digits, '-' and '_' only")
    nw.add_argument("--from", dest="base", metavar="PROFILE", help="copy this profile first, then apply the flags")
    nw.add_argument("--description")
    nw.add_argument("--voice")
    for k in NUMBERS:
        nw.add_argument(f"--{k.replace('_', '-')}", type=float, dest=k)
    nw.add_argument("--fx", choices=["on", "off"])
    nw.add_argument("--force", action="store_true", help="overwrite an existing profile")
    args = ap.parse_args()

    if args.cmd == "list":
        profiles = list_profiles()
        if not profiles:
            print(f"No profiles in {VOICES_DIR}. Create one with: voice_profiles.py new NAME --voice ...")
        for name, data in profiles.items():
            print(describe(name, data))
        print(f"\nBuilt-in defaults (no --profile): {describe('defaults', {})}")
    elif args.cmd == "show":
        path = profile_path(args.name)
        print(f"{path}\n{path.read_text(encoding='utf-8').rstrip()}")
    else:
        if not args.name.replace("-", "").replace("_", "").isalnum():
            _fail("name may contain only letters, digits, '-' and '_'")
        dest = VOICES_DIR / f"{args.name}.json"
        if dest.exists() and not args.force:
            _fail(f"{dest} already exists (use --force to overwrite)")
        data = dict(load_profile(args.base)) if args.base else {}
        for k in ("description", "voice", *NUMBERS):
            if getattr(args, k) is not None:
                data[k] = getattr(args, k)
        if args.fx:
            data["fx"] = args.fx == "on"
        validate(data, dest.name)
        VOICES_DIR.mkdir(exist_ok=True)
        dest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Wrote {dest}\n{describe(args.name, data)}")


if __name__ == "__main__":
    main()
