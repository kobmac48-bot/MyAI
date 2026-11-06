"""Dark studio-style control center for real USB audio monitoring."""

from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import Qt, QStandardPaths, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDial,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .engine import AudioEngine, AudioEvents, enumerate_input_devices
from .widgets import ChannelStrip, SpectrumWidget


STYLE = """
QMainWindow, QWidget { background: #171a1d; color: #e5e9e9; font-family: "Segoe UI"; font-size: 10pt; }
QFrame#panel, QFrame#channelStrip { background: #202428; border: 1px solid #343b3e; border-radius: 7px; }
QFrame#channelStrip { background: #22272a; }
QLabel#brand { color: #f0f3f2; font-size: 19pt; font-weight: 700; }
QLabel#subtitle, QLabel#mutedLabel, QLabel#tinyLabel { color: #91a0a4; }
QLabel#sectionTitle { color: #dce3e2; font-size: 11pt; font-weight: 600; }
QLabel#channelTitle { color: #e3e9e7; font-weight: 700; }
QLabel#signalOn { color: #27d184; font-weight: 700; }
QLabel#signalOff { color: #7d888c; font-weight: 700; }
QLabel#valueLabel { color: #b7c1c3; font-family: Consolas; font-size: 8pt; }
QLabel#status { color: #24cb81; font-weight: 600; }
QLabel#warning { color: #e4b83f; }
QComboBox, QPushButton {
  background: #2a3033; border: 1px solid #424b4f; border-radius: 4px;
  padding: 6px 9px; color: #edf1f0; min-height: 22px;
}
QComboBox:hover, QPushButton:hover { border-color: #21b977; }
QComboBox::drop-down { border: none; width: 22px; }
QPushButton:checked, QPushButton#primaryButton { background: #146d4b; border-color: #27c880; }
QPushButton:disabled { color: #778184; background: #202426; border-color: #343a3d; }
QPushButton#recordButton:checked { background: #8c2827; border-color: #ef5c55; }
QPushButton#toggleButton { padding: 5px 3px; font-size: 8pt; }
QSlider::groove:vertical { width: 5px; background: #424a4d; border-radius: 2px; }
QSlider::handle:vertical { height: 12px; margin: 0 -5px; background: #d9e2df; border: 1px solid #fff; border-radius: 3px; }
QDial { background: #30373a; }
QScrollArea { border: none; }
QScrollBar:horizontal { height: 11px; background: #171a1d; }
QScrollBar::handle:horizontal { background: #515c60; border-radius: 4px; min-width: 24px; }
"""

