"""Lightweight audio enhancement for completed speech segments."""

from __future__ import annotations

from dataclasses import dataclass

import noisereduce as nr
import numpy as np

from utils.audio_utils import db_to_linear, rms_db

# EPSILON is used to prevent division by ZERO error.
EPSILON = 1e-8


@dataclass(frozen=True)
class AudioEnhanceConfig:
    """Configuration for conservative speech enhancement.

    Attributes:
        sample_rate: Audio sample rate in Hz.
        target_rms_db: Target RMS level after normalization.
        max_gain_db: Maximum gain applied during normalization.
        compressor_threshold_db: Level where compression starts.
        compressor_ratio: Ratio used above the compressor threshold.
        limiter_peak: Maximum absolute sample value after limiting.
        noise_reduce_enabled: Whether to run noisereduce after dynamics.
        noise_reduce_stationary: Whether to use a stationary noise profile.
        noise_reduce_prop_decrease: Noise reduction strength.
        noise_reduce_n_fft: FFT size used by noisereduce.
    """

    sample_rate: int = 16000
    target_rms_db: float = -23.0
    max_gain_db: float = 18.0
    compressor_threshold_db: float = -20.0
    compressor_ratio: float = 2.0
    limiter_peak: float = 0.95
    noise_reduce_enabled: bool = True
    noise_reduce_stationary: bool = False
    noise_reduce_prop_decrease: float = 0.8
    noise_reduce_n_fft: int = 512


class AudioEnhancer:
    """Applies conservative enhancement to completed speech audio."""

    def __init__(self, config: AudioEnhanceConfig | None = None):

        self.config = config or AudioEnhanceConfig()

    def enhance(
        self,
        samples: np.ndarray,
        noise_reference: np.ndarray | None = None,
    ) -> np.ndarray:
        """Enhances a speech segment without changing its sample rate.

        Args:
            samples: Mono float audio samples.
            noise_reference: Optional non-speech reference audio.

        Returns:
            Enhanced mono float32 audio.
        """

        audio = np.asarray(samples, dtype=np.float32).copy()
        if audio.size == 0:
            return audio

        audio = self._remove_dc_offset(audio)
        audio = self._normalize_rms(audio)
        audio = self._compress(audio)
        audio = self._limit(audio)

        if self.config.noise_reduce_enabled:
            audio = self._reduce_noise(audio, noise_reference)
            audio = self._limit(audio)

        return audio.astype(np.float32, copy=False)

    # 辅助方法：完成音频增强的过程 -- 包括去除直流偏移、RMS归一化、压缩、限制和降噪

    def _remove_dc_offset(self, samples: np.ndarray) -> np.ndarray:
        """Removes constant offset from the waveform."""

        return samples - np.mean(samples, dtype=np.float32)

    def _normalize_rms(self, samples: np.ndarray) -> np.ndarray:
        """Moves RMS toward the target level with capped gain."""

        current_db = rms_db(samples)
        gain_db = min(self.config.target_rms_db - current_db, self.config.max_gain_db)
        return samples * db_to_linear(gain_db)

    def _compress(self, samples: np.ndarray) -> np.ndarray:
        """Applies a simple static compressor above the threshold."""

        abs_samples = np.abs(samples)
        signs = np.sign(samples)
        threshold = db_to_linear(self.config.compressor_threshold_db)
        over = abs_samples > threshold
        compressed = abs_samples.copy()
        compressed[over] = (
            threshold + (abs_samples[over] - threshold) / self.config.compressor_ratio
        )
        return compressed * signs

    def _limit(self, samples: np.ndarray) -> np.ndarray:
        """Prevents samples from exceeding the configured peak."""

        peak = float(np.max(np.abs(samples)))
        if peak <= self.config.limiter_peak:
            return samples
        return samples * (self.config.limiter_peak / max(peak, EPSILON))

    def _reduce_noise(
        self, samples: np.ndarray, noise_reference: np.ndarray | None
    ) -> np.ndarray:
        """Runs conservative noisereduce when the segment is long enough."""

        if samples.size < self.config.noise_reduce_n_fft:
            return samples

        if (
            self.config.noise_reduce_stationary
            and noise_reference is not None
            and noise_reference.size > 0
        ):
            return nr.reduce_noise(
                y=samples,
                sr=self.config.sample_rate,
                y_noise=np.asarray(noise_reference, dtype=np.float32),
                stationary=True,
                prop_decrease=self.config.noise_reduce_prop_decrease,
                n_fft=self.config.noise_reduce_n_fft,
                use_tqdm=False,
            ).astype(np.float32)

        return nr.reduce_noise(
            y=samples,
            sr=self.config.sample_rate,
            stationary=False,
            prop_decrease=self.config.noise_reduce_prop_decrease,
            n_fft=self.config.noise_reduce_n_fft,
            use_tqdm=False,
        ).astype(np.float32)
