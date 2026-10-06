#!/usr/bin/env python3
"""Fetch vendor deprecation pages (urllib with curl fallback, hard per-source deadline).
Saves raw HTML to data/raw/<name>-<UTC stamp>.html with a .sha256 receipt; a failed
fetch leaves a .failed marker so the build refuses to fall back silently."""
from __future__ import annotations
import hashlib
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
FETCH_DEADLINE_SECONDS = 60

SOURCES = [
    ("anthropic", "https://docs.claude.com/en/docs/about-claude/model-deprecations"),
    ("openai", "https://developers.openai.com/api/docs/deprecations"),
]

def _fetch_urllib(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()

def _fetch_curl(url: str) -> bytes:
    proc = subprocess.run(["curl", "-sL", "--max-time", "40", "-A", UA, url],
                          capture_output=True, check=False, timeout=45)
    if proc.returncode != 0:
        raise RuntimeError(f"curl exit {proc.returncode}: {proc.stderr.decode()[:200]}")
    return proc.stdout

def fetch(url: str) -> bytes:
    result: dict = {"ok": False, "data": None, "error": None}
    def work() -> None:
        try:
            result["data"] = _fetch_urllib(url)
            result["ok"] = True
        except Exception as exc:
            result["error"] = f"urllib: {exc}"
            try:
                result["data"] = _fetch_curl(url)
                result["ok"] = True
            except Exception as exc2:
                result["error"] = f"urllib: {exc}; curl: {exc2}"
    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout=FETCH_DEADLINE_SECONDS)
    if t.is_alive():
        raise RuntimeError(f"timed out after {FETCH_DEADLINE_SECONDS}s (hanging server)")
    if not result["ok"]:
        raise RuntimeError(result["error"])
    return result["data"]

def main() -> None:
    raw = Path(__file__).resolve().parent.parent / "data" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for name, url in SOURCES:
        base = raw / f"{name}-{ts}"
        try:
            body = fetch(url)
        except Exception as exc:
            base.with_suffix(".failed").write_text(f"{url}\n{exc}\n", encoding="utf-8")
            print(f"FAIL {name}: {exc}", file=sys.stderr)
            continue
        base.with_suffix(".html").write_bytes(body)
        base.with_suffix(".sha256").write_text(f"{hashlib.sha256(body).hexdigest()}  {base.name}.html\n", encoding="utf-8")
        print(f"OK {name}: {len(body)} bytes -> {base.name}.html")

if __name__ == "__main__":
    main()
