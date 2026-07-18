"""Tests for the Tkinter GUI (:mod:`vidsnap.gui`).

Widget tests need a real Tk display, so they skip automatically where one is not
available (a headless CI runner, for instance). The split itself is not exercised
here — that is covered in ``test_splitter.py``; these tests cover the wiring the
GUI adds on top: state transitions, input validation, and the worker→UI queue.
"""

from __future__ import annotations

import queue
import tkinter as tk
from collections.abc import Iterator
from pathlib import Path

import pytest

from vidsnap import gui


def _tk_available() -> bool:
    try:
        root = tk.Tk()
    except (tk.TclError, RuntimeError):
        return False
    root.destroy()
    return True


requires_tk = pytest.mark.skipif(not _tk_available(), reason="no usable Tk/Tcl install")


@pytest.fixture(scope="session")
def tk_root() -> Iterator[tk.Tk]:
    """One Tk root for the whole session.

    Deliberately session-scoped: spinning up a root per test is slow, and on
    installs where the Tcl library is flaky to load it multiplies the chance of a
    spurious TclError. Each test still gets an isolated window (see ``app``).
    """
    try:
        root = tk.Tk()
    except (tk.TclError, RuntimeError) as exc:  # pragma: no cover - env dependent
        pytest.skip(f"no usable Tk/Tcl install: {exc}")
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture
def app(tk_root: tk.Tk) -> Iterator[gui.VidSnapApp]:
    """A fresh app in its own Toplevel, so tests cannot leak state into each other."""
    window = tk.Toplevel(tk_root)
    window.withdraw()  # keep the window off-screen during tests
    instance = gui.VidSnapApp(window)
    yield instance
    window.destroy()


# --------------------------------------------------------------------------- #
# No display needed
# --------------------------------------------------------------------------- #


def test_dpi_awareness_is_safe_to_call() -> None:
    # No-op off Windows, and must never raise on any platform.
    gui._enable_dpi_awareness()


def test_open_folder_never_raises_on_bad_path(tmp_path: Path) -> None:
    # Best-effort by contract: a missing folder must not propagate an error.
    gui.open_folder(tmp_path / "definitely_missing")


# --------------------------------------------------------------------------- #
# Widget behaviour (needs Tk)
# --------------------------------------------------------------------------- #


@requires_tk
def test_defaults_match_the_cli(app: gui.VidSnapApp) -> None:
    # Default segment length is the same 2 minutes the CLI uses.
    assert float(app.minutes_var.get()) == gui.splitter.DEFAULT_SEGMENT_SECONDS / 60


@requires_tk
def test_exact_cuts_are_off_by_default(app: gui.VidSnapApp) -> None:
    """Lossless is the product; re-encoding must be a deliberate tick."""
    assert app.exact_var.get() is False


@requires_tk
def test_exact_checkbox_is_disabled_while_running(app: gui.VidSnapApp) -> None:
    app._set_running(True)
    assert "disabled" in app.exact_check.state()
    app._set_running(False)
    assert "disabled" not in app.exact_check.state()


@requires_tk
def test_destination_warnings_flag_a_synced_output_folder(
    app: gui.VidSnapApp, tmp_path: Path
) -> None:
    app.output_var.set(str(tmp_path / "OneDrive" / "clips"))
    warnings = app._destination_warnings(tmp_path / "clip.mp4")
    assert any("sync" in w for w in warnings)


@requires_tk
def test_destination_warnings_silent_for_a_plain_local_folder(
    app: gui.VidSnapApp, tmp_path: Path
) -> None:
    app.output_var.set(str(tmp_path / "clips"))
    assert app._destination_warnings(tmp_path / "clip.mp4") == []


@requires_tk
@pytest.mark.parametrize("raw", ["", "abc", "0"])
def test_segment_seconds_falls_back_to_default_for_unusable_input(
    app: gui.VidSnapApp, raw: str
) -> None:
    """Advisory text is computed while the user is mid-type; it must not raise."""
    app.minutes_var.set(raw)
    assert app._segment_seconds_or_default() == gui.splitter.DEFAULT_SEGMENT_SECONDS


@requires_tk
def test_cancel_disabled_until_running(app: gui.VidSnapApp) -> None:
    assert "disabled" in app.cancel_btn.state()
    assert "disabled" not in app.start_btn.state()


@requires_tk
def test_set_running_swaps_control_states(app: gui.VidSnapApp) -> None:
    app._set_running(True)
    assert "disabled" in app.start_btn.state()
    assert "disabled" in app.browse_input_btn.state()
    assert "disabled" in app.minutes_spin.state()
    assert "disabled" not in app.cancel_btn.state()

    app._set_running(False)
    assert "disabled" not in app.start_btn.state()
    assert "disabled" in app.cancel_btn.state()


