"""Restore the public Demo database into the local backend data directory."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "demo" / "aiexamcoach-demo.sqlite3"
MANIFEST = ROOT / "demo" / "manifest.json"
TARGET = ROOT / "backend" / "data" / "aiexamcoach.db"


def main() -> None:
    if not SNAPSHOT.is_file():
        raise SystemExit(f"Missing Demo snapshot: {SNAPSHOT}")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    expected = manifest.get("sha256")
    snapshot_digest = hashlib.sha256(SNAPSHOT.read_bytes()).hexdigest()
    if snapshot_digest != expected:
        raise SystemExit("Demo snapshot SHA256 does not match demo/manifest.json")
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SNAPSHOT, TARGET)
    digest = hashlib.sha256(TARGET.read_bytes()).hexdigest()
    if digest != expected:
        raise SystemExit("Restored Demo database SHA256 does not match manifest")
    print(f"Restored: {TARGET}")
    print(f"SHA256: {digest}")
    print("Demo login: username=demo, password=demo1234")
    print("AI provider: heuristic; no API key is required for the frozen Demo.")


if __name__ == "__main__":
    main()
