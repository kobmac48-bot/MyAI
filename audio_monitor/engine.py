"""Audio-device discovery, capture, analysis, and WAV recording."""

from __future__ import annotations

import queue
import threading
import time
import wave
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, Signal

from .analysis import analyze_block


class AudioEvents(QObject):
    data_ready = Signal(object)
    status = Signal(str)
    error = Signal(str)
    recording_changed = Signal(bool, str)


def enumerate_input_devices() -> list[dict]:
    """Return actual PortAudio input devices and their host APIs."""
    try:
        import sounddevice as sd
    except ImportError as error:
        raise RuntimeError(
            "sounddevice fehlt. Installiere die Pakete aus requirements.txt."
        ) from error

    try:
        devices = sd.query_devices()
        host_apis = sd.query_hostapis()
    except sd.PortAudioError as error:
        raise RuntimeError(f"Audioeingangsgeraete konnten nicht gelesen werden: {error}") from error
    result = []
    for index, device in enumerate(devices):
        channels = int(device["max_input_channels"])
        if channels <= 0:
            continue
        host_api = host_apis[int(device["hostapi"])]["name"]
        result.append(
            {
                "index": index,
                "name": str(device["name"]),
                "host_api": str(host_api),
                "channels": channels,
                "default_samplerate": int(round(device["default_samplerate"])),
            }
        )
    return result


class WaveRecorder:
    """Write captured PCM blocks from a background thread, never the audio callback."""

    def __init__(self, events: AudioEvents):
        self._events = events
        self._queue: queue.Queue = queue.Queue(maxsize=128)
        self._enabled = threading.Event()
        self._abort = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def active(self) -> bool:
        return self._enabled.is_set()

    def start(self, path: str, channels: int, sample_rate: int) -> None:
        if self.active:
            raise RuntimeError("Es laeuft bereits eine Aufnahme.")
        self._abort.clear()
        self._enabled.set()
        try:
            self._queue.put_nowait(("start", path, channels, sample_rate))
        except queue.Full as error:
            self._enabled.clear()
            raise RuntimeError("WAV-Schreibpuffer ist beschaeftigt; bitte erneut versuchen.") from error

    def push(self, samples: np.ndarray) -> None:
        if not self.active:
            return
        try:
            self._queue.put_nowait(("audio", samples.copy()))
        except queue.Full:
            self._enabled.clear()
            self._abort.set()
            self._events.error.emit(
                "Aufnahme angehalten: Der WAV-Schreibpuffer ist uebergelaufen."
            )

    def stop(self) -> None:
        if self._enabled.is_set():
            self._enabled.clear()
            try:
                self._queue.put_nowait(("stop",))
            except queue.Full:
                self._abort.set()

    def _run(self) -> None:
        output = None

        def close_output() -> None:
            nonlocal output
            if output is None:
                return
            try:
                output.close()
            except (OSError, wave.Error) as error:
                self._events.error.emit(f"WAV-Datei konnte nicht abgeschlossen werden: {error}")
            finally:
                output = None

        while True:
            command = self._queue.get()
            kind = command[0]
            try:
                if kind == "start":
                    _, path, channels, sample_rate = command
                    output = wave.open(str(Path(path)), "wb")
                    output.setnchannels(channels)
                    output.setsampwidth(2)
                    output.setframerate(sample_rate)
                    self._events.recording_changed.emit(True, str(path))
                elif kind == "audio" and output is not None:
                    samples = np.nan_to_num(
                        command[1], copy=False, nan=0.0, posinf=1.0, neginf=-1.0
                    )
                    samples = np.clip(samples, -1.0, 1.0)
                    pcm = (samples * 32767.0).astype("<i2", copy=False)
                    output.writeframesraw(pcm.tobytes())
                elif kind == "stop":
                    close_output()
                    self._events.recording_changed.emit(False, "")
                elif kind == "shutdown":
                    close_output()
                    return
            except (OSError, wave.Error, ValueError) as error:
                self._enabled.clear()
                close_output()
                self._events.recording_changed.emit(False, "")
                self._events.error.emit(f"WAV-Aufnahme fehlgeschlagen: {error}")
            if self._abort.is_set():
                close_output()
                self._abort.clear()
                self._events.recording_changed.emit(False, "")

    def shutdown(self) -> None:
        self.stop()
        self._queue.put(("shutdown",))
        self._thread.join(timeout=2.0)


