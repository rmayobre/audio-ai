#!/usr/bin/env python3
"""
A stand-in for Kokoro-FastAPI used by the smoke test: answers POST /v1/audio/speech with a short FLAC tone
whose length depends on the text, and logs every request's text to a file so tests can check what was sent.

usage: python fake_kokoro_server.py PORT REQUEST_LOG
"""
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

LOG = sys.argv[2] if len(sys.argv) > 2 else "requests.log"


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"voice": body.get("voice"), "input": body.get("input")}) + "\n")
        seconds = max(0.3, min(3.0, len(body.get("input", "")) / 400))
        audio = subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}",
             "-ar", "24000", "-f", "flac", "-"], capture_output=True, check=True).stdout
        self.send_response(200)
        self.send_header("Content-Type", "audio/flac")
        self.send_header("Content-Length", str(len(audio)))
        self.end_headers()
        self.wfile.write(audio)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
