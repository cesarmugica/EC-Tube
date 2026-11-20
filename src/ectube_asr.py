"""EC-Tube: escuchar el audio y escribir los subtítulos (reconocimiento de voz en la PC, con faster-whisper).

El «oído» (modelo Whisper) se baja una sola vez de Hugging Face; después funciona sin internet.
"""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from typing import Callable

MODELS = {  # calidad → (repositorio, MB aproximados)
    "base": ("Systran/faster-whisper-base", 145),
    "small": ("Systran/faster-whisper-small", 484),
}
FILES = ["config.json", "tokenizer.json", "vocabulary.txt", "model.bin"]
RATE = 16000


def model_dir(home: Path, quality: str) -> Path:
    return home / "oido" / quality


def model_ready(home: Path, quality: str) -> bool:
    folder = model_dir(home, quality)
    return all((folder / f).is_file() for f in FILES)


def download_model(home: Path, quality: str, progress: Callable[[float], None], cancelled: Callable[[], bool],
                   user_agent: str = "EC-Tube") -> Path:
    """Bajar el modelo (con avance de 0 a 100). Se baja a una carpeta temporal y se cambia al final."""
    repo, mb = MODELS[quality]
    folder = model_dir(home, quality)
    if model_ready(home, quality):
        return folder
    tmp = folder.with_name(folder.name + "-bajando")
    tmp.mkdir(parents=True, exist_ok=True)
    total_guess = mb * 1024 * 1024
    done = 0
    for name in FILES:
        target = tmp / name
        url = f"https://huggingface.co/{repo}/resolve/main/{name}"
        request = urllib.request.Request(url, headers={"User-Agent": user_agent})
        with urllib.request.urlopen(request, timeout=60) as response, target.open("wb") as out:  # noqa: S310
            while chunk := response.read(512 * 1024):
                if cancelled():
                    raise InterruptedError
                out.write(chunk)
                done += len(chunk)
                progress(min(99.0, done * 100 / total_guess))
    if folder.exists():
        import shutil

        shutil.rmtree(folder, ignore_errors=True)
    tmp.replace(folder)
    progress(100.0)
    return folder


def transcribe(audio, folder: Path, language: str | None, progress: Callable[[float], None],
               cancelled: Callable[[], bool]) -> tuple[list[dict], str]:
    """audio: numpy float32 mono a 16 kHz. Regresa (bloques de subtítulos, idioma que escuchó)."""
    from faster_whisper import WhisperModel

    from ectube_subs import _group

    model = WhisperModel(str(folder), device="cpu", compute_type="int8", cpu_threads=max(1, (os.cpu_count() or 2) - 1))
    duration = max(0.1, len(audio) / RATE)
    segments, info = model.transcribe(audio, language=language or None, vad_filter=True, word_timestamps=True,
                                      condition_on_previous_text=False, beam_size=5)
    words: list[tuple[float, float, str]] = []
    for seg in segments:  # se va escuchando mientras se recorre
        if cancelled():
            raise InterruptedError
        if seg.words:
            words += [(w.start, w.end, w.word.strip()) for w in seg.words if w.word.strip()]
        elif seg.text.strip():
            words.append((seg.start, seg.end, seg.text.strip()))
        progress(min(99.0, seg.end * 100 / duration))
    progress(100.0)
    return _group(words), getattr(info, "language", "") or ""
