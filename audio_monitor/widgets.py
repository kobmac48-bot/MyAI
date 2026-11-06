"""Custom-painted meter and spectrum widgets for the monitor UI."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from .analysis import DB_FLOOR


class LevelMeter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = DB_FLOOR
        self.peak = DB_FLOOR
        self.clip = False
        self.hold_until = 0.0
        self.setMinimumSize(26, 190)

    def set_levels(self, level: float, peak: float, clipping: bool, hold_seconds: float) -> None:
        self.level = level
        now = time.monotonic()
        if peak >= self.peak or now >= self.hold_until:
            self.peak = peak
            self.hold_until = now + hold_seconds
        self.clip = self.clip or clipping
        self.update()

    def reset_clip(self) -> None:
        self.clip = False
        self.update()

    def reset_peak(self) -> None:
        self.peak = DB_FLOOR
        self.clip = False
        self.update()

    def _y_for_db(self, value: float, top: int, height: int) -> int:
        normalized = max(0.0, min(1.0, (value + 60.0) / 60.0))
        return top + height - int(normalized * height)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        bounds = self.rect().adjusted(3, 4, -3, -4)
        painter.fillRect(bounds, QColor("#101316"))
        top, height = bounds.top(), bounds.height()
        for db, color in ((-60, "#263238"), (-18, "#20bd73"), (-6, "#e4b83f"), (0, "#e65b52")):
            y = self._y_for_db(db, top, height)
            painter.setPen(QPen(QColor(color), 1))
            painter.drawLine(bounds.left(), y, bounds.right(), y)

        y_level = self._y_for_db(self.level, top, height)
        y_zero = self._y_for_db(-60.0, top, height)
        if y_level < y_zero:
            painter.fillRect(
                bounds.left() + 2,
                y_level,
                max(1, bounds.width() - 3),
                y_zero - y_level,
                QColor("#20bd73"),
            )
            yellow_y = self._y_for_db(-18.0, top, height)
            red_y = self._y_for_db(-6.0, top, height)
            if y_level < yellow_y:
                painter.fillRect(
                    bounds.left() + 2,
                    y_level,
                    max(1, bounds.width() - 3),
                    min(yellow_y, y_zero) - y_level,
                    QColor("#e4b83f"),
                )
            if y_level < red_y:
                painter.fillRect(
                    bounds.left() + 2,
                    y_level,
                    max(1, bounds.width() - 3),
                    red_y - y_level,
                    QColor("#e65b52"),
                )

        if self.peak > -60:
            peak_y = self._y_for_db(self.peak, top, height)
            painter.fillRect(bounds.left(), peak_y, bounds.width(), 2, QColor("#f2f5f5"))
        if self.clip:
            painter.fillRect(bounds.left(), bounds.top(), bounds.width(), 4, QColor("#ef5149"))


class ChannelStrip(QFrame):
    def __init__(self, number: int, parent=None):
        super().__init__(parent)
        self.number = number
        self.raw_peak = DB_FLOOR
        self.raw_rms = DB_FLOOR
        self.setObjectName("channelStrip")
        self.setFixedWidth(126)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 9, 8, 9)
        layout.setSpacing(6)

        self.title = QLabel(f"INPUT {number}")
        self.title.setObjectName("channelTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.name = QLabel(f"Audioeingang {number}")
        self.name.setObjectName("mutedLabel")
        self.name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        layout.addWidget(self.name)

        self.signal = QLabel("KEIN SIGNAL")
        self.signal.setObjectName("signalOff")
        self.signal.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.signal)
        self.clip_label = QLabel("● CLIP")
        self.clip_label.setStyleSheet("color: #ef5149; font-weight: 700;")
        self.clip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clip_label.setVisible(False)
        layout.addWidget(self.clip_label)

        meter_row = QHBoxLayout()
        meter_row.setSpacing(6)
        self.meter = LevelMeter()
        meter_row.addWidget(self.meter, 1)

        fader_column = QVBoxLayout()
        fader_column.setSpacing(1)
        self.trim_value = QLabel("0 dB")
        self.trim_value.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.trim_value.setObjectName("mutedLabel")
        self.fader = QSlider(Qt.Orientation.Vertical)
        self.fader.setRange(-24, 12)
        self.fader.setValue(0)
        self.fader.setInvertedAppearance(True)
        self.fader.setToolTip(
            "Virtueller Analyse-Trim: veraendert nur die Meterdarstellung, "
            "nicht den Mixer oder die WAV-Aufnahme."
        )
        self.fader.valueChanged.connect(self._trim_changed)
        trim_label = QLabel("TRIM")
        trim_label.setObjectName("tinyLabel")
        trim_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        fader_column.addWidget(self.trim_value)
        fader_column.addWidget(self.fader, 1, Qt.AlignmentFlag.AlignHCenter)
        fader_column.addWidget(trim_label)
        meter_row.addLayout(fader_column)
        layout.addLayout(meter_row, 1)

        scale = QLabel("  0 dB\n-6 dB\n-18 dB\n-36 dB\n-60 dBFS")
        scale.setObjectName("tinyLabel")
        scale.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(scale)
        self.peak_label = QLabel("PEAK  -120.0 dBFS")
        self.rms_label = QLabel("RMS   -120.0 dBFS")
        self.peak_label.setObjectName("valueLabel")
        self.rms_label.setObjectName("valueLabel")
        layout.addWidget(self.peak_label)
        layout.addWidget(self.rms_label)

        self.monitor_button = QPushButton("ANZEIGE AN")
        self.monitor_button.setCheckable(True)
        self.monitor_button.setChecked(True)
        self.monitor_button.setObjectName("toggleButton")
        self.monitor_button.toggled.connect(self._monitor_toggled)
        layout.addWidget(self.monitor_button)

    def _trim_changed(self, value: int) -> None:
        self.trim_value.setText(f"{value:+d} dB")

    def _monitor_toggled(self, enabled: bool) -> None:
        self.monitor_button.setText("ANZEIGE AN" if enabled else "ANZEIGE AUS")
        if not enabled:
            self.signal.setText("AUSGEBLENDET")
            self.signal.setObjectName("signalOff")
            self.signal.style().unpolish(self.signal)
            self.signal.style().polish(self.signal)

    def update_levels(
        self,
        peak: float,
        rms: float,
        signal_present: bool,
        clipping: bool,
        hold_seconds: float,
    ) -> None:
        self.raw_peak = peak
        self.raw_rms = rms
        self.peak_label.setText(f"PEAK  {peak:7.1f} dBFS")
        self.rms_label.setText(f"RMS   {rms:7.1f} dBFS")
        if self.monitor_button.isChecked():
            adjusted = min(0.0, peak + self.fader.value())
            rms_adjusted = min(0.0, rms + self.fader.value())
            self.meter.set_levels(rms_adjusted, adjusted, clipping, hold_seconds)
            self.signal.setText("SIGNAL" if signal_present else "KEIN SIGNAL")
            self.signal.setObjectName("signalOn" if signal_present else "signalOff")
            self.signal.style().unpolish(self.signal)
            self.signal.style().polish(self.signal)
        else:
            self.meter.set_levels(DB_FLOOR, DB_FLOOR, clipping, hold_seconds)
        self.clip_label.setVisible(self.meter.clip)


class SpectrumWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.spectrum: list[tuple[float, float]] = []
        self.setMinimumHeight(190)

    def set_spectrum(self, bins: list[tuple[float, float]]) -> None:
        self.spectrum = bins
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        area = self.rect().adjusted(38, 12, -12, -27)
        painter.fillRect(self.rect(), QColor("#101316"))
        for level in (-90, -60, -30, 0):
            y = area.bottom() - int((level + 90) / 90 * area.height())
            painter.setPen(QPen(QColor("#30373b"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(area.left(), y, area.right(), y)
            painter.setPen(QColor("#8d999e"))
            painter.drawText(2, y + 4, f"{level} dB")

        if self.spectrum:
            bar_width = area.width() / len(self.spectrum)
            for index, (_, level) in enumerate(self.spectrum):
                normalized = max(0.0, min(1.0, (level + 90.0) / 90.0))
                bar_height = normalized * area.height()
                color = QColor("#20bd73") if level < -18 else (
                    QColor("#e4b83f") if level < -6 else QColor("#e65b52")
                )
                painter.fillRect(
                    int(area.left() + index * bar_width),
                    int(area.bottom() - bar_height),
                    max(1, int(bar_width - 1)),
                    int(bar_height),
                    color,
                )
        painter.setPen(QColor("#aab5b9"))
        painter.drawText(area.left(), self.height() - 6, "20 Hz")
        painter.drawText(area.center().x() - 20, self.height() - 6, "1 kHz")
        painter.drawText(area.right() - 52, self.height() - 6, "20 kHz")
