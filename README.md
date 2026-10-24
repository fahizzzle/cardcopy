# CardCopy

Copies the photos, videos and recordings off camera SD cards into tidy project folders, for example on Google Drive:

    Raw Photo\<Project>\Cam 1, Cam 2 ...
    Raw Video\<Project>\Cam 1, Cam 2 ...
    Raw Video\<Project>\Audio            (field recorders and wireless mics)

Plug in your cameras (or put the cards in readers), tick the cards, press **Create folders + copy cards**.
CardCopy never deletes and never overwrites anything, on the cards or at the destination.

## Download

### Windows

**[Download CardCopy for Windows](https://github.com/fahizzzle/cardcopy/releases/latest/download/CardCopy-Setup.exe)** (Windows 10 or 11, 64-bit)

If your antivirus holds the installer back, use the
[zip version](https://github.com/fahizzzle/cardcopy/releases/latest/download/CardCopy-Setup.zip): unzip it and double-click `Install.cmd`.

Windows may say "Windows protected your PC" because the installer is not code-signed yet: choose **More info > Run anyway**.

### Mac

**[Download CardCopy for Mac](https://github.com/fahizzzle/cardcopy/releases/latest/download/CardCopy-Installer.pkg)** (Apple silicon, macOS 13 or later)

Open it and click Continue, then Install: CardCopy goes into Applications. Or use the
[disk image](https://github.com/fahizzzle/cardcopy/releases/latest/download/CardCopy-mac.dmg) and drag CardCopy onto Applications.

The app is not notarized by Apple yet, so the first time macOS says it cannot verify it: click **Done**, then open
**System Settings > Privacy & Security** and choose **Open Anyway**.

Installing a newer version over an old one keeps your settings. CardCopy tells you on launch when an update is
available, and **Update now** installs it (on a Mac, after asking for your password once).

## What it does

- Finds every connected camera, recorder and card, and shows how many files will be copied from each
- Video cameras go to Raw Video, photo cameras to Raw Photo, recorders and wireless mics (DJI Mic and others) into the
  project's Raw Video folder; you choose the Cam folder per camera or per card
- RAW photos, video clips and recordings by default; JPG/HEIF and clip XML files are optional
- Copies all cards at the same time, resumes after an interruption, optional checksum verification and offload receipt
- Can eject the cards and shut the computer down when copying, or the Google Drive upload, has finished

Made by Framed Horizon LLC.
