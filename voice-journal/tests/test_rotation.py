"""
test_rotation.py
Unit tests for segment boundary calculation logic (rotation timing).
Tests the pure-logic parts of recorder.py without opening audio streams.
"""
import os
import sys
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from recorder import _next_segment_start, _seconds_until


class TestNextSegmentStart:
    def test_align_to_clock_hour_returns_next_hour(self, monkeypatch):
        """With align_to_clock_hour=True, next boundary is the next clock hour."""
        fake_now = datetime(2026, 5, 31, 14, 23, 45)

        # Monkeypatch datetime.now in the recorder module
        import recorder as rec_module
        from unittest.mock import patch

        with patch("recorder.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

            result = _next_segment_start(align_to_clock_hour=True, segment_seconds=3600)

        expected = datetime(2026, 5, 31, 15, 0, 0)
        assert result == expected

    def test_align_to_clock_hour_at_exact_boundary(self, monkeypatch):
        """At exact hour boundary, next segment starts at the following hour."""
        fake_now = datetime(2026, 5, 31, 15, 0, 0)

        from unittest.mock import patch
        with patch("recorder.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

            result = _next_segment_start(align_to_clock_hour=True, segment_seconds=3600)

        expected = datetime(2026, 5, 31, 16, 0, 0)
        assert result == expected

    def test_no_align_adds_segment_seconds(self):
        """Without clock alignment, next boundary is now + segment_seconds."""
        from unittest.mock import patch
        fake_now = datetime(2026, 5, 31, 14, 23, 45)

        with patch("recorder.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

            result = _next_segment_start(align_to_clock_hour=False, segment_seconds=60)

        expected = fake_now + timedelta(seconds=60)
        assert result == expected

    def test_short_segment_seconds(self):
        """20-second segment_seconds without alignment gives correct boundary."""
        from unittest.mock import patch
        fake_now = datetime(2026, 5, 31, 10, 0, 5)

        with patch("recorder.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)

            result = _next_segment_start(align_to_clock_hour=False, segment_seconds=20)

        expected = fake_now + timedelta(seconds=20)
        assert result == expected


class TestSecondsUntil:
    def test_future_target(self):
        """Positive seconds for a future target."""
        from unittest.mock import patch
        fake_now = datetime(2026, 5, 31, 14, 30, 0)
        target = datetime(2026, 5, 31, 15, 0, 0)

        with patch("recorder.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            result = _seconds_until(target)

        assert abs(result - 1800.0) < 1.0  # 30 minutes = 1800 sec

    def test_past_target_returns_zero(self):
        """Past target returns 0 (not negative)."""
        from unittest.mock import patch
        fake_now = datetime(2026, 5, 31, 15, 0, 0)
        target = datetime(2026, 5, 31, 14, 0, 0)

        with patch("recorder.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            result = _seconds_until(target)

        assert result == 0.0

    def test_sequence_of_boundaries(self):
        """Simulating multiple rotation steps: each adds segment_seconds."""
        segment_sec = 3600
        base = datetime(2026, 5, 31, 14, 0, 0)
        boundaries = [base + timedelta(seconds=segment_sec * i) for i in range(1, 5)]

        for i, b in enumerate(boundaries):
            expected_hour = 15 + i
            assert b.hour == expected_hour % 24