class AudioEngine:
    """Capture real input channels; signal analysis is kept off the GUI thread."""

    def __init__(self, events: AudioEvents):
        self.events = events
        self._stream = None
        self._processor: threading.Thread | None = None
        self._blocks: queue.Queue = queue.Queue(maxsize=32)
        self._running = threading.Event()
        self._reported_overrun = False
        self._recorder = WaveRecorder(events)
        self.device: dict | None = None
        self.sample_rate = 0
        self.blocksize = 0

    @property
    def running(self) -> bool:
        return self._running.is_set()

    def start(self, device: dict, sample_rate: int, blocksize: int) -> None:
        if self.running:
            self.stop()
        try:
            import sounddevice as sd
        except ImportError as error:
            raise RuntimeError(
                "sounddevice fehlt. Installiere die Pakete aus requirements.txt."
            ) from error

        channels = device["channels"]
        try:
            sd.check_input_settings(
                device=device["index"],
                channels=channels,
                samplerate=sample_rate,
                dtype="float32",
            )
            self._blocks = queue.Queue(maxsize=32)
            self.device = device
            self.sample_rate = sample_rate
            self.blocksize = blocksize
            self._running.set()
            self._processor = threading.Thread(target=self._process, daemon=True)
            self._processor.start()
            self._stream = sd.InputStream(
                device=device["index"],
                channels=channels,
                samplerate=sample_rate,
                blocksize=blocksize,
                dtype="float32",
                latency="low",
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception as error:
            self._running.clear()
            if self._stream is not None:
                try:
                    self._stream.close()
                except Exception:
                    pass
                self._stream = None
            if self._processor is not None:
                self._processor.join(timeout=1.0)
                self._processor = None
            raise RuntimeError(f"Audioeingang konnte nicht gestartet werden: {error}") from error

        self.events.status.emit(
            f"Live · {device['name']} · {channels} echte USB-Eingaenge"
        )

    def _audio_callback(self, indata, frames, time_info, status) -> None:
        if status:
            self.events.status.emit(f"Audio-Callback: {status}")
        try:
            self._blocks.put_nowait((indata.copy(), time.monotonic()))
            self._reported_overrun = False
        except queue.Full:
            if not self._reported_overrun:
                self.events.status.emit(
                    "Warnung: Analysepuffer ueberlaufen; Audioblock verworfen."
                )
                self._reported_overrun = True

    def _process(self) -> None:
        while self._running.is_set() or not self._blocks.empty():
            try:
                samples, captured_at = self._blocks.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                result = analyze_block(samples, self.sample_rate)
                result.update(
                    {
                        "captured_at": captured_at,
                        "sample_rate": self.sample_rate,
                        "callback_latency_ms": self.blocksize * 1000.0 / self.sample_rate,
                    }
                )
                self.events.data_ready.emit(result)
                self._recorder.push(samples)
            except (ValueError, FloatingPointError) as error:
                self.events.error.emit(f"Audioanalyse fehlgeschlagen: {error}")

    def start_recording(self, path: str) -> None:
        if not self.running or not self.device:
            raise RuntimeError("Vor der Aufnahme muss ein Audioeingang gestartet werden.")
        self._recorder.start(path, self.device["channels"], self.sample_rate)

    def stop_recording(self) -> None:
        self._recorder.stop()

    def stop(self) -> None:
        self._recorder.stop()
        self._running.clear()
        stream = self._stream
        self._stream = None
        stream_error = None
        if stream is not None:
            try:
                stream.stop()
            except Exception as error:
                stream_error = error
            finally:
                try:
                    stream.close()
                except Exception as error:
                    if stream_error is None:
                        stream_error = error
        if self._processor is not None:
            self._processor.join(timeout=1.0)
            self._processor = None
        self.events.status.emit("Gestoppt")
        if stream_error is not None:
            raise RuntimeError(f"Audioeingang konnte nicht sauber gestoppt werden: {stream_error}") from stream_error

    def shutdown(self) -> None:
        try:
            self.stop()
        finally:
            self._recorder.shutdown()
