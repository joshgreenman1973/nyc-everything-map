#!/usr/bin/env python3
"""Unattended refresh of the Everything Map's "Eating nearby" restaurant data.

Pulls fresh DOHMH data (via build_restaurants.py), and if the cuisine/point data
actually changed, commits and pushes docs/data/restaurants.json to origin/main so
the live GitHub Pages map updates. Notifies Josh via iMessage on the outcome.

Run by launchd (com.joshgreenman.everything-map-restaurants); also safe to run by
hand: python3 scripts/refresh_restaurants.py
"""
import json, os, subprocess, sys
from datetime import datetime

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
DATA = os.path.join(REPO, "docs", "data", "restaurants.json")
BUILD = os.path.join(REPO, "scripts", "build_restaurants.py")
IMESSAGE_TO = "9175823254"  # per Josh's standing notification preference
# This repo belongs to joshgreenman1973, but the machine may have another GitHub
# account (e.g. vitalcity-nyc) set active. Push with this account's token
# explicitly so the unattended job never pushes (or fails) as the wrong account.
GH = "/Users/joshgreenman/.local/bin/gh"
GH_USER = "joshgreenman1973"
REPO_SLUG = "joshgreenman1973/nyc-everything-map"


def git(*args, check=True):
    return subprocess.run(["/usr/bin/git", "-C", REPO, *args],
                          capture_output=True, text=True, check=check)


def notify(body):
    body = body.replace('"', "'").replace(chr(92), "")
    script = ('tell application "Messages"\n'
              'set s to 1st account whose service type = iMessage\n'
              f'send "{body}" to participant "{IMESSAGE_TO}" of s\n'
              'end tell')
    try:
        subprocess.run(["/usr/bin/osascript", "-e", script], check=True, timeout=30)
    except Exception as e:  # noqa: BLE001
        print(f"iMessage send failed: {e}", file=sys.stderr)


def push_as_owner():
    """git push origin main, authenticating as the repo owner regardless of which
    GitHub account is currently 'active' on the machine. Falls back to a plain
    push if the per-account token can't be retrieved."""
    try:
        tok = subprocess.run([GH, "auth", "token", "--user", GH_USER],
                             capture_output=True, text=True, timeout=20)
        token = tok.stdout.strip()
    except Exception:  # noqa: BLE001
        token = ""
    if token:
        url = f"https://x-access-token:{token}@github.com/{REPO_SLUG}.git"
        res = git("push", url, "HEAD:main", check=False)
        # never let the token reach the log
        res.stdout = res.stdout.replace(token, "***")
        res.stderr = res.stderr.replace(token, "***")
        return res
    return git("push", "origin", "main", check=False)


def signature(path):
    """Content fingerprint that ignores the volatile 'built' date."""
    with open(path) as f:
        d = json.load(f)
    return json.dumps({k: d.get(k) for k in ("cuisines", "city", "cityTotal", "pts")},
                      sort_keys=True)


def main():
    print(f"=== {datetime.now():%Y-%m-%d %H:%M} restaurant refresh start ===")

    # Start from a clean, current main (discard any half-finished local rebuild).
    if os.path.exists(DATA):
        git("checkout", "--", "docs/data/restaurants.json", check=False)
    git("pull", "--ff-only", "origin", "main", check=False)

    before = signature(DATA) if os.path.exists(DATA) else None

    r = subprocess.run(["/usr/bin/python3", BUILD], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode != 0:
        notify("Everything Map: restaurant data refresh FAILED at build step. "
               "See scripts/refresh.log.")
        sys.exit(1)

    after = signature(DATA)
    if before == after:
        print("no substantive change since last run; nothing to commit")
        return

    total = json.load(open(DATA))["cityTotal"]
    git("add", "docs/data/restaurants.json")
    git("commit", "-m",
        f"Refresh Eating-nearby restaurant data ({total} restaurants) [skip ci]")
    push = push_as_owner()
    if push.returncode == 0:
        print("pushed")
        notify(f"Everything Map: restaurant data refreshed - {total:,} restaurants, "
               "pushed live.")
    else:
        sys.stderr.write(push.stderr)
        notify("Everything Map: restaurant data rebuilt but PUSH FAILED. "
               "See scripts/refresh.log.")
        sys.exit(1)

    print(f"=== {datetime.now():%Y-%m-%d %H:%M} done ===")


if __name__ == "__main__":
    main()
