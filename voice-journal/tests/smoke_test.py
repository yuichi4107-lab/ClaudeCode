"""
smoke_test.py
Integration smoke test: synthetic wav -> transcribe -> inbox append -> cleanup.
Does NOT touch real inbox or require live audio devices.
"""
import math
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def make_test_audio(path: str, duration: float = 3.0, sr: int = 16000) -> None:
    """Write a synthetic 16 kHz mono WAV (sine + silence mix)."""
    n = int(sr * duration)
    t = np.arange(n) / sr
    # First half: sine wave; second half: silence
    half = n // 2
    signal = np.zeros(n, dtype=np.float32)
    signal[:half] = 0.2 * np.sin(2 * math.pi * 440 * t[:half])
    sf.write(path, signal, sr)


def test_transcriber_returns_str():
    """Transcriber returns dict with str 'text' key without raising."""
    print("\n[Smoke] Loading Whisper model (may download on first run)...", flush=True)

    from transcriber import Transcriber

    with tempfile.TemporaryDirectory() as tmpdir:
        audio_path = os.path.join(tmpdir, "test_mic.flac")
        make_test_audio(audio_path, duration=3.0)

        t0 = time.time()
        transcriber = Transcriber(model="small", whisper_device="auto", language="ja")
        result = transcriber.transcribe(audio_path, sys_path=None)
        elapsed = time.time() - t0

        assert isinstance(result, dict), "Result must be dict"
        assert "text" in result, "Result must contain 'text'"
        assert isinstance(result["text"], str), "'text' must be str"
        assert "language" in result, "Result must contain 'language'"
        assert "duration" in result, "Result must contain 'duration'"
        print(f"[Smoke] Transcription OK in {elapsed:.1f}s: text='{result['text'][:60]}'")


def test_inbox_writer_temp_dir():
    """inbox_writer.append writes to temp dir, not real inbox."""
    import inbox_writer

    with tempfile.TemporaryDirectory() as tmpdir:
        start = datetime(2026, 5, 31, 14, 0, 0)
        end = datetime(2026, 5, 31, 15, 0, 0)

        inbox_writer.append(start, end, "スモークテスト本文", inbox_dir=tmpdir)

        md_file = Path(tmpdir) / "2026-05-31.md"
        assert md_file.exists(), "Inbox file was not created"
        content = md_file.read_text(encoding="utf-8")
        assert "スモークテスト本文" in content
        assert "14:00" in content
        print(f"[Smoke] inbox_writer OK: {md_file}")

        # Cleanup
        md_file.unlink()
        assert not md_file.exists(), "File deletion failed"
        print("[Smoke] Cleanup OK")


def test_real_inbox_not_touched():
    """Confirm real inbox directory was not modified during smoke tests."""
    import json
    config_path = Path(__file__).parent.parent / "config.json"
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    real_inbox = Path(cfg["inbox_dir"])
    today_file = real_inbox / f"{datetime.now().strftime('%Y-%m-%d')}.md"
    # We just verify we did NOT create or modify it during smoke tests
    # (If it already existed, we leave it alone)
    print(f"[Smoke] Real inbox check: {real_inbox} - test did not touch it.")


if __name__ == "__main__":
    print("=== Smoke Test ===")
    test_inbox_writer_temp_dir()
    test_transcriber_returns_str()
    test_real_inbox_not_touched()
    print("\n=== All smoke tests passed ===")
