"""
test_audio_mix.py
Unit tests for audio_mix.mix_to_16k_mono using synthetic sine waves.
"""
import os
import sys
import tempfile
import math

import numpy as np
import pytest
import soundfile as sf

# Ensure voice-journal directory is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from audio_mix import mix_to_16k_mono


def _write_sine_flac(path: str, freq: float, duration: float, sr: int, channels: int) -> None:
    """Write a sine wave FLAC file."""
    n = int(sr * duration)
    t = np.arange(n) / sr
    signal = (0.3 * np.sin(2 * math.pi * freq * t)).astype(np.float32)
    if channels == 2:
        signal = np.stack([signal, signal], axis=1)
    sf.write(path, signal, sr, format="FLAC")


class TestMixTo16kMono:
    def test_single_mic_shape(self, tmp_path):
        """Mic-only: output should be 1D float32 array at 16 kHz."""
        mic_path = str(tmp_path / "mic.flac")
        _write_sine_flac(mic_path, freq=440.0, duration=1.0, sr=16000, channels=1)

        result = mix_to_16k_mono(mic_path, sys_path=None)

        assert result.ndim == 1
        assert result.dtype == np.float32
        # Allow +-5% tolerance for length
        assert abs(len(result) - 16000) < 800

    def test_resample_from_44100(self, tmp_path):
        """Input at 44100 Hz should be resampled to 16000 Hz."""
        mic_path = str(tmp_path / "mic44k.flac")
        _write_sine_flac(mic_path, freq=440.0, duration=2.0, sr=44100, channels=1)

        result = mix_to_16k_mono(mic_path, sys_path=None)

        assert result.ndim == 1
        assert result.dtype == np.float32
        expected_len = 32000  # 2 sec * 16000
        assert abs(len(result) - expected_len) < 1600

    def test_stereo_to_mono(self, tmp_path):
        """Stereo input should be averaged to mono."""
        mic_path = str(tmp_path / "mic_stereo.flac")
        _write_sine_flac(mic_path, freq=440.0, duration=1.0, sr=16000, channels=2)

        result = mix_to_16k_mono(mic_path, sys_path=None)

        assert result.ndim == 1

    def test_mix_two_tracks_shape(self, tmp_path):
        """Mixing mic+sys returns correct 1D float32 shape."""
        mic_path = str(tmp_path / "mic.flac")
        sys_path = str(tmp_path / "sys.flac")
        _write_sine_flac(mic_path, freq=440.0, duration=1.0, sr=16000, channels=1)
        _write_sine_flac(sys_path, freq=880.0, duration=1.0, sr=16000, channels=1)

        result = mix_to_16k_mono(mic_path, sys_path)

        assert result.ndim == 1
        assert result.dtype == np.float32

    def test_no_clipping_when_loud(self, tmp_path):
        """Mixed result should not exceed [-1.0, 1.0]."""
        mic_path = str(tmp_path / "mic.flac")
        sys_path = str(tmp_path / "sys.flac")
        # Both at high amplitude -> would clip without normalization
        sr = 16000
        n = sr  # 1 second
        t = np.arange(n) / sr
        loud = (0.9 * np.sin(2 * math.pi * 440 * t)).astype(np.float32)
        sf.write(mic_path, loud, sr, format="FLAC")
        sf.write(sys_path, loud, sr, format="FLAC")

        result = mix_to_16k_mono(mic_path, sys_path)

        assert np.max(np.abs(result)) <= 1.0 + 1e-6, "Output exceeds ±1.0 (clipping)"

    def test_length_matching_zero_pad(self, tmp_path):
        """Shorter sys track is zero-padded; output length = max(mic, sys)."""
        mic_path = str(tmp_path / "mic.flac")
        sys_path = str(tmp_path / "sys.flac")
        _write_sine_flac(mic_path, freq=440.0, duration=2.0, sr=16000, channels=1)
        _write_sine_flac(sys_path, freq=880.0, duration=1.0, sr=16000, channels=1)

        result = mix_to_16k_mono(mic_path, sys_path)

        # Should be ~2 seconds long (padded to mic length)
        assert abs(len(result) - 32000) < 800
