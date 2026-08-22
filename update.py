"""One-click WealthOS updater — double-click me.

Pulls the latest main from GitHub and redeploys the bot. Run on any machine
that has this repo cloned and Modal access (`modal token new` done once).
The dashboard's update banner points here.

Note: updates need a real git *clone*. A folder unzipped from GitHub's
"Download ZIP" has no history, so nothing can be pulled — and the deploy
can't stamp a version into the image, which is why such an instance never
shows the update banner either.
"""
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
os.environ.setdefault("PYTHONUTF8", "1")

CLONE_HINT = (
    "  git clone https://github.com/feartherealworld/PortfolioAutomation.git\n"
    "  cd PortfolioAutomation\n"
    "  python manage.py        # paste this instance's tokens, Save & Deploy"
)


def git(*args, capture=True):
    """Run a git command in the repo; return stdout (stripped) or ''. """
    r = subprocess.run(["git", *args], cwd=REPO, capture_output=capture, text=True)
    return (r.stdout or "").strip() if capture else ""


def run(label, cmd):
    print(f"\n── {label} " + "─" * max(0, 58 - len(label)))
    r = subprocess.run(cmd, cwd=REPO)
    if r.returncode != 0:
        print(f"\n✗ {label} failed (exit {r.returncode}) — nothing further was run.")
        input("Press Enter to close…")
        sys.exit(r.returncode)


def bail(msg, *extra):
    print("\n✗ " + msg)
    for line in extra:
        print(line)
    input("\nPress Enter to close…")
    sys.exit(1)


def ask(question):
    return input(question).strip().lower() in ("y", "yes")


def main():
    print("WealthOS updater")

    # ── 1. Is this a git clone at all? ──────────────────────────────────────
    inside = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"],
                            cwd=REPO, capture_output=True, text=True)
    if inside.returncode != 0 or inside.stdout.strip() != "true":
        bail("This folder isn't a git clone, so there's nothing to pull.",
             "  It was most likely unzipped from GitHub's 'Download ZIP'.",
             "  Updates (and the dashboard's update banner) need a clone:",
             "", CLONE_HINT)

    if not git("remote"):
        bail("This clone has no GitHub remote configured.",
             "  Add one with:",
             "    git remote add origin "
             "https://github.com/feartherealworld/PortfolioAutomation.git")

    # ── 2. On the released branch? ──────────────────────────────────────────
    branch = git("branch", "--show-current")
    if branch != "main":
        where = f"branch '{branch}'" if branch else "a detached commit"
        print(f"\nThis checkout is on {where}, not 'main'.")
        print("Updates deploy the released main branch.")
        if not ask("Switch to main and update? [y/N] "):
            print("\nNothing was changed.")
            input("Press Enter to close…")
            sys.exit(1)
        # a switch can be blocked by local edits; handle them the same way below
        if git("status", "--porcelain") and not offer_to_set_aside():
            sys.exit(1)
        run("Switch to main", ["git", "checkout", "main"])

    # ── 3. Local changes? Offer to set them aside rather than dead-end ──────
    if git("status", "--porcelain") and not offer_to_set_aside():
        sys.exit(1)

    # ── 4. Update and deploy ────────────────────────────────────────────────
    run("Pull latest main", ["git", "pull", "--ff-only", "origin", "main"])
    run("Install requirements", [sys.executable, "-m", "pip", "install", "-q",
                                 "-r", "requirements.txt"])
    run("Deploy to Modal", [sys.executable, "-m", "modal", "deploy",
                            "modal_signal_bot.py"])

    sha = git("rev-parse", "--short", "HEAD")
    print(f"\n✓ WealthOS updated and deployed ({sha}).")
    print("  Give the dashboard a minute before clicking actions (warm containers).")
    input("Press Enter to close…")


def offer_to_set_aside():
    """Show what's locally modified and offer to stash it. True = safe to go on.

    An instance that only ever downloads from GitHub still drifts: the deploy
    writes signalbot/_build.py, editors touch files, line endings differ. None
    of that is worth blocking an update — but it isn't ours to delete either,
    so it goes into a git stash that `git stash pop` can bring back.
    """
    dirty = git("status", "--porcelain")
    print("\nThis checkout has local changes:")
    for line in dirty.splitlines()[:12]:
        print("   " + line)
    if len(dirty.splitlines()) > 12:
        print(f"   … and {len(dirty.splitlines()) - 12} more")
    print("\nIf you never edit files here, these are stray/generated files and")
    print("setting them aside is safe (recover any time with: git stash pop).")
    if not ask("Set them aside and update? [y/N] "):
        print("\nNothing was changed. Commit or stash them, then run this again.")
        input("Press Enter to close…")
        return False
    run("Set local changes aside", ["git", "stash", "push", "-u",
                                    "-m", "auto-stash before WealthOS update"])
    return True


if __name__ == "__main__":
    main()
