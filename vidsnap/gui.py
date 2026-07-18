"""Tkinter GUI — pick a video, choose a segment length, split it losslessly.

Two things govern the structure of this module:

**DPI awareness must happen before the Tk root exists.** Windows decides a
process's scaling behaviour when its first window is created, so
:func:`_enable_dpi_awareness` runs in :func:`main` before ``tk.Tk()``. Without
it the whole UI renders blurry on any modern high-DPI display.

**Tkinter is not thread-safe.** The split runs on a worker thread so the window
stays responsive, but that thread never touches a widget. It posts messages to a
:class:`queue.Queue`, and the UI thread drains that queue from a ``after()``
timer. Cancellation goes the other way through a :class:`threading.Event`, which
:func:`vidsnap.splitter.split` polls.
"""

from __future__ import annotations

import contextlib
import ctypes
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from vidsnap import __version__, ffmpeg, paths, probe, splitter
from vidsnap.humanize import format_duration
from vidsnap.log import get_logger, setup_logging

_logger = get_logger()


# --------------------------------------------------------------------------- #
# Worker -> UI messages
#
# The worker thread may not touch widgets, so it posts one of these instead and
# the UI thread acts on it. Modelling them as distinct types (rather than
# ``(str, Any)`` tuples) keeps the payloads type-checked at the boundary.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _Progress:
    """Fractional completion in ``[0.0, 1.0]``."""

    fraction: float


@dataclass(frozen=True)
class _Finished:
    """The split ended — either completed or cancelled — with these segments.

    ``note`` carries anything worth telling the user about the finished run, such
    as segments that ran long because the source's keyframes are far apart.
    """

    segments: tuple[Path, ...]
    cancelled: bool
    note: str | None = None


@dataclass(frozen=True)
class _Failed:
    """The split raised; ``message`` is already user-facing."""

    message: str


_Message = _Progress | _Finished | _Failed

# How often the UI thread drains the worker's message queue.
_POLL_INTERVAL_MS = 80

_VIDEO_FILETYPES = [
    ("Video files", "*.mp4 *.mkv *.mov *.avi *.m4v *.webm *.wmv *.flv *.mpg *.mpeg *.ts"),
    ("All files", "*.*"),
]


def _enable_dpi_awareness() -> None:
    """Opt into per-monitor DPI awareness on Windows (no-op elsewhere)."""
    if os.name != "nt":
        return
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        # Older Windows without shcore — fall back to the system-DPI-aware API.
        with contextlib.suppress(AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]


def _apply_tk_scaling(root: tk.Tk) -> None:
    """Scale Tk's fonts to the display DPI.

    DPI *awareness* stops Windows from bitmap-stretching the window, but Tk still
    lays out at 72 dpi, so on a 150% display everything comes out small and
    sharp instead of blurry. Telling Tk the real DPI fixes the sizing too.
    """
    with contextlib.suppress(tk.TclError, ZeroDivisionError):
        dpi = float(root.winfo_fpixels("1i"))
        if dpi > 0:
            root.tk.call("tk", "scaling", dpi / 72.0)


def open_folder(path: Path) -> None:
    """Reveal ``path`` in the platform file manager. Best-effort; never raises."""
    try:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]  # Windows-only API
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except OSError:
        _logger.warning("could not open folder %s", path, exc_info=True)


