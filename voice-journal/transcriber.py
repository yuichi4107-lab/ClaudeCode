"""
transcriber.py
Transcriber: load faster-whisper model, transcribe audio segments.
"""
from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

logger = logging.getLogger(__name__)


def _resolve_device(whisper_device: str) -> tuple[str, str]:
    """
    Resolve whisper_device 'auto' to ('cuda', 'float16') or ('cpu', 'int8').
    Returns (device, compute_type).
    """
    if whisper_device == "auto":
        try:
            import torch
            if torch.cuda.is_available():
                logger.info("CUDA detected — using GPU (float16)")
                return "cuda", "float16"
        except ImportError:
            pass
        logger.info("CUDA not available — using CPU (int8)")
        return "cpu", "int8"
    return whisper_device, "int8"


class Transcriber:
    """
    Wraps faster-whisper WhisperModel.
    Loads the model once; transcribe() accepts audio file paths.
    """

    def __init__(
        self,
        model: str = "small",
        whisper_device: str = "auto",
        compute_type: str = "int8",
        language: str = "ja",
    ) -> None:
        self._language = language
        device, resolved_compute = _resolve_device(whisper_device)
        # compute_type from config takes precedence unless device is 'auto'
        if whisper_device == "auto":
            effective_compute = resolved_compute
        else:
            effective_compute = compute_type

        logger.info(
            "Loading Whisper model '%s' on device='%s' compute_type='%s'",
            model, device, effective_compute,
        )
        from faster_whisper import WhisperModel
        self._model = WhisperModel(model, device=device, compute_type=effective_compute)
        logger.info("Whisper model loaded.")

    def transcribe(
        self, mic_path: str, sys_path: Optional[str] = None
    ) -> dict:
        """
        Mix audio, transcribe with Whisper, return dict with text/language/duration.

        Parameters
        ----------
        mic_path : str
            Path to mic FLAC file.
        sys_path : str | None
            Path to system audio FLAC file, or None.

        Returns
        -------
        dict with keys: text (str), language (str), duration (float seconds)
        """
        from audio_mix import mix_to_16k_mono

        audio = mix_to_16k_mono(mic_path, sys_path)
        duration_sec = len(audio) / 16000.0

        # faster-whisper accepts numpy float32 array directly
        segments, info = self._model.transcribe(
            audio,
            language=self._language,
            vad_filter=True,
        )

        text = "".join(seg.text for seg in segments).strip()

        return {
            "text": text,
            "language": info.language,
            "duration": duration_sec,
        }
