#!/usr/bin/env python3
"""
Play an audio file from the command line on Linux, macOS or Windows.

It uses the first player it finds, in this order: ffplay (ships with ffmpeg, which this project needs anyway),
mpv, VLC, then the platform's own tools (afplay on macOS; pw-play, paplay, play or aplay on Linux; Windows
SoundPlayer). Players that only handle wav/flac get a temporary wav made with ffmpeg when needed.

Usage:
  python play_audio.py clip.flac
  python play_audio.py output/arthas/arthas.m4b --start 1:30:00       # start offset (ffplay, mpv, vlc only)
  python play_audio.py --list-players                                  # what was found on this machine
  AUDIO_PLAYER="mpv --no-video" python play_audio.py clip.flac         # force a player (file path is appended)

Also importable: `from play_audio import play; play(path)` blocks until the clip has finished.
Keyboard controls (pause, seek, quit with q) work when run from the command line; ffplay and mpv show them.
"""
import argparse
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ANY = None
WAV_FLAC = {".wav", ".flac", ".ogg", ".oga"}
WAV = {".wav"}

# (name, executable, argument builder, formats the player handles, supports --start)
PLAYERS = [
    ("ffplay", "ffplay", lambda f, ss: ["-nodisp", "-autoexit", "-loglevel", "quiet", *(["-ss", ss] if ss else []), f], ANY, True),
    ("mpv", "mpv", lambda f, ss: ["--no-video", "--really-quiet", *([f"--start={ss}"] if ss else []), f], ANY, True),
    ("vlc", "cvlc", lambda f, ss: ["--play-and-exit", "--quiet", *([f"--start-time={_secs(ss)}"] if ss else []), f], ANY, True),
    ("vlc", "vlc", lambda f, ss: ["--intf", "dummy", "--play-and-exit", "--quiet", *([f"--start-time={_secs(ss)}"] if ss else []), f], ANY, True),
    ("afplay", "afplay", lambda f, ss: [f], ANY, False),  # macOS
    ("pw-play", "pw-play", lambda f, ss: [f], WAV_FLAC, False),
    ("paplay", "paplay", lambda f, ss: [f], WAV_FLAC, False),
    ("sox play", "play", lambda f, ss: ["-q", f], ANY, False),
    ("aplay", "aplay", lambda f, ss: ["-q", f], WAV, False),
]


def _secs(ts):
    """'1:30:00' / '90' / '12:05' -> seconds as a string (for players that want plain seconds)."""
    total = 0.0
    for part in str(ts).split(":"):
        total = total * 60 + float(part)
    return str(int(total)) if total == int(total) else str(total)


def _windows_player():
    ps = shutil.which("powershell") or shutil.which("pwsh")
    if os.name == "nt" and ps:
        return ("Windows SoundPlayer", ps, lambda f, ss: [
            "-NoProfile", "-Command", f"(New-Object Media.SoundPlayer '{f}').PlaySync()"], WAV, False)
    return None


def available_players():
    found = [p for p in PLAYERS if shutil.which(p[1])]
    win = _windows_player()
    if win:
        found.append(win)
    return found


def _to_wav(path):
    """Convert to a temporary wav with ffmpeg for players that cannot read this format."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError(f"Cannot play {path.suffix} files with the players found and ffmpeg is not installed.")
    tmp = Path(tempfile.mkstemp(suffix=".wav")[1])
    r = subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(path), str(tmp)], capture_output=True, text=True)
    if r.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg could not convert {path}: {r.stderr.strip()[-300:]}")
    return tmp


def play(path, start=None, interactive=False):
    """Play `path` and wait until it ends. Returns the name of the player used.

    interactive=False detaches the player from the keyboard so a prompt can keep reading input afterwards.
    Set AUDIO_PLAYER to force a player command, for example AUDIO_PLAYER="mpv --no-video".
    """
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    stdin = None if interactive else subprocess.DEVNULL

    forced = os.environ.get("AUDIO_PLAYER")
    if forced:
        cmd = shlex.split(forced)
        subprocess.run([*cmd, str(path)], stdin=stdin, check=False)
        return cmd[0]

    players = available_players()
    if not players:
        raise RuntimeError("No audio player found. Install ffmpeg (ffplay) or mpv, or set AUDIO_PLAYER.")
    # prefer a player that reads the format directly (and, if a start offset was asked for, can seek)
    ext = path.suffix.lower()
    direct = [p for p in players if p[3] is ANY or ext in p[3]]
    if start:
        direct = [p for p in direct if p[4]] or direct
    name, exe, build, formats, can_seek = (direct or players)[0]

    tmp = None
    target = path
    if formats is not ANY and ext not in formats:
        tmp = target = _to_wav(path)
    try:
        if start and not can_seek:
            print(f"({name} cannot start at an offset; playing from the beginning)", file=sys.stderr)
        subprocess.run([shutil.which(exe), *build(str(target), start if can_seek else None)],
                       stdin=stdin, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
    return name


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", help="audio file to play")
    ap.add_argument("--start", metavar="TIME", help="start offset such as 90, 12:05 or 1:30:00 (ffplay, mpv, vlc)")
    ap.add_argument("--list-players", action="store_true", help="show the players found on this machine and exit")
    args = ap.parse_args()

    if args.list_players:
        found = available_players()
        if os.environ.get("AUDIO_PLAYER"):
            print(f"AUDIO_PLAYER forces: {os.environ['AUDIO_PLAYER']}")
        for name, exe, _b, formats, can_seek in found:
            fmts = "all formats" if formats is ANY else "/".join(sorted(f.lstrip('.') for f in formats))
            print(f"  {name:<20} {shutil.which(exe)}  ({fmts}{', seek' if can_seek else ''})")
        if not found:
            print("  none found: install ffmpeg (ffplay) or mpv")
        return
    if not args.file:
        ap.error("give an audio file, or use --list-players")
    try:
        play(args.file, start=args.start, interactive=True)
    except (FileNotFoundError, RuntimeError) as e:
        sys.exit(f"play_audio: {e}")


if __name__ == "__main__":
    main()