class VidSnapApp:
    """The main window: source picker, segment length, output dir, progress.

    ``root`` is normally the ``tk.Tk`` root, but any top-level window works — the
    class only uses the window-manager methods both types share. Tests take
    advantage of that to host each case in its own ``Toplevel`` under a single
    shared root.
    """

    def __init__(self, root: tk.Tk | tk.Toplevel) -> None:
        self.root = root
        self._messages: queue.Queue[_Message] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._cancel_event: threading.Event | None = None
        self._result_dir: Path | None = None

        root.title(f"VidSnap {__version__}")
        root.minsize(560, 0)
        root.columnconfigure(0, weight=1)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.minutes_var = tk.StringVar(value=f"{splitter.DEFAULT_SEGMENT_SECONDS / 60:g}")
        self.exact_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Choose a video to get started.")

        self._build_widgets()
        self._poll_messages()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ #
    # Layout
    # ------------------------------------------------------------------ #

    def _build_widgets(self) -> None:
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Video").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", padx=8)
        self.browse_input_btn = ttk.Button(frame, text="Choose…", command=self._choose_input)
        self.browse_input_btn.grid(row=0, column=2)

        ttk.Label(frame, text="Segment length").grid(row=1, column=0, sticky="w", pady=4)
        spin_row = ttk.Frame(frame)
        spin_row.grid(row=1, column=1, sticky="w", padx=8)
        self.minutes_spin = ttk.Spinbox(
            spin_row, from_=0.1, to=600, increment=0.5, width=8, textvariable=self.minutes_var
        )
        self.minutes_spin.grid(row=0, column=0)
        ttk.Label(spin_row, text="minutes").grid(row=0, column=1, padx=(6, 0))
        # Off by default and labelled with its cost: the lossless split is the
        # point of VidSnap, and this is the one control that gives it up.
        self.exact_check = ttk.Checkbutton(
            spin_row,
            text="Exact cuts (re-encodes — slower, slight quality loss)",
            variable=self.exact_var,
        )
        self.exact_check.grid(row=0, column=2, padx=(18, 0))

        ttk.Label(frame, text="Output folder").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.output_var).grid(row=2, column=1, sticky="ew", padx=8)
        self.browse_output_btn = ttk.Button(frame, text="Choose…", command=self._choose_output)
        self.browse_output_btn.grid(row=2, column=2)

        self.progress = ttk.Progressbar(frame, mode="determinate", maximum=100.0)
        self.progress.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(14, 4))

        ttk.Label(frame, textvariable=self.status_var, wraplength=520, justify="left").grid(
            row=4, column=0, columnspan=3, sticky="w"
        )

        buttons = ttk.Frame(frame)
        buttons.grid(row=5, column=0, columnspan=3, sticky="e", pady=(14, 0))
        self.open_btn = ttk.Button(
            buttons, text="Open folder", command=self._open_result, state="disabled"
        )
        self.open_btn.grid(row=0, column=0, padx=(0, 8))
        self.cancel_btn = ttk.Button(buttons, text="Cancel", command=self._cancel, state="disabled")
        self.cancel_btn.grid(row=0, column=1, padx=(0, 8))
        self.start_btn = ttk.Button(buttons, text="Split", command=self._start)
        self.start_btn.grid(row=0, column=2)

    # ------------------------------------------------------------------ #
    # File pickers
    # ------------------------------------------------------------------ #

    def _choose_input(self) -> None:
        chosen = filedialog.askopenfilename(title="Choose a video", filetypes=_VIDEO_FILETYPES)
        if not chosen:
            return
        path = Path(chosen)
        self.input_var.set(str(path))
        # Default the output folder alongside the input, as the CLI does.
        self.output_var.set(str(splitter.default_output_dir(path)))
        self._describe_source(path)

    def _choose_output(self) -> None:
        chosen = filedialog.askdirectory(title="Choose an output folder")
        if chosen:
            self.output_var.set(str(Path(chosen)))

    def _describe_source(self, path: Path) -> None:
        """Probe the chosen file and show a summary plus any advisories."""
        try:
            info = probe.probe(path)
        except (probe.ProbeError, ffmpeg.BinaryNotFoundError) as exc:
            self.status_var.set(str(exc))
            return

        lines = [
            f"{path.name} — {format_duration(info.duration_seconds)}, "
            f"{info.resolution} {info.video_codec}"
        ]
        segment_seconds = self._segment_seconds_or_default()
        if info.is_shorter_than(segment_seconds):
            lines.append("Shorter than one segment — the result will be a single lossless copy.")
        lines.extend(w for w in self._destination_warnings(path) if w)
        subtitle_warning = info.dropped_subtitle_warning()
        if subtitle_warning:
            lines.append(subtitle_warning)
        self.status_var.set("\n".join(lines))

    def _destination_warnings(self, input_path: Path) -> list[str]:
        """Advisories about where the segments will land (sync folder, other drive)."""
        raw_out = self.output_var.get().strip()
        output_dir = Path(raw_out) if raw_out else splitter.default_output_dir(input_path)
        return [
            w
            for w in (
                paths.cloud_sync_warning(output_dir),
                paths.different_drive_warning(input_path, output_dir),
            )
            if w
        ]

    def _segment_seconds_or_default(self) -> int:
        """The spinbox value in seconds, falling back to the default if unparseable.

        Used only for advisory text, where a half-typed number should not raise or
        pop a dialog — validation proper happens in :meth:`_read_minutes`.
        """
        try:
            minutes = float(self.minutes_var.get().strip())
        except ValueError:
            return splitter.DEFAULT_SEGMENT_SECONDS
        return max(1, round(minutes * 60)) if minutes > 0 else splitter.DEFAULT_SEGMENT_SECONDS

    # ------------------------------------------------------------------ #
    # Running the split
    # ------------------------------------------------------------------ #

    def _read_minutes(self) -> float | None:
        """Parse the spinbox, reporting a dialog and returning None if invalid."""
        raw = self.minutes_var.get().strip()
        try:
            minutes = float(raw)
        except ValueError:
            messagebox.showerror("VidSnap", f"{raw!r} is not a number of minutes.")
            return None
        if minutes <= 0:
            messagebox.showerror("VidSnap", "Segment length must be greater than 0.")
            return None
        return minutes

    def _start(self) -> None:
        if self._worker is not None and self._worker.is_alive():
            return

        raw_input = self.input_var.get().strip()
        if not raw_input:
            messagebox.showerror("VidSnap", "Choose a video first.")
            return
        input_path = Path(raw_input)
        if not input_path.is_file():
            messagebox.showerror("VidSnap", f"No such file:\n{input_path}")
            return

        minutes = self._read_minutes()
        if minutes is None:
            return
        segment_seconds = max(1, round(minutes * 60))

        raw_out = self.output_var.get().strip()
        output_dir = Path(raw_out) if raw_out else None

        exact = bool(self.exact_var.get())

        self._cancel_event = threading.Event()
        self._set_running(True)
        self.progress["value"] = 0.0
        self.status_var.set(
            "Re-encoding for exact cuts — this takes much longer than a lossless split…"
            if exact
            else "Splitting…"
        )
        self._result_dir = None

        self._worker = threading.Thread(
            target=self._run_split,
            args=(input_path, output_dir, segment_seconds, self._cancel_event, exact),
            daemon=True,
        )
        self._worker.start()

    def _run_split(
        self,
        input_path: Path,
        output_dir: Path | None,
        segment_seconds: int,
        cancel_event: threading.Event,
        exact: bool,
    ) -> None:
        """Worker thread. Touches no widgets — only posts to the queue."""
        try:
            result = splitter.split(
                input_path,
                output_dir,
                segment_seconds,
                on_progress=lambda f: self._messages.put(_Progress(f)),
                cancel_event=cancel_event,
                exact=exact,
            )
        except splitter.SplitCancelled as exc:
            self._messages.put(_Finished(tuple(exc.segments), cancelled=True))
        except (
            splitter.SplitError,
            probe.ProbeError,
            ffmpeg.BinaryNotFoundError,
            OSError,
        ) as exc:
            _logger.exception("split failed")
            self._messages.put(_Failed(str(exc)))
        else:
            self._messages.put(
                _Finished(tuple(result.segments), cancelled=False, note=result.length_report())
            )

    def _cancel(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
            self.cancel_btn.state(["disabled"])
            self.status_var.set("Cancelling…")

    # ------------------------------------------------------------------ #
    # UI-thread message pump
    # ------------------------------------------------------------------ #

    def _poll_messages(self) -> None:
        """Drain the worker queue on the UI thread; reschedule itself."""
        latest_progress: float | None = None
        try:
            while True:
                message = self._messages.get_nowait()
                if isinstance(message, _Progress):
                    # Coalesce: only the newest value matters for a progress bar.
                    latest_progress = message.fraction
                elif isinstance(message, _Finished):
                    self._on_finished(
                        message.segments, cancelled=message.cancelled, note=message.note
                    )
                else:
                    self._on_error(message.message)
        except queue.Empty:
            pass

        if latest_progress is not None:
            self.progress["value"] = latest_progress * 100.0

        self.root.after(_POLL_INTERVAL_MS, self._poll_messages)

    def _on_finished(
        self, segments: Sequence[Path], *, cancelled: bool, note: str | None = None
    ) -> None:
        """Settle the UI after the worker ends, however it ended."""
        self._set_running(False)
        # A cancelled run is not "complete", so the bar goes back to empty.
        self.progress["value"] = 0.0 if cancelled else 100.0

        if segments:
            self._result_dir = segments[0].parent
            self.open_btn.state(["!disabled"])

        if cancelled:
            self.status_var.set(
                f"Cancelled — {len(segments)} complete segment(s) kept; "
                "the partial one was removed."
                if segments
                else "Cancelled — no complete segments were kept."
            )
        elif segments:
            done = f"Done — {len(segments)} file(s) created in {self._result_dir}"
            self.status_var.set(f"{done}\n{note}" if note else done)
        else:
            self.status_var.set("Done, but no segments were produced.")

    def _on_error(self, message: str) -> None:
        self._set_running(False)
        self.progress["value"] = 0.0
        self.status_var.set(f"Error: {message}")
        messagebox.showerror("VidSnap", message)

    def _set_running(self, running: bool) -> None:
        """Enable exactly the controls that make sense for the current state."""
        busy = ["disabled"] if running else ["!disabled"]
        idle = ["!disabled"] if running else ["disabled"]
        for widget in (
            self.start_btn,
            self.browse_input_btn,
            self.browse_output_btn,
            self.minutes_spin,
            self.exact_check,
        ):
            widget.state(busy)
        self.cancel_btn.state(idle)
        if running:
            self.open_btn.state(["disabled"])

    def _open_result(self) -> None:
        if self._result_dir is not None:
            open_folder(self._result_dir)

    def _on_close(self) -> None:
        """Cancel a running split before tearing the window down."""
        if self._worker is not None and self._worker.is_alive():
            if self._cancel_event is not None:
                self._cancel_event.set()
            # Give FFmpeg a moment to die so we do not orphan the process.
            self._worker.join(timeout=10)
        self.root.destroy()


def main() -> int:
    """Launch the GUI."""
    setup_logging()
    _enable_dpi_awareness()  # must precede tk.Tk()
    root = tk.Tk()
    _apply_tk_scaling(root)
    VidSnapApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