MIXER_LAYOUT = (
    "Mic/Line 1",
    "Mic/Line 2",
    "Mic/Line 3",
    "Mic/Line 4",
    "Stereo Line 5/6",
    "Stereo Line 7/8",
    "Stereo Line 9/10",
    "Stereo Line 11/12",
    "Main Mix",
    "USB Return",
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Behringer XENYX 1204 USB Control Center")
        self.setMinimumSize(1080, 760)
        self.resize(1380, 900)
        self.setStyleSheet(STYLE)

        self.events = AudioEvents()
        self.engine = AudioEngine(self.events)
        self.devices: list[dict] = []
        self.strips: list[ChannelStrip] = []
        self.last_data: dict | None = None
        self.record_started: float | None = None
        self.settings_path = self._settings_path()

        self._build_ui()
        self._connect_events()
        self._load_settings()
        self.refresh_devices()

        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(33)
        self.ui_timer.timeout.connect(self._tick)
        self.ui_timer.start()

    @staticmethod
    def _settings_path() -> Path:
        location = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
        path = Path(location) / "settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _build_ui(self) -> None:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 14, 18, 14)
        outer.setSpacing(12)
        self.setCentralWidget(root)

        header = QHBoxLayout()
        brand_stack = QVBoxLayout()
        brand = QLabel("XENYX 1204 USB  |  CONTROL CENTER")
        brand.setObjectName("brand")
        subtitle = QLabel("USB-Audio-Monitor · reale Eingangskanäle · Echtzeitanalyse")
        subtitle.setObjectName("subtitle")
        brand_stack.addWidget(brand)
        brand_stack.addWidget(subtitle)
        header.addLayout(brand_stack, 1)
        self.status_label = QLabel("Bereit")
        self.status_label.setObjectName("status")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        header.addWidget(self.status_label)
        outer.addLayout(header)

        controls = QFrame()
        controls.setObjectName("panel")
        control_layout = QHBoxLayout(controls)
        control_layout.setContentsMargins(12, 8, 12, 8)
        control_layout.setSpacing(8)
        control_layout.addWidget(self._label("EINGANGSGERÄT"))
        self.device_combo = QComboBox()
        self.device_combo.setMinimumWidth(280)
        self.device_combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.device_combo.currentIndexChanged.connect(self._populate_rates)
        control_layout.addWidget(self.device_combo, 1)
        self.refresh_button = QPushButton("Aktualisieren")
        self.refresh_button.clicked.connect(self.refresh_devices)
        control_layout.addWidget(self.refresh_button)
        control_layout.addWidget(self._label("RATE"))
        self.rate_combo = QComboBox()
        self.rate_combo.setMinimumWidth(110)
        control_layout.addWidget(self.rate_combo)
        control_layout.addWidget(self._label("PUFFER"))
        self.buffer_combo = QComboBox()
        for size in (128, 256, 512, 1024, 2048, 4096):
            self.buffer_combo.addItem(f"{size} Samples", size)
        self.buffer_combo.setCurrentIndex(3)
        control_layout.addWidget(self.buffer_combo)
        self.start_button = QPushButton("Eingang starten")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self._toggle_audio)
        control_layout.addWidget(self.start_button)
        self.save_settings_button = QPushButton("Einstellungen speichern")
        self.save_settings_button.clicked.connect(self._save_settings)
        control_layout.addWidget(self.save_settings_button)
        self.load_settings_button = QPushButton("Einstellungen laden")
        self.load_settings_button.clicked.connect(self._load_settings)
        control_layout.addWidget(self.load_settings_button)
        outer.addWidget(controls)

        details = QHBoxLayout()
        self.audio_info = QLabel("Abtastrate: —   ·   Puffer: —   ·   Latenz (Puffer): —")
        self.audio_info.setObjectName("mutedLabel")
        self.audio_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        details.addWidget(self.audio_info, 1)
        self.output_info = QLabel("Ausgang: nicht separat erfasst")
        self.output_info.setObjectName("warning")
        details.addWidget(self.output_info)
        outer.addLayout(details)

        channel_heading = QHBoxLayout()
        title = QLabel("ERKANNTE AUDIO-EINGÄNGE")
        title.setObjectName("sectionTitle")
        self.channel_count = QLabel("Noch kein Gerät ausgewählt")
        self.channel_count.setObjectName("mutedLabel")
        channel_heading.addWidget(title)
        channel_heading.addWidget(self.channel_count)
        channel_heading.addStretch(1)
        self.reset_peaks_button = QPushButton("Peak / Clip zuruecksetzen")
        self.reset_peaks_button.clicked.connect(self._reset_peaks)
        channel_heading.addWidget(self.reset_peaks_button)
        outer.addLayout(channel_heading)

        self.channel_scroll = QScrollArea()
        self.channel_scroll.setWidgetResizable(True)
        self.channel_scroll.setMinimumHeight(420)
        self.channel_scroll.setMaximumHeight(510)
        self.channel_container = QWidget()
        self.channel_layout = QHBoxLayout(self.channel_container)
        self.channel_layout.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.channel_layout.setContentsMargins(2, 2, 2, 6)
        self.channel_layout.setSpacing(8)
        self.channel_scroll.setWidget(self.channel_container)
        outer.addWidget(self.channel_scroll, 1)

        lower = QHBoxLayout()
        analysis_panel = QFrame()
        analysis_panel.setObjectName("panel")
        analysis_layout = QVBoxLayout(analysis_panel)
        analysis_layout.setContentsMargins(12, 9, 12, 9)
        spectrum_header = QHBoxLayout()
        spectrum_title = QLabel("FFT-SPEKTRUM")
        spectrum_title.setObjectName("sectionTitle")
        spectrum_header.addWidget(spectrum_title)
        spectrum_header.addStretch(1)
        spectrum_header.addWidget(self._label("KANAL"))
        self.spectrum_channel = QComboBox()
        self.spectrum_channel.setMinimumWidth(130)
        self.spectrum_channel.currentIndexChanged.connect(self._refresh_spectrum)
        spectrum_header.addWidget(self.spectrum_channel)
        analysis_layout.addLayout(spectrum_header)
        self.spectrum = SpectrumWidget()
        analysis_layout.addWidget(self.spectrum, 1)
        lower.addWidget(analysis_panel, 1)

        side_panel = QFrame()
        side_panel.setObjectName("panel")
        side_layout = QVBoxLayout(side_panel)
        side_layout.setContentsMargins(12, 9, 12, 9)
        side_title = QLabel("AUFNAHME & ANALYSE")
        side_title.setObjectName("sectionTitle")
        side_layout.addWidget(side_title)
        record_row = QHBoxLayout()
        self.record_button = QPushButton("●  WAV aufnehmen")
        self.record_button.setObjectName("recordButton")
        self.record_button.setCheckable(True)
        self.record_button.toggled.connect(self._toggle_recording)
        record_row.addWidget(self.record_button, 1)
        self.record_time = QLabel("00:00:00")
        self.record_time.setObjectName("valueLabel")
        record_row.addWidget(self.record_time)
        side_layout.addLayout(record_row)
        self.record_path_label = QLabel("WAV speichert unveraenderte Eingangsdaten.")
        self.record_path_label.setObjectName("mutedLabel")
        self.record_path_label.setWordWrap(True)
        side_layout.addWidget(self.record_path_label)

        hold_row = QHBoxLayout()
        hold_text = QVBoxLayout()
        hold_text.addWidget(self._label("PEAK-HOLD"))
        self.hold_value = QLabel("1.5 s")
        self.hold_value.setObjectName("mutedLabel")
        hold_text.addWidget(self.hold_value)
        hold_row.addLayout(hold_text)
        hold_row.addStretch(1)
        self.hold_dial = QDial()
        self.hold_dial.setRange(0, 9)
        self.hold_dial.setValue(2)
        self.hold_dial.setNotchesVisible(True)
        self.hold_dial.setFixedSize(66, 66)
        self.hold_dial.valueChanged.connect(
            lambda value: self.hold_value.setText(f"{0.5 + value * 0.5:.1f} s")
        )
        hold_row.addWidget(self.hold_dial)
        side_layout.addLayout(hold_row)
        self.analysis_summary = QLabel(
            "Peak und RMS werden pro erkanntem USB-Kanal aus dem Eingangssignal berechnet."
        )
        self.analysis_summary.setObjectName("mutedLabel")
        self.analysis_summary.setWordWrap(True)
        side_layout.addWidget(self.analysis_summary, 1)
        lower.addWidget(side_panel, 0)
        outer.addLayout(lower, 1)

        reference = QFrame()
        reference.setObjectName("panel")
        reference_layout = QVBoxLayout(reference)
        reference_layout.setContentsMargins(12, 7, 12, 7)
        ref_title = QLabel(
            "PULT-LAYOUT (Referenz) — diese analogen Kanäle werden nicht separat per USB übertragen"
        )
        ref_title.setObjectName("warning")
        reference_layout.addWidget(ref_title)
        ref_channels = QHBoxLayout()
        for channel in MIXER_LAYOUT:
            label = QLabel(channel)
            label.setObjectName("tinyLabel")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ref_channels.addWidget(label, 1)
        reference_layout.addLayout(ref_channels)
        outer.addWidget(reference)

    @staticmethod
    def _label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("tinyLabel")
        return label

    def _connect_events(self) -> None:
        self.events.data_ready.connect(self._update_data)
        self.events.status.connect(self._set_status)
        self.events.error.connect(self._show_error)
        self.events.recording_changed.connect(self._recording_changed)

    def _load_settings(self) -> None:
        if not self.settings_path.is_file():
            return
        try:
            settings = json.loads(self.settings_path.read_text(encoding="utf-8"))
            if not isinstance(settings, dict):
                raise ValueError("Die Einstellungsdatei muss ein JSON-Objekt enthalten.")
            self._saved_device = settings.get("device", "")
            self._saved_host = settings.get("host_api", "")
            self._saved_rate = int(settings.get("sample_rate", 0))
            blocksize = int(settings.get("blocksize", 1024))
            trims = settings.get("channel_trim", [])
            monitors = settings.get("channel_monitor", [])
            self._saved_trims = trims if isinstance(trims, list) else []
            self._saved_monitors = monitors if isinstance(monitors, list) else []
            self.buffer_combo.setCurrentIndex(
                max(0, self.buffer_combo.findData(blocksize))
            )
            self.hold_dial.setValue(max(0, min(9, int(settings.get("peak_hold", 2)))))
            if hasattr(self, "device_combo"):
                for index in range(self.device_combo.count()):
                    device = self.device_combo.itemData(index)
                    if (
                        device["name"] == self._saved_device
                        and device["host_api"] == self._saved_host
                    ):
                        self.device_combo.setCurrentIndex(index)
                        break
                selected_device = self.device_combo.currentData()
                if selected_device and (
                    selected_device["name"] == self._saved_device
                    and selected_device["host_api"] == self._saved_host
                ):
                    selected_rate = self.rate_combo.findData(self._saved_rate)
                    if selected_rate >= 0:
                        self.rate_combo.setCurrentIndex(selected_rate)
                for index, strip in enumerate(self.strips):
                    if index < len(self._saved_trims):
                        strip.fader.setValue(max(-24, min(12, int(self._saved_trims[index]))))
                    if index < len(self._saved_monitors):
                        strip.monitor_button.setChecked(bool(self._saved_monitors[index]))
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
            self._set_status(f"Einstellungen nicht geladen: {error}", warning=True)
            self._saved_device = ""
            self._saved_host = ""
            self._saved_rate = 0

    def _save_settings(self) -> None:
        device = self.device_combo.currentData()
        settings = {
            "device": device["name"] if device else "",
            "host_api": device["host_api"] if device else "",
            "sample_rate": self.rate_combo.currentData() or 0,
            "blocksize": self.buffer_combo.currentData(),
            "peak_hold": self.hold_dial.value(),
            "channel_trim": [strip.fader.value() for strip in self.strips],
            "channel_monitor": [strip.monitor_button.isChecked() for strip in self.strips],
        }
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(
                json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self._set_status(f"Einstellungen gespeichert · {self.settings_path}")
        except OSError as error:
            self._show_error(f"Einstellungen konnten nicht gespeichert werden: {error}")

    def refresh_devices(self) -> None:
        try:
            devices = enumerate_input_devices()
        except (RuntimeError, OSError) as error:
            self.devices = []
            self.device_combo.clear()
            self._show_error(str(error))
            return
        self.devices = devices
        self.device_combo.clear()
        for device in devices:
            self.device_combo.addItem(
                f"{device['name']}  ·  {device['channels']} ch  ·  {device['host_api']}",
                device,
            )

        target_index = 0
        for index, device in enumerate(devices):
            if (
                device["name"] == getattr(self, "_saved_device", "")
                and device["host_api"] == getattr(self, "_saved_host", "")
            ):
                target_index = index
                break
        if devices:
            self.device_combo.setCurrentIndex(target_index)
            self._populate_rates()
            self._set_status(f"{len(devices)} Audio-Eingangsgerät(e) erkannt")
        else:
            self._set_status("Keine Audio-Eingangsgeräte erkannt", warning=True)

    def _populate_rates(self) -> None:
        device = self.device_combo.currentData()
        self.rate_combo.clear()
        if not device:
            return
        rates = [0, 44100, 48000, 88200, 96000, 176400, 192000]
        for rate in rates:
            label = (
                f"Standard ({device['default_samplerate']})"
                if rate == 0
                else str(rate)
            )
            self.rate_combo.addItem(label, rate)
        use_saved_rate = (
            device["name"] == getattr(self, "_saved_device", "")
            and device["host_api"] == getattr(self, "_saved_host", "")
        )
        selected_rate = self._saved_rate if use_saved_rate else 0
        selected = self.rate_combo.findData(selected_rate)
        self.rate_combo.setCurrentIndex(max(0, selected))

    def _toggle_audio(self) -> None:
        if self.engine.running:
            try:
                self.engine.stop()
            except Exception as error:
                self._show_error(f"Audioeingang konnte nicht sauber gestoppt werden: {error}")
            self.start_button.setText("Eingang starten")
            self.device_combo.setEnabled(True)
            self.rate_combo.setEnabled(True)
            self.buffer_combo.setEnabled(True)
            self.refresh_button.setEnabled(True)
            self.load_settings_button.setEnabled(True)
            self.audio_info.setText("Abtastrate: —   ·   Puffer: —   ·   Latenz: —")
            return
        device = self.device_combo.currentData()
        if not device:
            self._show_error("Bitte zuerst ein Audio-Eingangsgerät auswählen.")
            return
        requested_rate = self.rate_combo.currentData()
        rate = requested_rate or device["default_samplerate"]
        blocksize = self.buffer_combo.currentData()
        try:
            self.engine.start(device, rate, blocksize)
        except RuntimeError as error:
            self._show_error(str(error))
            return
        self._make_strips(device["channels"], device["name"])
        self.device_combo.setEnabled(False)
        self.rate_combo.setEnabled(False)
        self.buffer_combo.setEnabled(False)
        self.refresh_button.setEnabled(False)
        self.load_settings_button.setEnabled(False)
        self.start_button.setText("Eingang stoppen")
        self.audio_info.setText(
            f"Abtastrate: {rate:,} Hz   ·   Puffer: {blocksize} Samples   ·   "
            f"Latenz (Puffer): {blocksize * 1000 / rate:.1f} ms"
        )

    def _make_strips(self, count: int, device_name: str = "") -> None:
        while self.channel_layout.count():
            item = self.channel_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self.strips = []
        self.spectrum_channel.clear()
        for index in range(count):
            strip = ChannelStrip(index + 1)
            if "BEHRINGER" in device_name.upper():
                strip.title.setText(f"BEHRINGER USB {index + 1}")
                if count == 2:
                    side = "L · links" if index == 0 else "R · rechts"
                    strip.name.setText(f"USB-Kanal {index + 1} · {side}")
            if index < len(getattr(self, "_saved_trims", [])):
                strip.fader.setValue(max(-24, min(12, int(self._saved_trims[index]))))
            if index < len(getattr(self, "_saved_monitors", [])):
                strip.monitor_button.setChecked(bool(self._saved_monitors[index]))
            self.strips.append(strip)
            self.channel_layout.addWidget(strip)
            self.spectrum_channel.addItem(f"Eingang {index + 1}", index)
        channel_word = "Eingangskanal" if count == 1 else "Eingangskanäle"
        self.channel_count.setText(f"{count} {channel_word} · vom Audiogerät gemeldet")

    def _update_data(self, result: dict) -> None:
        self.last_data = result
        hold_seconds = 0.5 + self.hold_dial.value() * 0.5
        for index, strip in enumerate(self.strips):
            strip.update_levels(
                result["peak_dbfs"][index],
                result["rms_dbfs"][index],
                result["signal"][index],
                result["clipping"][index],
                hold_seconds,
            )
        self._refresh_spectrum()
        active = sum(result["signal"])
        clipped = sum(result["clipping"])
        self.analysis_summary.setText(
            f"Aktive Eingänge: {active}/{len(self.strips)}  ·  "
            f"Clipping: {clipped}  ·  "
            f"Block: {result['callback_latency_ms']:.1f} ms"
        )

    def _refresh_spectrum(self) -> None:
        if not self.last_data or not self.last_data["spectrum"]:
            self.spectrum.set_spectrum([])
            return
        channel = self.spectrum_channel.currentData()
        if channel is None or channel >= len(self.last_data["spectrum"]):
            return
        self.spectrum.set_spectrum(self.last_data["spectrum"][channel])

    def _reset_peaks(self) -> None:
        for strip in self.strips:
            strip.meter.reset_peak()
            strip.clip_label.setVisible(False)

    def _toggle_recording(self, recording: bool) -> None:
        if recording:
            if not self.engine.running:
                self.record_button.setChecked(False)
                self._show_error("Starten Sie zuerst den Audioeingang, bevor Sie aufnehmen.")
                return
            path, _ = QFileDialog.getSaveFileName(
                self, "WAV-Aufnahme speichern", "xenyx-recording.wav", "WAV-Datei (*.wav)"
            )
            if not path:
                self.record_button.setChecked(False)
                return
            if not path.lower().endswith(".wav"):
                path += ".wav"
            try:
                self.engine.start_recording(path)
            except RuntimeError as error:
                self.record_button.setChecked(False)
                self._show_error(str(error))
                return
            self.record_started = time.monotonic()
            self.record_path_label.setText(f"Aufnahme: {path}")
            self.record_button.setText("■  Aufnahme stoppen")
        else:
            self.engine.stop_recording()
            self.record_started = None
            self.record_button.setText("●  WAV aufnehmen")

    def _recording_changed(self, active: bool, path: str) -> None:
        if active:
            self.record_path_label.setText(f"Aufnahme: {path}")
        else:
            self.record_started = None
            self.record_button.blockSignals(True)
            self.record_button.setChecked(False)
            self.record_button.blockSignals(False)
            self.record_button.setText("●  WAV aufnehmen")

    def _tick(self) -> None:
        if self.record_started is not None:
            elapsed = int(time.monotonic() - self.record_started)
            hours, remainder = divmod(elapsed, 3600)
            minutes, seconds = divmod(remainder, 60)
            self.record_time.setText(f"{hours:02}:{minutes:02}:{seconds:02}")

    def _set_status(self, message: str, warning: bool = False) -> None:
        self.status_label.setText(message)
        self.status_label.setObjectName("warning" if warning else "status")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _show_error(self, message: str) -> None:
        self._set_status(message, warning=True)
        QMessageBox.warning(self, "Audio-Monitor", message)

    def closeEvent(self, event):
        self.ui_timer.stop()
        try:
            self.engine.shutdown()
        except RuntimeError as error:
            self._set_status(f"Audio-Stopp: {error}", warning=True)
        event.accept()


def run() -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("Behringer XENYX 1204 USB Control Center")
    window = MainWindow()
    window.show()
    return app.exec()
