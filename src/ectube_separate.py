"""Separar voz y música (modelo MDX-Net «Kim Vocal 2» de UVR, con ONNX Runtime).

- Solo voz: lo que da el modelo.
- Solo música: la mezcla original menos la voz (lo mismo que hace UVR).
El modelo (~65 MB) se baja la primera vez y se revisa su huella SHA-256.
"""

from __future__ import annotations

import contextlib
import hashlib
import urllib.request
from pathlib import Path

import numpy as np

MODEL_URL = "https://github.com/TRvlvr/model_repo/releases/download/all_public_uvr_models/Kim_Vocal_2.onnx"
MODEL_SHA256 = "ce74ef3b6a6024ce44211a07be9cf8bc6d87728cc852a68ab34eb8e58cde9c8b"

# Datos del modelo Kim_Vocal_2.onnx (tabla de modelos de UVR)
N_FFT = 7680
DIM_F = 3072
DIM_T = 256
HOP = 1024
RATE = 44100
OVERLAP = 0.25


def ensure_model(folder: Path, progress=None, cancelled=None) -> Path:
    target = folder / "Kim_Vocal_2.onnx"
    if target.is_file() and target.stat().st_size > 10_000_000:
        return target
    folder.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".part")
    digest = hashlib.sha256()
    request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "EC-Tube"})
    with urllib.request.urlopen(request, timeout=60) as response, tmp.open("wb") as out:  # noqa: S310
        size = int(response.headers.get("Content-Length") or 0)
        got = 0
        while chunk := response.read(256 * 1024):
            if cancelled and cancelled():
                raise InterruptedError("cancelado")
            out.write(chunk)
            digest.update(chunk)
            got += len(chunk)
            if progress and size:
                progress(got / size)
    if digest.hexdigest() != MODEL_SHA256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("El separador se descargó mal. Vuelve a intentar.")
    tmp.replace(target)
    return target


class MDX:
    def __init__(self, model_path: str, session=None) -> None:
        if session is None:
            import onnxruntime as ort

            with contextlib.suppress(Exception):
                ort.set_default_logger_severity(3)
            # DirectML usa la tarjeta de video que tengas (NVIDIA, AMD o Intel); si no, el procesador.
            available = ort.get_available_providers()
            providers = [p for p in ("DmlExecutionProvider", "CPUExecutionProvider") if p in available]
            options = ort.SessionOptions()
            options.log_severity_level = 3
            options.enable_mem_pattern = False  # DirectML lo pide así
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            try:
                session = ort.InferenceSession(model_path, providers=providers, sess_options=options)
            except Exception:  # noqa: BLE001  (sin DirectML que sirva: procesador)
                session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"], sess_options=options)
        self.providers = list(getattr(session, "get_providers", lambda: [])())
        self.session = session
        n = np.arange(N_FFT)
        self.window = (0.5 - 0.5 * np.cos(2 * np.pi * n / N_FFT)).astype(np.float32)  # Hann periódica
        self.chunk = HOP * (DIM_T - 1)
        self.trim = N_FFT // 2
        self.n_bins = N_FFT // 2 + 1

    # STFT / ISTFT iguales a torch.stft/istft(center=True, reflect)
    def _stft(self, x: np.ndarray) -> np.ndarray:
        """x: (2, T) → (1, 4, DIM_F, frames): [re0, im0, re1, im1]."""
        half = N_FFT // 2
        padded = np.pad(x, ((0, 0), (half, half)), mode="reflect")
        frames = 1 + (padded.shape[1] - N_FFT) // HOP
        idx = np.arange(N_FFT)[None, :] + HOP * np.arange(frames)[:, None]
        spec = np.fft.rfft(padded[:, idx] * self.window, axis=-1)  # (2, frames, bins)
        spec = spec.transpose(0, 2, 1)[:, :DIM_F, :]               # (2, DIM_F, frames)
        out = np.stack([spec.real, spec.imag], 1).reshape(1, 4, DIM_F, frames)
        return out.astype(np.float32)

    def _istft(self, spec: np.ndarray) -> np.ndarray:
        """(1, 4, DIM_F, frames) → (2, T)."""
        frames = spec.shape[-1]
        full = np.zeros((4, self.n_bins, frames), np.float32)
        full[:, :DIM_F] = spec[0]
        complex_spec = (full[0::2] + 1j * full[1::2]).transpose(0, 2, 1)  # (2, frames, bins)
        chunks = np.fft.irfft(complex_spec, n=N_FFT, axis=-1) * self.window
        length = N_FFT + HOP * (frames - 1)
        out = np.zeros((2, length), np.float64)
        norm = np.zeros(length, np.float64)
        for i in range(frames):
            out[:, i * HOP:i * HOP + N_FFT] += chunks[:, i]
            norm[i * HOP:i * HOP + N_FFT] += self.window ** 2
        half = N_FFT // 2
        out = out[:, half:length - half] / np.maximum(norm[half:length - half], 1e-8)
        return out.astype(np.float32)

    def _run(self, part: np.ndarray) -> np.ndarray:
        spec = self._stft(part)
        spec[:, :, :3, :] = 0
        pred = self.session.run(None, {"input": spec})[0]
        return self._istft(np.asarray(pred, dtype=np.float32))

    def vocals(self, mix: np.ndarray, progress=None, cancelled=None) -> np.ndarray:
        """mix: (2, T) float32 → voz (2, T). progress(0..1) y cancelled() son opcionales."""
        peak = float(np.abs(mix).max()) or 1.0
        mix = mix / peak
        gen = self.chunk - 2 * self.trim
        pad = gen + self.trim - (mix.shape[-1] % gen)
        mixture = np.concatenate([np.zeros((2, self.trim), np.float32), mix, np.zeros((2, pad), np.float32)], 1)
        step = int((1 - OVERLAP) * self.chunk)
        result = np.zeros((2, mixture.shape[-1]), np.float32)
        divider = np.zeros((2, mixture.shape[-1]), np.float32)
        total = max(1, -(-mixture.shape[-1] // step))
        if True:
            for number, start in enumerate(range(0, mixture.shape[-1], step)):
                if cancelled and cancelled():
                    raise InterruptedError("cancelado")
                if progress:
                    progress(number / total)
                end = min(start + self.chunk, mixture.shape[-1])
                size = end - start
                part = mixture[:, start:end]
                if size < self.chunk:
                    part = np.concatenate([part, np.zeros((2, self.chunk - size), np.float32)], 1)
                out = self._run(part)[:, :size]
                window = np.hanning(size)[None, :].astype(np.float32)
                result[:, start:end] += out * window
                divider[:, start:end] += window
        out = (result / np.maximum(divider, 1e-8))[:, self.trim:self.trim + mix.shape[-1]]
        return out * peak


