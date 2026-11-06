import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from audio_monitor.analysis import DB_FLOOR, analyze_block
from audio_monitor.engine import AudioEvents, WaveRecorder


class AudioAnalysisTests(unittest.TestCase):
    def test_silence_has_floor_levels_and_no_signal(self):
        result = analyze_block(np.zeros((2048, 2), dtype=np.float32), 48000)

        self.assertEqual(result["peak_dbfs"], [DB_FLOOR, DB_FLOOR])
        self.assertEqual(result["rms_dbfs"], [DB_FLOOR, DB_FLOOR])
        self.assertEqual(result["signal"], [False, False])
        self.assertEqual(result["clipping"], [False, False])
        self.assertEqual(len(result["spectrum"]), 2)

    def test_real_signal_reports_peak_rms_spectrum_and_clipping(self):
        sample_rate = 48000
        time_axis = np.arange(4096, dtype=np.float32) / sample_rate
        tone = 0.5 * np.sin(2 * np.pi * 1000 * time_axis)
        samples = np.column_stack((tone, np.full_like(tone, 1.0)))

        result = analyze_block(samples, sample_rate)

        self.assertAlmostEqual(result["peak_dbfs"][0], -6.02, delta=0.1)
        self.assertAlmostEqual(result["rms_dbfs"][0], -9.03, delta=0.1)
        self.assertEqual(result["signal"], [True, True])
        self.assertEqual(result["clipping"], [False, True])
        peak_frequency, peak_level = max(result["spectrum"][0], key=lambda item: item[1])
        self.assertAlmostEqual(peak_frequency, 1000, delta=150)
        self.assertGreater(peak_level, -10)

    def test_rejects_empty_or_invalid_audio(self):
        with self.assertRaises(ValueError):
            analyze_block(np.empty((0, 2), dtype=np.float32), 48000)
        with self.assertRaises(ValueError):
            analyze_block(np.ones((128, 1), dtype=np.float32), 0)

    def test_wave_recorder_writes_real_input_blocks_as_pcm(self):
        events = AudioEvents()
        recorder = WaveRecorder(events)
        samples = np.array([[0.0, 0.5], [-0.5, 1.0]], dtype=np.float32)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "capture.wav"
            recorder.start(str(path), channels=2, sample_rate=48000)
            recorder.push(samples)
            recorder.stop()
            recorder.shutdown()

            with wave.open(str(path), "rb") as audio_file:
                self.assertEqual(audio_file.getnchannels(), 2)
                self.assertEqual(audio_file.getframerate(), 48000)
                self.assertEqual(audio_file.getsampwidth(), 2)
                self.assertEqual(audio_file.getnframes(), 2)


if __name__ == "__main__":
    unittest.main()
