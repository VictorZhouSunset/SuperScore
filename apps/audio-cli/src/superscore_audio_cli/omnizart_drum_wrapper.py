import argparse
import os
from pathlib import Path

# Omnizart's default Windows path fans out aggressively across native and
# Python workers. Cap thread counts before the heavy imports happen.
for env_key in (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMBA_NUM_THREADS",
    "TF_NUM_INTRAOP_THREADS",
    "TF_NUM_INTEROP_THREADS",
):
    os.environ.setdefault(env_key, "1")
os.environ.setdefault("PYTHONUTF8", "1")
os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import librosa
import numpy as np
from omnizart.drum.app import DrumTranscription
import omnizart.feature.beat_for_drum as beat_for_drum
import omnizart.feature.cqt as cqt
from omnizart.io import load_audio_with_librosa


def _stable_extract_cqt(
    audio_path: str,
    sampling_rate: int = 44100,
    lowest_note: int = 16,
    note_num: int = 120,
    a_hop: int = 256,
    pad_sec: float = 1,
):
    audio_data, _ = load_audio_with_librosa(audio_path, sampling_rate=sampling_rate)
    audio_data = np.asarray(audio_data, dtype=np.float32)
    zeros = np.zeros(int(pad_sec * sampling_rate), dtype=audio_data.dtype)
    padded_audio = np.concatenate([zeros, audio_data, zeros])
    audio_gram = librosa.cqt(
        padded_audio,
        sr=sampling_rate,
        hop_length=a_hop,
        fmin=librosa.midi_to_hz(lowest_note),
        n_bins=note_num,
    )
    return cqt.post_process_cqt(audio_gram)


def _trimmed_bpm(pred_beats: np.ndarray) -> float:
    beat_spans = np.sort(pred_beats[1:] - pred_beats[:-1])
    trimmed = beat_spans[int(len(pred_beats) * 0.2):int(len(pred_beats) * 0.8)]
    return 60.0 / np.mean(trimmed)


def _sequential_process(self, audio_data):
    original_threads = self.num_threads
    self.num_threads = 1
    try:
        pred_beats1 = self._get_dbn_down_beat(audio_data, min_bpm_in=50, max_bpm_in=230)
        pred_beats2 = self._get_dbn_beat(audio_data)
        pred_beats3 = self._get_beat(audio_data)
        pred_bpm_avg = np.mean(
            [
                _trimmed_bpm(pred_beats1),
                _trimmed_bpm(pred_beats2),
                _trimmed_bpm(pred_beats3),
            ]
        )
        return self._get_dbn_down_beat(
            audio_data,
            min_bpm_in=pred_bpm_avg / 1.38,
            max_bpm_in=pred_bpm_avg * 1.38,
        )
    finally:
        self.num_threads = original_threads


def _install_runtime_patches() -> None:
    cqt.load_audio = load_audio_with_librosa
    cqt.extract_cqt = _stable_extract_cqt
    beat_for_drum.load_audio = load_audio_with_librosa
    beat_for_drum.MadmomBeatTracking.process = _sequential_process


def main() -> int:
    parser = argparse.ArgumentParser(prog="superscore-omnizart-drum")
    parser.add_argument("input_audio")
    parser.add_argument("output_dir")
    args = parser.parse_args()

    _install_runtime_patches()

    input_audio = Path(args.input_audio)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    DrumTranscription().transcribe(str(input_audio), output=str(output_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
