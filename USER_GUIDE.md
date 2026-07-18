# VidSnap User Guide

VidSnap splits a video into short segments — about 2 minutes each by default —
and saves them as new video files. It does this **without re-encoding**, so the
segments are bit-identical to the source: no quality loss, and even a
multi-gigabyte file usually finishes in seconds.

Everything happens on your computer. VidSnap has no accounts, no cloud, and no
telemetry. Nothing you feed it leaves the machine.

---

## 1. Install

1. Download `VidSnapSetup-<version>.exe` from the
   [latest release](https://github.com/SATCORPDEVS/VIDSNAP/releases).
2. Run it. There is nothing else to install — FFmpeg ships inside VidSnap.

Notes:

- **No administrator rights needed.** If you can elevate, it installs for all
  users; if not, it quietly installs just for you.
- **Windows SmartScreen may warn you** that the publisher is unrecognised. The
  build isn't code-signed (a certificate costs a few hundred dollars a year and
  has been deferred). If you trust the download, choose **More info → Run
  anyway**.
- Two optional checkboxes during setup:
  - **Create a desktop icon**
  - **Add VidSnap to PATH** — tick this if you want to type `vidsnap` in a
    terminal. You can install without it and still use the GUI.

To remove VidSnap later, use **Settings → Apps → Installed apps → VidSnap →
Uninstall**.

---

## 2. Using the app (GUI)

Launch **VidSnap** from the Start Menu.

![The window has: Video, Segment length, Output folder, a progress bar, a status
line, and the Open folder / Cancel / Split buttons.]

### Step by step

1. **Video** — click **Choose…** and pick your file. VidSnap immediately reads
   the file and shows a summary in the status line, e.g.
   `holiday.mp4 — 47m 12s, 1920x1080 h264`.
2. **Segment length** — how many minutes each piece should be. The default is
   `2`. Decimals are fine: `0.5` gives 30-second pieces.
3. **Output folder** — filled in for you as `<video name>_segments` next to the
   source video. Change it with **Choose…** if you'd rather put the pieces
   elsewhere.
