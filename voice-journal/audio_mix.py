"""
audio_mix.py
Pure function: read FLAC files -> resample to 16 kHz mono -> mix two tracks.
"""
from __future__ import annotations

import numpy as np
import soundfile as sf
import soxr


def mix_to_16k_mono(mic_path: str, sys_path: str | None = None) -> np.ndarray:
    """
    Load mic (and optionally system) FLAC, resample to 16 kHz mono, mix, return float32 array.

    Parameters
    ----------
    mic_path : str
        Path to mic FLAC file.
    sys_path : str | None
        Path to system audio FLAC file. If None, returns mic-only.

    Returns
    -------
    np.ndarray
        float32 array, shape (N,), sample rate = 16000 Hz.
    """
    mic_audio = _load_flac_as_16k_mono(mic_path)

    if sys_path is None:
        return mic_audio

    sys_audio = _load_flac_as_16k_mono(sys_path)

    # Zero-pad the shorter one to match lengths
    len_mic = len(mic_audio)
    len_sys = len(sys_audio)
    if len_mic > len_sys:
        sys_audio = np.concatenate([sys_audio, np.zeros(len_mic - len_sys, dtype=np.float32)])
    elif len_sys > len_mic:
        mic_audio = np.concatenate([mic_audio, np.zeros(len_sys - len_mic, dtype=np.float32)])

    mixed = mic_audio + sys_audio

    # Normalize if peak > 1.0 to avoid clipping
    peak = np.max(np.abs(mixed))
    if peak > 1.0:
        mixed = mixed / peak

    return mixed


def _load_flac_as_16k_mono(path: str) -> np.ndarray:
    """Load a FLAC file, convert to float32 mono, resample to 16 kHz."""
    data, sr = sf.read(path, dtype="float32", always_2d=True)

    # Convert to mono by averaging channels
    if data.shape[1] > 1:
        data = data.mean(axis=1)
    else:
        data = data[:, 0]

    # Resample to 16 kHz if needed
    if sr != 16000:
        data = soxr.resample(data, sr, 16000, quality="HQ")

    return data.astype(np.float32)
