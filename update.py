"""One-click WealthOS updater — double-click me.

Pulls the latest main from GitHub and redeploys the bot. Run on any
machine that has this repo and Modal access (`modal token new` done once).
The dashboard's update banner points here.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
os.environ.setdefault("PYTHONUTF8", "1")


def run(label, cmd):
    print(f"\n── {label} " + "─" * max(0, 58 - len(label)))
    r = subprocess.run(cmd, cwd=REPO)
    if r.returncode != 0:
        print(f"\n✗ {label} failed (exit {r.returncode}) — nothing further was run.")
        input("Press Enter to close…")
        sys.exit(r.returncode)


def main():
    print("WealthOS updater")
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=REPO,
                            capture_output=True, text=True).stdout.strip()
    if branch != "main":
        print(f"\n✗ This checkout is on branch '{branch}', not 'main'.")
        print("  Updates deploy the released main branch. Run: git checkout main")
        input("Press Enter to close…")
        sys.exit(1)

    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                           capture_output=True, text=True).stdout.strip()
    if dirty:
        print("\n✗ You have local uncommitted changes — refusing to update over them:")
        print("  " + "\n  ".join(dirty.splitlines()[:8]))
        input("Press Enter to close…")
        sys.exit(1)

    run("Pull latest main", ["git", "pull", "--ff-only", "origin", "main"])
    run("Install requirements", [sys.executable, "-m", "pip", "install", "-q",
                                 "-r", "requirements.txt"])
    run("Deploy to Modal", [sys.executable, "-m", "modal", "deploy",
                            "modal_signal_bot.py"])

    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                         capture_output=True, text=True).stdout.strip()
    print(f"\n✓ WealthOS updated and deployed ({sha}).")
    print("  Give the dashboard a minute before clicking actions (warm containers).")
    input("Press Enter to close…")


if __name__ == "__main__":
    main()
