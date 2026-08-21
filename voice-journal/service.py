"""
service.py
Entry point for voice-journal service.
Orchestrates recorder, transcriber, inbox writer.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import shutil
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

# --- Logging setup ---
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "voice-journal.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("voice-journal")

QUEUE_WARN_THRESHOLD = 3


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.json"
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def collect_orphan_segments(temp_dir: Path, work_queue: queue.Queue) -> None:
    """
    On startup: find unprocessed mic FLAC files in temp_dir (excluding failed/).
    Enqueue them for transcription.
    """
    failed_dir = temp_dir / "failed"
    for mic_file in sorted(temp_dir.glob("*_mic.flac")):
        if mic_file.parent == failed_dir:
            continue
        # Check for matching sys file
        sys_file = temp_dir / mic_file.name.replace("_mic.flac", "_sys.flac")
        sys_path = str(sys_file) if sys_file.exists() else None

        # Parse start timestamp from filename
        ts_str = mic_file.stem.replace("_mic", "")
        try:
            start_ts = datetime.strptime(ts_str, "%Y%m%d_%H%M%S")
        except ValueError:
            logger.warning("Cannot parse timestamp from orphan file: %s", mic_file)
            continue

        logger.info("Orphan segment found, enqueuing: %s", mic_file.name)
        work_queue.put((start_ts, str(mic_file), sys_path))


def get_retry_count(base_path: str) -> int:
    retry_file = Path(base_path + ".retry")
    if retry_file.exists():
        try:
            return int(retry_file.read_text().strip())
        except Exception:
            return 0
    return 0


def set_retry_count(base_path: str, count: int) -> None:
    retry_file = Path(base_path + ".retry")
    retry_file.write_text(str(count))


def clear_retry_sidecar(base_path: str) -> None:
    retry_file = Path(base_path + ".retry")
    if retry_file.exists():
        retry_file.unlink()


def worker_loop(
    work_queue: queue.Queue,
    cfg: dict,
    stop_event: threading.Event,
) -> None:
    """Worker thread: dequeue segments, transcribe, write inbox, manage files."""
    from transcriber import Transcriber
    import inbox_writer

    temp_dir = Path(cfg["temp_dir"])
    failed_dir = temp_dir / "failed"
    failed_dir.mkdir(exist_ok=True)

    logger.info("Loading Whisper model...")
    try:
        transcriber = Transcriber(
            model=cfg.get("whisper_model", "small"),
            whisper_device=cfg.get("whisper_device", "auto"),
            compute_type=cfg.get("whisper_compute_type", "int8"),
            language=cfg.get("language", "ja"),
        )
    except Exception as exc:
        logger.error("Failed to load Whisper model: %s", exc)
        return

    while not stop_event.is_set() or not work_queue.empty():
        try:
            start_ts, mic_path, sys_path = work_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        qsize = work_queue.qsize()
        if qsize > QUEUE_WARN_THRESHOLD:
            logger.warning("Transcription queue backlog: %d items pending", qsize)

        # Approximate end time from segment_seconds (or derive from filename gap)
        end_ts = datetime.fromtimestamp(
            start_ts.timestamp() + cfg.get("segment_seconds", 3600)
        )

        base_path = mic_path  # use mic_path as base for retry sidecar
        retries = get_retry_count(base_path)

        try:
            logger.info("Transcribing segment starting %s", start_ts.strftime("%Y%m%d_%H%M%S"))
            result = transcriber.transcribe(mic_path, sys_path)
            text = result.get("text", "")
            logger.info(
                "Transcription done (%.1f s audio): %d chars",
                result.get("duration", 0), len(text)
            )

            # Write to inbox（PC音をキャプチャできなかった場合は注記を付ける）
            note = None
            if sys_path is None and cfg.get("capture_system_audio", True):
                note = "PC音をキャプチャできなかったため、マイク音声のみの文字起こしです。"
            inbox_writer.append(
                start_ts, end_ts, text,
                note=note,
                inbox_dir=cfg.get("inbox_dir")
            )

            # Success: delete audio files
            if cfg.get("delete_audio_after_transcribe", True):
                for p in [mic_path, sys_path]:
                    if p and Path(p).exists():
                        Path(p).unlink()
                        logger.info("Deleted audio: %s", p)
            clear_retry_sidecar(base_path)

        except Exception as exc:
            logger.error("Error processing segment %s: %s", mic_path, exc)
            retries += 1
            max_retries = cfg.get("max_transcribe_retries", 3)

            if retries > max_retries:
                logger.warning(
                    "Max retries (%d) exceeded for %s — moving to failed/",
                    max_retries, mic_path
                )
                for p in [mic_path, sys_path]:
                    if p and Path(p).exists():
                        dest = failed_dir / Path(p).name
                        shutil.move(p, dest)
                        logger.info("Moved to failed/: %s", dest)
                clear_retry_sidecar(base_path)
            else:
                set_retry_count(base_path, retries)
                logger.info(
                    "Will retry segment (attempt %d/%d): %s",
                    retries, max_retries, mic_path
                )
                # Re-enqueue for retry
                work_queue.put((start_ts, mic_path, sys_path))

        work_queue.task_done()

    logger.info("Worker thread finished.")


def main() -> None:
    cfg = load_config()
    temp_dir = Path(cfg["temp_dir"])
    temp_dir.mkdir(parents=True, exist_ok=True)
    (temp_dir / "failed").mkdir(exist_ok=True)

    logger.info("voice-journal service starting.")
    logger.info("temp_dir: %s", temp_dir)
    logger.info("inbox_dir: %s", cfg.get("inbox_dir"))

    work_queue: queue.Queue = queue.Queue()
    stop_event = threading.Event()

    # Collect orphan segments from previous run
    collect_orphan_segments(temp_dir, work_queue)

    # on_segment callback: enqueue completed segment
    def on_segment(start_ts: datetime, mic_path: str, sys_path) -> None:
        logger.info(
            "Segment complete: %s (sys=%s)",
            Path(mic_path).name, Path(sys_path).name if sys_path else "None"
        )
        work_queue.put((start_ts, mic_path, sys_path))

    # Start worker thread
    worker = threading.Thread(
        target=worker_loop,
        args=(work_queue, cfg, stop_event),
        daemon=True,
        name="transcribe-worker",
    )
    worker.start()

    # Start recorder
    from recorder import AudioRecorder
    recorder = AudioRecorder(
        temp_dir=str(temp_dir),
        segment_seconds=cfg.get("segment_seconds", 3600),
        align_to_clock_hour=cfg.get("align_to_clock_hour", True),
        mic_device=cfg.get("mic_device"),
        loopback_device=cfg.get("loopback_device"),
        capture_system_audio=cfg.get("capture_system_audio", True),
        on_segment=on_segment,
    )

    def shutdown(signum=None, frame=None) -> None:
        logger.info("Shutdown signal received. Stopping recorder...")
        recorder.stop()
        logger.info("Waiting for worker to drain queue...")
        stop_event.set()
        worker.join(timeout=60)
        logger.info("voice-journal service stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    recorder.start()
    logger.info("Recorder started. Press Ctrl+C to stop.")

    # Main thread: keep alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown()


if __name__ == "__main__":
    main()
