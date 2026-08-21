"""
recorder.py
AudioRecorder: mic + WASAPI loopback recording, FLAC writing, hourly rotation.
"""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import sounddevice as sd
import soundfile as sf

logger = logging.getLogger(__name__)

# Path to pause flag file (relative to service.py's working directory or CWD)
PAUSE_FLAG = Path("PAUSE.flag")


def _next_segment_start(align_to_clock_hour: bool, segment_seconds: int) -> datetime:
    """Calculate the datetime of the next segment boundary."""
    now = datetime.now()
    if align_to_clock_hour:
        # Align to next clock hour boundary
        next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        return next_hour
    else:
        return now + timedelta(seconds=segment_seconds)


def _seconds_until(target: datetime) -> float:
    """Seconds remaining until target datetime (floor to 0)."""
    delta = (target - datetime.now()).total_seconds()
    return max(0.0, delta)


class _FlacWriter:
    """Background thread that drains a queue and writes to a FLAC file."""

    def __init__(self, path: str, samplerate: int, channels: int) -> None:
        self.path = path
        self._q: queue.Queue = queue.Queue()
        self._sf: Optional[sf.SoundFile] = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._samplerate = samplerate
        self._channels = channels
        self._stop_event = threading.Event()

    def start(self) -> None:
        self._sf = sf.SoundFile(
            self.path, mode="w",
            samplerate=self._samplerate,
            channels=self._channels,
            format="FLAC"
        )
        self._thread.start()

    def write(self, frames: "np.ndarray") -> None:
        self._q.put(frames.copy())

    def close(self) -> None:
        """Signal stop and wait for the writer thread to flush and close."""
        self._stop_event.set()
        self._thread.join(timeout=10)
        if self._sf and not self._sf.closed:
            self._sf.close()

    def _run(self) -> None:
        try:
            while not self._stop_event.is_set() or not self._q.empty():
                try:
                    frames = self._q.get(timeout=0.1)
                    if self._sf:
                        self._sf.write(frames)
                except queue.Empty:
                    continue
        except Exception as exc:
            logger.error("FlacWriter error for %s: %s", self.path, exc)
        finally:
            if self._sf and not self._sf.closed:
                self._sf.close()