4. **Exact cuts** — leave this **off** unless you specifically need it. See
   [section 4](#4-why-a-2-minute-segment-comes-out-at-203).
5. Press **Split**. The progress bar fills as FFmpeg works.
6. When it finishes, the status line reports how many files were created, and
   **Open folder** opens them in File Explorer.

### Cancelling

**Cancel** stops the split immediately. Segments that were already finished are
kept and remain playable; the one FFmpeg was midway through writing is deleted,
because a half-written video file won't play. Closing the window during a split
does the same thing.

### Output file names

Segments are numbered from 1 and keep the source's container format:

```
holiday_segments\holiday_part_001.mp4
holiday_segments\holiday_part_002.mp4
holiday_segments\holiday_part_003.mp4
```

Each segment starts at 00:00 in its own timeline, so they play normally in any
player.

---

## 3. Using the command line (CLI)

Available in any terminal if you ticked **Add VidSnap to PATH** during install.
(If you didn't, the executable still lives at `vidsnap.exe` inside the
installation folder — typically `C:\Program Files\VidSnap\`.)

```
vidsnap <input> [--minutes 2] [--out DIR] [--exact]
```

| Option | Meaning |
| --- | --- |
| `input` | Path to the source video. Required. |
| `--minutes N` | Segment length in minutes. Default `2`. Accepts decimals. |
| `--out DIR` | Where to write segments. Default `<input name>_segments` next to the input. |
| `--exact` | Frame-exact cuts by re-encoding. Much slower; see below. |
| `--version` | Print the version and exit. |

### Examples

```powershell
vidsnap "C:\Videos\lecture.mp4"                        # 2-minute pieces, alongside the source
vidsnap "C:\Videos\lecture.mp4" --minutes 5            # 5-minute pieces
vidsnap "C:\Videos\lecture.mp4" --out "D:\clips"       # choose the destination
vidsnap "C:\Videos\lecture.mp4" --minutes 1 --exact    # exactly 1:00 each, re-encoded
```

### What you'll see

```
lecture.mp4: 47m 12s, 1920x1080 h264 -> ~24 segment(s) of 2 min
  [##############################] 100%
Done. 24 file(s) created in C:\Videos\lecture_segments
```

VidSnap exits with status `0` on success and `1` on error, so it scripts cleanly.

---

## 4. Why a "2-minute" segment comes out at 2:03

This is the one thing worth understanding about VidSnap.

Video is stored as occasional complete frames (**keyframes**) followed by frames
that only describe what changed. A cut can only be made *at* a keyframe — cutting
anywhere else would require rebuilding the video, which means re-encoding it and
losing quality.

So VidSnap cuts at the first keyframe at or after each 2-minute mark. If your
video has a keyframe every 3 seconds, segments land somewhere in 2:00–2:03. Screen
recordings are the extreme case: 10 seconds between keyframes is common, so
segments can run to 2:10.

VidSnap measures the finished segments and tells you when they ran long, rather
than letting you discover it in a player later:

```
Segments run up to 2m 10s rather than 2m 0s: cuts can only land on the source's
keyframes, which are up to 10s apart. Use exact-cut mode for exact lengths.
```

### Exact-cut mode

If exact boundaries matter more than perfect fidelity — an upload limit of
exactly 60 seconds, for instance — use **Exact cuts** (GUI) or `--exact` (CLI).
VidSnap re-encodes the video so a keyframe falls precisely on every boundary.

The trade-offs, plainly:

- **Much slower.** Minutes or hours instead of seconds — it's re-compressing
  every frame.
- **One generation of quality loss.** The setting used (CRF 17, `slow`) is
  visually transparent for most material, but it is no longer bit-identical.
- Audio and subtitles are still copied untouched; only the video is re-encoded.

This is never the default, and both the GUI and CLI say so before they start.

---

## 5. Advisories VidSnap shows before splitting

These are warnings, not errors — the split still runs.

**"… is inside a cloud-synced folder."**
Your output folder is under OneDrive, Dropbox, Google Drive, or iCloud. Because
splitting is lossless, the segments together are roughly the size of the source
video, so your sync client is about to upload that much again. Pick a local
folder if you only want the files on this machine.

**"The output folder is on D: but the source is on C:."**
Every byte has to cross between drives (or over a network share), which will
dominate the runtime of what is otherwise a seconds-long operation.

**"N subtitle format(s) … will be dropped."**
MP4 and MOV containers can only carry `mov_text` subtitles. If your source has
SubRip or ASS subtitles and the output is `.mp4`, those tracks can't come along.
An `.mkv` source keeps every stream.

---

## 6. What VidSnap handles

**Formats.** MP4, MKV, MOV, AVI, M4V, WebM, WMV, FLV, MPG/MPEG, TS — and
anything else FFmpeg reads. Segments always use the same container as the source;
VidSnap never converts formats.

**Large files.** FFmpeg streams the file rather than loading it, so a 10 GB
source uses no more memory than a small one. Make sure you have disk space for
roughly a second copy of the video.

**All tracks.** Every stream the container allows is carried through — multiple
audio tracks, subtitles, rotation metadata, and so on.

**Short videos.** If your video is shorter than one segment, you get a single
output file that is a lossless copy of the whole thing, plus a note saying so.

---

## 7. Troubleshooting

**"No video stream found in …"**
The file is audio-only, an image, or corrupt. VidSnap only splits videos.

**"ffprobe could not read …"**
The file isn't a media file VidSnap can parse, is truncated, or is locked by
another program. Try playing it first to confirm it's intact.

**"Input file does not exist"**
Check the path. In a terminal, wrap paths containing spaces in quotes.

**The split is unexpectedly slow.**
Almost always one of three things: exact-cut mode is on, the output is on a
different drive or network share, or an antivirus is scanning each file as it's
written.

**The last segment is short.**
Expected — it's the remainder. A 47-minute video in 2-minute pieces ends with a
1-minute one.

**Something else went wrong.**
VidSnap keeps a local log at:

```
%LOCALAPPDATA%\VidSnap\vidsnap.log
```

It records what was run and any FFmpeg errors, and it never leaves your machine.
It's the right thing to attach to a bug report.

---

## 8. Privacy

VidSnap makes no network connections at all. No accounts, no update checks, no
analytics, no crash reporting. The log file described above is local only.

The single piece of this project that touches the network is a developer script
used to download FFmpeg when building VidSnap from source — it isn't part of the
installed app.

---

## 9. License

VidSnap is licensed under **GPL-3.0-or-later** and bundles the GPL build of
FFmpeg. The full terms are in [`LICENSE`](LICENSE), also installed alongside the
program. FFmpeg is a separate work under its own license.

Source for any released installer is this repository at the matching `v<version>`
tag; see the source offer in [`README.md`](README.md).
