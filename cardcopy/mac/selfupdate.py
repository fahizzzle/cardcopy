"""Install a downloaded update on a Mac. No Qt in here.

The update is the same CardCopy-Installer.pkg people download, already checked against the sha256 its
feed published (updates.download). CardCopy cannot replace itself while it runs, and after a package
install /Applications/CardCopy.app belongs to the system, so a small detached script takes over:

  1. waits for CardCopy to quit;
  2. runs the installer with administrator rights -- macOS shows one password prompt, saying what for;
  3. if the copy that asked for the update ran from outside Applications, moves it to the Trash, so the
     Mac is not left with an old second CardCopy (see copies.py);
  4. opens CardCopy again: the new build, or the old one when the prompt was cancelled.

Nothing is deleted: the installer replaces the app the way a hand-run install does, an old copy goes to
the Trash, and everything the script does is written to update.log beside it.
"""
from __future__ import annotations

import os
import subprocess
import sys

APP = "/Applications/CardCopy.app"            # where CardCopy-Installer.pkg puts it

_RUNNER = r"""#!/bin/sh
# Written by CardCopy to update itself. Waits for CardCopy to quit, installs, opens it again.
log="$(dirname "$0")/update.log"
say() { echo "$(date +%H:%M:%S)  $*" >> "$log"; }
pid="$1"; export CARDCOPY_PKG="$2"; app="$3"; old="$4"
say "waiting for CardCopy (pid $pid) to quit"
i=0
while kill -0 "$pid" 2>/dev/null && [ "$i" -lt 240 ]; do sleep 0.5; i=$((i + 1)); done
say "installing $CARDCOPY_PKG"
if /usr/bin/osascript \
    -e 'do shell script "/usr/sbin/installer -pkg " & quoted form of (system attribute "CARDCOPY_PKG") & " -target /" with prompt "CardCopy needs your password to install its update." with administrator privileges' \
    >> "$log" 2>&1; then
  say "installed"
  # The update went into Applications. The copy that asked for it, if it lived anywhere else (Downloads,
  # the Desktop), is now an old second CardCopy: into the Trash with it, from where it can be put back.
  # Never one on a disk image or another disk (/Volumes/...).
  case "$old" in
    ""|"$app"|/Volumes/*) ;;
    *)
      if [ -d "$old" ]; then
        dest="$HOME/.Trash/$(basename "$old" .app) (old $(date +%Y%m%d-%H%M%S)).app"
        if mv "$old" "$dest" 2>> "$log"; then say "moved the old copy $old to the Trash"; fi
      fi ;;
  esac
else
  say "NOT installed (the password prompt was cancelled, or the installer failed): opening the CardCopy already there"
fi
/usr/bin/open "$app"
say "done"
"""


def app_bundle() -> str:
    """The CardCopy.app this copy runs from, or '' when it runs from source."""
    exe = sys.executable or ""               # absolute already in a packaged app
    marker = ".app/Contents/MacOS/"
    i = exe.find(marker)
    return exe[:i + len(".app")] if i >= 0 else ""


def is_installed(folder: str | None = None) -> bool:
    """True for the packaged app, which an installer package can replace; False when run from source."""
    return bool(getattr(sys, "frozen", False)) and bool(app_bundle())


def apply(pkg_path: str, into: str | None = None, run: bool = True) -> str:
    """Leave a detached job running that installs pkg_path once CardCopy has quit, then reopens it.

    The caller should quit straight afterwards. Returns the path of the script that was started.
    """
    from ..selfupdate import staging_dir
    if not is_installed():
        raise ValueError("CardCopy is not running as CardCopy.app, so there is nothing to update in place")
    if not pkg_path.lower().endswith(".pkg") or not os.path.isfile(pkg_path):
        raise ValueError(f"not an installer package: {pkg_path}")
    work = staging_dir()
    runner = os.path.join(work, "run-update.sh")
    with open(runner, "x", encoding="utf-8") as f:       # exclusive: a fresh folder, a fresh file
        f.write(_RUNNER)
    os.chmod(runner, 0o755)
    reopen = APP if os.path.isdir(APP) else (into or app_bundle() or APP)
    if run:
        subprocess.Popen(["/bin/sh", runner, str(os.getpid()), pkg_path, reopen, app_bundle()], cwd=work,
                         start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
    return runner
