r"""Replace this installed copy of CardCopy with a newer one. No Qt in here.

CardCopy cannot overwrite itself while it is running: Windows holds its own pythonw.exe and the
DLLs it has loaded. So the work is handed to a small PowerShell script that waits for CardCopy to
close, runs the downloaded installer's own install.ps1 (the same script Install.cmd runs, silently
and into the same folder), and starts CardCopy again.

What is run is the ZIP installer, never the Setup.exe. The zip contains no executable of ours --
just an embedded Python signed by the PSF, the app's .py files and install.ps1 -- which is why
antivirus leaves it alone, while a freshly built unsigned Setup.exe is quarantined for hours.

Nothing here deletes anything: staging goes into its own new folder each time, and replacing the
installed files is install.ps1's job, exactly as it is for a hand-run install.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import zipfile

# CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP: no console window, and nothing that happens to
# CardCopy's own console can reach the job. NOT DETACHED_PROCESS: powershell.exe given no console at
# all exits 0 immediately without running the script, which leaves the update silently undone (seen
# on Windows 10). The job outlives us either way -- Windows does not end a process because its
# parent did.
_DETACHED = 0x08000000 | 0x00000200


def install_dir() -> str:
    r"""The folder CardCopy is installed in: the one holding the cardcopy package and python\."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_installed(folder: str | None = None) -> bool:
    """True only for a real install, where there is an embedded Python to relaunch and files to replace.

    False when running from the source checkout or a venv, where updating in place would be wrong:
    there the download link goes to the browser instead.
    """
    folder = folder or install_dir()
    return (os.path.isfile(os.path.join(folder, "python", "pythonw.exe"))
            and os.path.isfile(os.path.join(folder, "cardcopy", "__init__.py")))


def staging_dir() -> str:
    """A folder of our own for this attempt; never reused, so nothing is ever written over."""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = os.path.join(tempfile.gettempdir(), "CardCopy-update")
    for n in range(100):
        path = os.path.join(base, stamp if n == 0 else f"{stamp}-{n}")
        if not os.path.exists(path):
            os.makedirs(path)
            return path
    raise OSError("could not make a folder to unpack the update into")


def unpack(zip_path: str, into: str) -> str:
    """Unpack the downloaded installer and return the folder holding install.ps1."""
    with zipfile.ZipFile(zip_path) as archive:
        for name in archive.namelist():         # a zip may not write outside the folder it is given
            if os.path.isabs(name) or ".." in name.replace("\\", "/").split("/"):
                raise ValueError(f"the update archive holds an unsafe path: {name}")
        archive.extractall(into)
    for folder, _dirs, names in os.walk(into):
        if "install.ps1" in names:
            return folder
    raise ValueError("the update archive has no install.ps1 in it")


_RUNNER = r"""
# Written by CardCopy to update itself. Waits for CardCopy to close, installs, starts it again.
# Everything it does is written to update.log beside this script, so a failed update can be read back.
param([int]$Waiting, [string]$Setup, [string]$Into)
$log = Join-Path $PSScriptRoot "update.log"
function Say($text) { "$(Get-Date -Format 'HH:mm:ss')  $text" | Out-File -FilePath $log -Append -Encoding utf8 }

# Wait for CardCopy to let go of its files. The pid alone is not enough to go on: Windows reuses pids,
# so a stranger inheriting it would have us wait for nothing. What actually matters is that no CardCopy
# is left running out of the folder about to be replaced, which is also true of a copy the user opened
# a second time.
function StillRunning {
    if (Get-Process -Id $Waiting -ErrorAction SilentlyContinue) {
        $mine = Get-CimInstance Win32_Process -Filter "ProcessId = $Waiting" -ErrorAction SilentlyContinue
        if ($mine -and $mine.ExecutablePath -and $mine.ExecutablePath.StartsWith($Into, "OrdinalIgnoreCase")) { return $true }
    }
    $others = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe' OR Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($Into, "OrdinalIgnoreCase") }
    return [bool]$others
}
Say "waiting for CardCopy (pid $Waiting) to close"
for ($i = 0; $i -lt 240; $i++) {
    if (-not (StillRunning)) { break }
    Start-Sleep -Milliseconds 500
}
Start-Sleep -Milliseconds 700          # let Windows release the files it had open

# One retry: a virus scanner reading the files we just unpacked can hold one for a moment, and
# robocopy then reports the whole install as failed over a file that would copy a second later.
foreach ($try in 1, 2) {
    Say "installing $Setup into $Into (attempt $try)"
    & powershell -ExecutionPolicy Bypass -File (Join-Path $Setup "install.ps1") -Silent -InstallDir $Into 2>&1 |
        Out-File -FilePath $log -Append -Encoding utf8
    if ($LASTEXITCODE -eq 0) { break }
    Say "attempt $try failed ($LASTEXITCODE)"
    if ($try -eq 2) { Say "GIVING UP; CardCopy was not started, nothing else was changed"; exit 1 }
    Start-Sleep -Seconds 5
}
Say "installed; starting CardCopy again"
Start-Process (Join-Path $Into "python\pythonw.exe") -ArgumentList "-m cardcopy" -WorkingDirectory $Into
Say "done"
"""


def apply(zip_path: str, into: str | None = None, run: bool = True) -> str:
    """Unpack the update and leave a detached job running that installs it once CardCopy exits.

    The caller should quit straight afterwards: the job waits for this process either way, but the
    sooner it goes, the sooner the new version is up. Returns the path of the script that was started.
    """
    into = into or install_dir()
    if not is_installed(into):
        raise ValueError(f"{into} is not a CardCopy install, so there is nothing to update in place")
    work = staging_dir()
    setup = unpack(zip_path, work)
    runner = os.path.join(work, "run-update.ps1")
    with open(runner, "x", encoding="utf-8") as f:       # exclusive: a fresh folder, a fresh file
        f.write(_RUNNER)
    if run:
        subprocess.Popen(
            ["powershell", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", runner,
             "-Waiting", str(os.getpid()), "-Setup", setup, "-Into", into],
            creationflags=_DETACHED, close_fds=True,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            cwd=work)
    return runner


if sys.platform == "darwin":            # a Mac installs the downloaded CardCopy-Installer.pkg instead
    from .mac.selfupdate import apply, is_installed  # noqa: E402,F401,F811