@requires_tk
@pytest.mark.parametrize("bad", ["", "abc", "0", "-3"])
def test_invalid_minutes_rejected(
    app: gui.VidSnapApp, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    errors: list[str] = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda _t, m: errors.append(m))
    app.minutes_var.set(bad)
    assert app._read_minutes() is None
    assert errors  # the user was told why


@requires_tk
def test_valid_minutes_parsed(app: gui.VidSnapApp) -> None:
    app.minutes_var.set("1.5")
    assert app._read_minutes() == pytest.approx(1.5)


@requires_tk
def test_start_without_input_shows_error_and_does_not_run(
    app: gui.VidSnapApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    errors: list[str] = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda _t, m: errors.append(m))
    app.input_var.set("")
    app._start()
    assert errors
    assert app._worker is None  # no thread was spawned


@requires_tk
def test_start_with_missing_file_shows_error(
    app: gui.VidSnapApp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    errors: list[str] = []
    monkeypatch.setattr(gui.messagebox, "showerror", lambda _t, m: errors.append(m))
    app.input_var.set(str(tmp_path / "nope.mp4"))
    app._start()
    assert errors
    assert app._worker is None


@requires_tk
def test_done_enables_open_folder(app: gui.VidSnapApp, tmp_path: Path) -> None:
    seg = tmp_path / "clip_part_001.mp4"
    seg.write_bytes(b"x")

    app._on_finished([seg], cancelled=False)

    assert app._result_dir == tmp_path
    assert "disabled" not in app.open_btn.state()
    assert "1 file(s)" in app.status_var.get()
    assert app.progress["value"] == pytest.approx(100.0)


@requires_tk
def test_cancelled_reports_kept_segments(app: gui.VidSnapApp, tmp_path: Path) -> None:
    seg = tmp_path / "clip_part_001.mp4"
    seg.write_bytes(b"x")

    app._on_finished([seg], cancelled=True)

    status = app.status_var.get()
    assert "Cancelled" in status
    assert "partial" in status
    assert "disabled" not in app.open_btn.state()
    # A cancelled run must not look complete.
    assert app.progress["value"] == pytest.approx(0.0)


@requires_tk
def test_cancelled_with_nothing_kept(app: gui.VidSnapApp) -> None:
    app._on_finished([], cancelled=True)
    assert "no complete segments" in app.status_var.get()
    assert "disabled" in app.open_btn.state()


@requires_tk
def test_finished_message_from_queue_settles_ui(app: gui.VidSnapApp, tmp_path: Path) -> None:
    """A _Finished posted by the worker is applied by the UI-thread pump."""
    seg = tmp_path / "clip_part_001.mp4"
    seg.write_bytes(b"x")
    app._set_running(True)

    app._messages.put(gui._Finished((seg,), cancelled=False))
    app._poll_messages()

    assert "disabled" not in app.start_btn.state()
    assert "1 file(s)" in app.status_var.get()


@requires_tk
def test_finished_note_is_shown_alongside_the_done_line(
    app: gui.VidSnapApp, tmp_path: Path
) -> None:
    """Keyframe drift reported by the engine has to reach the user."""
    seg = tmp_path / "clip_part_001.mp4"
    seg.write_bytes(b"x")

    app._messages.put(gui._Finished((seg,), cancelled=False, note="Segments run up to 2:14"))
    app._poll_messages()

    status = app.status_var.get()
    assert "1 file(s)" in status
    assert "2:14" in status


@requires_tk
def test_failed_message_from_queue_reports_error(
    app: gui.VidSnapApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gui.messagebox, "showerror", lambda _t, _m: None)
    app._set_running(True)

    app._messages.put(gui._Failed("disk full"))
    app._poll_messages()

    assert "disk full" in app.status_var.get()
    assert "disabled" not in app.start_btn.state()


@requires_tk
def test_error_message_resets_state(app: gui.VidSnapApp, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gui.messagebox, "showerror", lambda _t, _m: None)
    app._set_running(True)
    app._on_error("ffmpeg exploded")
    assert "ffmpeg exploded" in app.status_var.get()
    assert "disabled" not in app.start_btn.state()
    assert "disabled" in app.cancel_btn.state()


@requires_tk
def test_poll_coalesces_progress_to_latest(app: gui.VidSnapApp) -> None:
    for fraction in (0.1, 0.4, 0.9):
        app._messages.put(gui._Progress(fraction))

    app._poll_messages()

    # Only the newest value is applied, and the queue is fully drained.
    assert app.progress["value"] == pytest.approx(90.0)
    with pytest.raises(queue.Empty):
        app._messages.get_nowait()
