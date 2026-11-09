#!/usr/bin/env python3
"""Copy the frontend source files into dist/ (the only folder the API serves) and fingerprint asset links.

Every script/stylesheet link in the dist pages gets ?v=<first 8 hex of sha256 of the file>, so a changed file
always gets a new address and browsers never keep running an old copy. Same result as scripts/sync_dist.ps1.

    python scripts/sync_dist.py
"""
import hashlib
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "index.html", "app.js", "phase1-features.js", "phase1.css", "styles.css",
    "api-integration.js", "app-api-wiring.js", "app-api-engagement.js", "user-journey.js", "analyst.html", "workspace.js",
    "app-api-alpha.js", "app-api-talent.js", "app-api-onboard.js", "app-api-course.js", "careers.html", "careers.js",
    "careers.css", "boot.js", "company-profile.js", "company-profile.css", "app-api-company.js", "chat.js", "chat.css",
    "app-api-messages.js",
]


def main() -> None:
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    for f in FILES:
        shutil.copyfile(ROOT / f, dist / f)
    prints = {f: hashlib.sha256((dist / f).read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:8]
              for f in FILES if f.endswith((".js", ".css"))}
    pattern = re.compile(r'(?P<attr>src|href)="(?P<file>[A-Za-z0-9_.\-]+\.(js|css))(\?v=[^"]*)?"')

    def stamp(m: re.Match) -> str:
        name = m.group("file")
        return f'{m.group("attr")}="{name}?v={prints[name]}"' if name in prints else m.group(0)

    for page in (f for f in FILES if f.endswith(".html")):
        path = dist / page
        path.write_text(pattern.sub(stamp, path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"Synced {len(FILES)} files to dist/ (asset links fingerprinted)")


if __name__ == "__main__":
    main()