class AudioRecorder:
    """
    Records mic and (optionally) system audio to FLAC files.
    Rotates every segment_seconds (aligned to clock hour if configured).
    Calls on_segment(start_ts, mic_path, sys_path) when a segment completes.
    Respects PAUSE.flag for pause/resume.
    """

    def __init__(
        self,
        temp_dir: str,
        segment_seconds: int = 3600,
        align_to_clock_hour: bool = True,
        mic_device: Optional[int] = None,
        loopback_device: Optional[int] = None,
        capture_system_audio: bool = True,
        on_segment: Optional[Callable] = None,
    ) -> None:
        self._temp_dir = Path(temp_dir)
        self._segment_seconds = segment_seconds
        self._align_to_clock_hour = align_to_clock_hour
        self._mic_device = mic_device
        self._loopback_device = loopback_device
        self._capture_system_audio = capture_system_audio
        self._on_segment = on_segment

        self._running = False
        self._main_thread: Optional[threading.Thread] = None
        self._mic_stream: Optional[sd.InputStream] = None
        self._sys_stream: Optional[sd.InputStream] = None
        self._mic_writer: Optional[_FlacWriter] = None
        self._sys_writer: Optional[_FlacWriter] = None

        self._segment_start_ts: Optional[datetime] = None
        self._mic_path: Optional[str] = None
        self._sys_path: Optional[str] = None

        self._paused = False

    def start(self) -> None:
        self._running = True
        self._main_thread = threading.Thread(target=self._run, daemon=True, name="recorder-main")
        self._main_thread.start()

    def stop(self) -> None:
        self._running = False
        if self._main_thread:
            self._main_thread.join(timeout=15)

    def _get_default_output_device_index(self) -> Optional[int]:
        """Find the default output device index for WASAPI loopback."""
        try:
            default_out = sd.default.device[1]  # output device
            if default_out >= 0:
                return default_out
            # Fallback: search for first output device
            devices = sd.query_devices()
            for i, d in enumerate(devices):
                if d["max_output_channels"] > 0:
                    return i
        except Exception as exc:
            logger.warning("Could not find default output device: %s", exc)
        return None

    def _open_streams(self, start_ts: datetime) -> bool:
        """Open mic (and optionally loopback) streams and writers. Returns True on success."""
        ts_str = start_ts.strftime("%Y%m%d_%H%M%S")
        self._segment_start_ts = start_ts
        self._mic_path = str(self._temp_dir / f"{ts_str}_mic.flac")
        self._sys_path = None

        # --- Mic stream ---
        try:
            mic_info = sd.query_devices(self._mic_device, "input")
            mic_sr = int(mic_info["default_samplerate"])
            mic_ch = min(int(mic_info["max_input_channels"]), 2)

            self._mic_writer = _FlacWriter(self._mic_path, mic_sr, mic_ch)
            self._mic_writer.start()

            def mic_callback(indata, frames, time_info, status):
                if status:
                    logger.debug("Mic status: %s", status)
                if self._mic_writer:
                    self._mic_writer.write(indata)

            self._mic_stream = sd.InputStream(
                device=self._mic_device,
                samplerate=mic_sr,
                channels=mic_ch,
                callback=mic_callback,
            )
            self._mic_stream.start()
            logger.info("Mic stream started: %s", self._mic_path)
        except Exception as exc:
            logger.error("Failed to open mic stream: %s", exc)
            return False

        # --- System audio loopback ---
        if self._capture_system_audio:
            loopback_idx = self._loopback_device or self._get_default_output_device_index()
            if loopback_idx is not None:
                try:
                    out_info = sd.query_devices(loopback_idx)
                    sys_sr = int(out_info["default_samplerate"])
                    sys_ch = max(1, int(out_info.get("max_output_channels", 2)))
                    sys_ch = min(sys_ch, 2)

                    ts_str2 = start_ts.strftime("%Y%m%d_%H%M%S")
                    self._sys_path = str(self._temp_dir / f"{ts_str2}_sys.flac")

                    self._sys_writer = _FlacWriter(self._sys_path, sys_sr, sys_ch)
                    self._sys_writer.start()

                    def sys_callback(indata, frames, time_info, status):
                        if status:
                            logger.debug("Sys status: %s", status)
                        if self._sys_writer:
                            self._sys_writer.write(indata)

                    self._sys_stream = sd.InputStream(
                        device=loopback_idx,
                        samplerate=sys_sr,
                        channels=sys_ch,
                        callback=sys_callback,
                        extra_settings=sd.WasapiSettings(loopback=True),
                    )
                    self._sys_stream.start()
                    logger.info("System audio (loopback) stream started: %s", self._sys_path)
                except Exception as exc:
                    logger.warning(
                        "Loopback stream failed (will record mic only): %s", exc
                    )
                    self._sys_path = None
                    self._sys_writer = None
                    self._sys_stream = None
            else:
                logger.warning("No output device found; system audio capture disabled.")

        return True

    def _close_streams(self) -> tuple[Optional[str], Optional[str]]:
        """Close all streams and writers. Returns (mic_path, sys_path)."""
        mic_path = self._mic_path
        sys_path = self._sys_path

        for stream in [self._mic_stream, self._sys_stream]:
            if stream:
                try:
                    stream.stop()
                    stream.close()
                except Exception as exc:
                    logger.warning("Error closing stream: %s", exc)

        for writer in [self._mic_writer, self._sys_writer]:
            if writer:
                try:
                    writer.close()
                except Exception as exc:
                    logger.warning("Error closing writer: %s", exc)

        self._mic_stream = None
        self._sys_stream = None
        self._mic_writer = None
        self._sys_writer = None
        self._mic_path = None
        self._sys_path = None

        return mic_path, sys_path

    def _run(self) -> None:
        retry_interval = 30  # seconds between mic-open retries
        segment_start = datetime.now()

        # Calculate time to next segment boundary
        next_rotate = _next_segment_start(self._align_to_clock_hour, self._segment_seconds)

        opened = False
        while self._running:
            # --- PAUSE.flag check ---
            if PAUSE_FLAG.exists():
                if not self._paused:
                    logger.info("PAUSE.flag detected — stopping streams.")
                    if opened:
                        self._close_streams()
                        opened = False
                    self._paused = True
                time.sleep(2)
                continue
            else:
                if self._paused:
                    logger.info("PAUSE.flag removed — resuming recording.")
                    self._paused = False
                    segment_start = datetime.now()
                    next_rotate = _next_segment_start(
                        self._align_to_clock_hour, self._segment_seconds
                    )

            # --- Open streams if not already open ---
            if not opened:
                segment_start = datetime.now()
                success = self._open_streams(segment_start)
                if not success:
                    logger.error(
                        "Failed to open mic; retrying in %d s", retry_interval
                    )
                    time.sleep(retry_interval)
                    continue
                opened = True

            # --- Check rotation ---
            if datetime.now() >= next_rotate:
                mic_path, sys_path = self._close_streams()
                opened = False
                seg_start_ts = self._segment_start_ts or segment_start

                if self._on_segment and mic_path:
                    try:
                        self._on_segment(seg_start_ts, mic_path, sys_path)
                    except Exception as exc:
                        logger.error("on_segment callback error: %s", exc)

                # Set next rotation boundary
                next_rotate = next_rotate + timedelta(seconds=self._segment_seconds)
                segment_start = datetime.now()
                opened = self._open_streams(segment_start)
                if not opened:
                    logger.error("Failed to re-open streams after rotation; retrying in %d s", retry_interval)
                    time.sleep(retry_interval)

            time.sleep(0.5)

        # --- Shutdown: flush current segment ---
        if opened:
            mic_path, sys_path = self._close_streams()
            seg_start_ts = self._segment_start_ts or segment_start
            if self._on_segment and mic_path:
                try:
                    self._on_segment(seg_start_ts, mic_path, sys_path)
                except Exception as exc:
                    logger.error("on_segment callback (shutdown) error: %s", exc)

        logger.info("AudioRecorder stopped.")
