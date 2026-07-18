"""Tests for the shared formatting helpers (:mod:`vidsnap.humanize`)."""

from __future__ import annotations

import pytest

from vidsnap.humanize import format_duration


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0:00"),
        (9, "0:09"),
        (60, "1:00"),
        (125, "2:05"),
        (599, "9:59"),
        (3600, "1:00:00"),
        (3661, "1:01:01"),
        (7 * 60, "7:00"),
    ],
)
def test_format_duration(seconds: float, expected: str) -> None:
    assert format_duration(seconds) == expected


def test_format_duration_rounds_to_nearest_second() -> None:
    assert format_duration(59.6) == "1:00"
    assert format_duration(59.4) == "0:59"
