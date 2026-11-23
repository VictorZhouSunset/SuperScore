import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from superscore_audio_cli.conditioning import condition_audio, condition_file


def _component_magnitude(signal: np.ndarray, sample_rate: int, frequency_hz: float) -> float:
    spectrum = np.abs(np.fft.rfft(signal.astype(np.float64, copy=False)))
    frequencies = np.fft.rfftfreq(signal.shape[0], d=1.0 / sample_rate)
    index = int(np.argmin(np.abs(frequencies - frequency_hz)))
    return float(spectrum[index])


class ConditioningTests(unittest.TestCase):
    def test_bass_conditioning_reduces_rumble_boosts_harmonics_and_targets_rms(self):
        sample_rate = 44100
        time = np.arange(sample_rate, dtype=np.float32) / sample_rate
        stereo = np.stack(
            [
                0.18 * np.sin(2 * np.pi * 10 * time)
                + 0.03 * np.sin(2 * np.pi * 55 * time)
                + 0.002 * np.sin(2 * np.pi * 1200 * time),
                0.09 * np.sin(2 * np.pi * 10 * time)
                + 0.015 * np.sin(2 * np.pi * 55 * time)
                + 0.001 * np.sin(2 * np.pi * 1200 * time),
            ],
            axis=1,
        ).astype(np.float32)
        mono_input = np.mean(stereo, axis=1)

        conditioned, conditioned_sample_rate = condition_audio("bass", stereo, sample_rate)
        conditioned_rms = float(np.sqrt(np.mean(np.square(conditioned))))
        input_rumble_ratio = _component_magnitude(mono_input, sample_rate, 10.0) / _component_magnitude(
            mono_input, sample_rate, 55.0
        )
        output_rumble_ratio = _component_magnitude(
            conditioned, conditioned_sample_rate, 10.0
        ) / _component_magnitude(conditioned, conditioned_sample_rate, 55.0)
        input_harmonic_ratio = _component_magnitude(
            mono_input, sample_rate, 1200.0
        ) / _component_magnitude(mono_input, sample_rate, 55.0)
        output_harmonic_ratio = _component_magnitude(
            conditioned, conditioned_sample_rate, 1200.0
        ) / _component_magnitude(conditioned, conditioned_sample_rate, 55.0)

        self.assertEqual(conditioned.ndim, 1)
        self.assertEqual(conditioned_sample_rate, sample_rate)
        self.assertAlmostEqual(conditioned_rms, 0.18, delta=0.02)
        self.assertLess(output_rumble_ratio, input_rumble_ratio * 0.35)
        self.assertGreater(output_harmonic_ratio, input_harmonic_ratio * 1.2)

    def test_condition_file_writes_float_wav_output(self):
        sample_rate = 44100
        audio = 0.05 * np.sin(2 * np.pi * 55 * np.arange(sample_rate, dtype=np.float32) / sample_rate)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            src = temp_root / "bass.wav"
            dst = temp_root / "conditioned.wav"
            sf.write(src, audio, sample_rate, subtype="FLOAT")

            conditioned_path = condition_file("bass", src, dst)
            info = sf.info(conditioned_path)

        self.assertEqual(conditioned_path, dst)
        self.assertEqual(info.subtype, "FLOAT")


if __name__ == "__main__":
    unittest.main()
