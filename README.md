# CardCopy

Copies the photos and videos off camera SD cards into tidy project folders, for example on Google Drive:

    Raw Photo\<Project>\Cam 1, Cam 2 ...
    Raw Video\<Project>\Cam 1, Cam 2 ...

Plug in your cameras (or put the cards in readers), tick the cards, press **Create folders + copy cards**.
CardCopy never deletes and never overwrites anything, on the cards or at the destination.

## Download

**[Download CardCopy for Windows](https://github.com/fahizzzle/cardcopy/releases/latest/download/CardCopy-Setup.exe)** (Windows 10 or 11, 64-bit)

If your antivirus holds the installer back, use the
[zip version](https://github.com/fahizzzle/cardcopy/releases/latest/download/CardCopy-Setup.zip): unzip it and double-click `Install.cmd`.

Windows may say "Windows protected your PC" because the installer is not code-signed yet: choose **More info > Run anyway**.
Installing a newer version over an old one keeps your settings. CardCopy tells you on launch when an update is available.

## What it does

- Finds every connected camera and card, and shows how many files will be copied from each
- Video cameras go to Raw Video, photo cameras to Raw Photo; you choose the Cam folder per camera or per card
- RAW photos and video clips by default; JPG/HEIF and clip XML files are optional
- Copies all cards at the same time, resumes after an interruption, optional checksum verification and offload receipt
- Can eject the cards and shut the PC down when copying, or the Google Drive upload, has finished

Made by Framed Horizon LLC.
