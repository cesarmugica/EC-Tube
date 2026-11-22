"""EC-Tube — descargar audio y video de YouTube (y otros sitios) en la PC.

Servidor local (solo 127.0.0.1) con una página sencilla. Las descargas las
hace yt-dlp.exe (se actualiza solo una vez al día), con Deno para resolver
los retos de YouTube y FFmpeg para convertir/unir audio y video.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

APP_VERSION = "5.6.0"

try:  # lo genera windows/build.ps1
    from ectube_build import BUILD_DATE  # type: ignore[import-not-found]
except ImportError:
    BUILD_DATE = ""

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
EXE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else ROOT
WEB_ROOT = ROOT / "web"
DEFAULT_PORT = 8791
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]", "::1"}
IS_WINDOWS = os.name == "nt"
EXE = ".exe" if IS_WINDOWS else ""


def ectube_home() -> Path:
    override = os.environ.get("ECTUBE_HOME")
    if override:
        return Path(override)
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return (Path(base) if base else Path.home() / "AppData" / "Local") / "EC-Tube"
    return Path.home() / ".local" / "state" / "ectube"


HOME = ectube_home()
BIN_DIR = HOME / "bin"  # copia de yt-dlp que se puede actualizar sin permisos


# ---------------------------------------------------------------------------
# Arranque: registro y ventanas negras
# ---------------------------------------------------------------------------
def _setup_logging() -> None:
    if sys.stdout is not None and not getattr(sys, "frozen", False):
        return
    log_dir = HOME / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "ectube.log"
    with contextlib.suppress(OSError):
        if log_path.exists() and log_path.stat().st_size > 2 * 1024 * 1024:
            log_path.replace(log_dir / "ectube.old.log")
    stream = open(log_path, "a", encoding="utf-8", buffering=1)  # noqa: SIM115
    sys.stdout = sys.stderr = stream


def _no_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if IS_WINDOWS else 0


_setup_logging()


def log(message: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), message, flush=True)


# ---------------------------------------------------------------------------
# Herramientas: yt-dlp, Deno y FFmpeg
# ---------------------------------------------------------------------------
def _bundled(name: str) -> Path | None:
    for candidate in (EXE_DIR / "bin" / name, EXE_DIR / name, ROOT / "bin" / name, ROOT / name):
        if candidate.is_file():
            return candidate
    return None


def _tool(name: str) -> str | None:
    found = _bundled(name + EXE)
    if found:
        return str(found)
    return shutil.which(name)


def ytdlp_path() -> str | None:
    """yt-dlp vive en %LOCALAPPDATA%\\EC-Tube\\bin para poder actualizarse solo."""
    env = os.environ.get("ECTUBE_YTDLP")
    if env:
        return env
    local = BIN_DIR / ("yt-dlp" + EXE)
    bundled = _bundled("yt-dlp" + EXE)
    if bundled and not local.is_file():
        with contextlib.suppress(OSError):
            BIN_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(bundled, local)
    if local.is_file():
        return str(local)
    return str(bundled) if bundled else shutil.which("yt-dlp")


FFMPEG = os.environ.get("ECTUBE_FFMPEG") or _tool("ffmpeg")
DENO = os.environ.get("ECTUBE_DENO") or _tool("deno")


class Engine:
    """Versión de yt-dlp y su actualización diaria (yt-dlp -U)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.version = ""
        self.updating = False
        self.last_update_message = ""

    def _run(self, args: list[str], timeout: float) -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=timeout, creationflags=_no_window_flags())

    def refresh_version(self) -> str:
        path = ytdlp_path()
        if not path:
            self.version = ""
            return ""
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            self.version = self._run([path, "--version"], 30).stdout.strip()
        return self.version

    def update(self, force: bool = False) -> None:
        stamp = HOME / "last-update.txt"
        if not force:
            with contextlib.suppress(OSError, ValueError):
                if time.time() - float(stamp.read_text().strip()) < 20 * 3600:
                    return
        path = ytdlp_path()
        if not path or not path.startswith(str(BIN_DIR)):
            return  # solo se actualiza la copia propia
        with self.lock:
            if self.updating:
                return
            self.updating = True
        try:
            log("Buscando actualización de yt-dlp…")
            result = self._run([path, "-U"], 180)
            text = (result.stdout + result.stderr).strip()
            log("yt-dlp -U: " + text.replace("\n", " | ")[:400])
            if "Updated yt-dlp to" in text:
                self.last_update_message = "Motor actualizado."
            elif "is up to date" in text:
                self.last_update_message = "El motor ya está al día."
            else:
                self.last_update_message = "No se pudo buscar actualización (¿sin internet?)."
            with contextlib.suppress(OSError):
                HOME.mkdir(parents=True, exist_ok=True)
                stamp.write_text(str(time.time()))
        except (OSError, subprocess.SubprocessError) as exc:
            self.last_update_message = "No se pudo buscar actualización."
            log(f"Error al actualizar yt-dlp: {exc}")
        finally:
            self.updating = False
            self.refresh_version()


ENGINE = Engine()


# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
OUTPUTS = Path.home() / "EC-Tube Outputs"
# Todo lo que hace EC-Tube, ordenado debajo de tu carpeta de usuario:
#   EC-Tube Outputs\MUSIC\Downloaded | Edited   ·   VIDEO\Downloaded | Edited   ·   KARAOKE\Downloaded | Edited
NEW_FOLDERS = {
    "audio_folder": OUTPUTS / "MUSIC" / "Downloaded", "audio_edited_folder": OUTPUTS / "MUSIC" / "Edited",
    "video_folder": OUTPUTS / "VIDEO" / "Downloaded", "video_edited_folder": OUTPUTS / "VIDEO" / "Edited",
    "karaoke_folder": OUTPUTS / "KARAOKE" / "Edited",
}
EXTRA_FOLDERS = [OUTPUTS / "KARAOKE" / "Downloaded"]


def _old_default_folders() -> dict:
    """Carpetas que EC-Tube usaba antes por defecto (si siguen así, se cambian a EC-Tube Outputs)."""
    old = {}
    for key, kind, name in (("audio_folder", "audio", "EC-Tube"), ("video_folder", "video", "EC-Tube"),
                            ("audio_edited_folder", "audio", "EC-Tube Editados"), ("video_edited_folder", "video", "EC-Tube Editados"),
                            ("karaoke_folder", "video", "EC-Tube Karaoke")):
        options = set()
        for base in (Path.home() / ("Music" if kind == "audio" else "Videos"), Path.home() / "Downloads"):
            options.add(os.path.normcase(str(base / name)))
        old[key] = options
    return old


def _default_folder(kind: str, edited: bool = False) -> str:
    return str(NEW_FOLDERS[f"{kind}_edited_folder" if edited else f"{kind}_folder"])


CONFIG_PATH = HOME / "config.json"
DEFAULT_CONFIG = {
    "port": DEFAULT_PORT,
    "kind": "audio",
    "audio_format": "mp3",
    "audio_quality": "320",
    "video_quality": "1080",
    "audio_folder": "",
    "video_folder": "",
    "audio_edited_folder": "",   # recortes de audio (aparte de las descargas)
    "video_edited_folder": "",   # recortes de video
    "karaoke_folder": "",        # videos de karaoke terminados
    "playlist": False,
    "language": "",  # "es" o "en"; vacío = el del instalador o el de Windows
    "bank_dismissed": 0,  # el banco de animaciones que dijiste «Ahora no» (para no volver a avisar de ese)
}
AUDIO_FORMATS = {"mp3", "m4a", "wav"}
AUDIO_QUALITIES = {"320", "192", "128"}
VIDEO_QUALITIES = {"best", "2160", "1440", "1080", "720", "480", "360"}
CONFIG_LOCK = threading.Lock()


def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    with contextlib.suppress(OSError, json.JSONDecodeError):
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            config.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
    old = _old_default_folders()
    for key, folder in NEW_FOLDERS.items():
        value = config.get(key) or ""
        if not value or os.path.normcase(value) in old[key]:
            config[key] = str(folder)  # vacío o el de antes por defecto → EC-Tube Outputs (si lo cambiaste tú, se respeta)
    with contextlib.suppress(OSError):
        for folder in [*NEW_FOLDERS.values(), *EXTRA_FOLDERS]:
            folder.mkdir(parents=True, exist_ok=True)
    return config


def current_language(accept: str = "") -> str:
    if CONFIG.get("language") in ("es", "en"):
        return CONFIG["language"]
    with contextlib.suppress(OSError):
        installed = (HOME / "language.txt").read_text(encoding="utf-8").strip().lower()
        if installed in ("es", "en"):
            return installed
    return "en" if accept.strip().lower().startswith("en") else "es"


def save_config(config: dict) -> None:
    with CONFIG_LOCK, contextlib.suppress(OSError):
        HOME.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


CONFIG = load_config()


# ---------------------------------------------------------------------------
# Descargas
# ---------------------------------------------------------------------------
URL_RE = re.compile(r"^https?://[^\s/$.?#][^\s]*$", re.I)
MAX_PARALLEL = 2

# Errores frecuentes de yt-dlp → mensaje entendible.
ERROR_HINTS = [
    (r"Private video", "El video es privado."),
    (r"Video unavailable|This video is not available|has been removed", "El video no está disponible (borrado o bloqueado en tu país)."),
    (r"Sign in to confirm your age|age-restricted|inappropriate for some users", "El video tiene restricción de edad y pide iniciar sesión en YouTube."),
    (r"Sign in to confirm you.re not a bot", "YouTube pide confirmar que no eres un robot. Espera un rato y vuelve a intentar."),
    (r"members-only|Join this channel", "El video es solo para miembros del canal."),
    (r"live event will begin|Premieres in|This live event", "La transmisión todavía no empieza."),
    (r"Unsupported URL", "Ese enlace no es de un sitio compatible."),
    (r"Requested format is not available", "No hay esa calidad para este video. Prueba con «Máxima»."),
    (r"HTTP Error 403|Forbidden", "El sitio rechazó la descarga. Dale «Actualizar motor» y reintenta."),
    (r"HTTP Error 429|Too Many Requests", "Demasiadas descargas seguidas; el sitio pide esperar. Intenta más tarde."),
    (r"Unable to download webpage|getaddrinfo failed|timed out|Connection reset", "No hay conexión a internet o el sitio no respondió."),
    (r"No space left|Errno 28", "No hay espacio en el disco."),
    (r"Permission denied|Errno 13", "No se puede escribir en esa carpeta."),
    (r"ffmpeg|ffprobe", "Falló la conversión con FFmpeg."),
]


def friendly_error(text: str) -> str:
    for pattern, message in ERROR_HINTS:
        if re.search(pattern, text, re.I):
            return message
    first = next((line for line in text.splitlines() if "ERROR" in line), text.strip().splitlines()[-1] if text.strip() else "")
    first = re.sub(r"^.*?ERROR:\s*(\[[^\]]+\]\s*)?([\w-]+:\s*)?", "", first).strip()
    return (first[:220] or "La descarga falló.")


class Job:
    def __init__(self, url: str, options: dict) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.url = url
        self.kind = options["kind"]
        self.audio_format = options["audio_format"]
        self.audio_quality = options["audio_quality"]
        self.video_quality = options["video_quality"]
        self.folder = options["folder"]
        self.playlist = options["playlist"]
        self.status = "queued"  # queued, running, converting, done, error, cancelled
        self.title = ""
        self.thumbnail = ""
        self.percent = 0.0
        self.speed = ""
        self.eta = ""
        self.item = 0  # en listas: video actual / total
        self.items = 0
        self.files: list[str] = []
        self.error = ""
        self.created = time.time()
        self.process: subprocess.Popen | None = None
        self.cancel_requested = False
        self.log_tail: list[str] = []

    def public(self) -> dict:
        return {
            "id": self.id, "url": self.url, "kind": self.kind,
            "format": self.audio_format.upper() if self.kind == "audio" else "MP4",
            "quality": (f"{self.audio_quality} kbps" if self.audio_format == "mp3" else "") if self.kind == "audio"
            else ("Máxima" if self.video_quality == "best" else f"{self.video_quality}p"),
            "folder": self.folder, "playlist": self.playlist, "status": self.status,
            "title": self.title, "thumbnail": self.thumbnail, "percent": round(self.percent, 1),
            "speed": self.speed, "eta": self.eta, "item": self.item, "items": self.items,
            "files": len(self.files), "error": self.error,
            "media": MEDIA.token_for(self.files[-1]) if self.status == "done" and self.files and not self.playlist else "",
        }

    # ---------- comando ----------
    def command(self) -> list[str]:
        path = ytdlp_path()
        if not path:
            raise RuntimeError("No se encontró el motor de descargas (yt-dlp).")
        name = "%(playlist_index)02d - %(title)s.%(ext)s" if self.playlist else "%(title)s.%(ext)s"
        output = ("%(playlist_title,playlist|" + ("Playlist" if current_language() == "en" else "Lista") + ")s/" + name) if self.playlist else name
        args = [
            path, "--newline", "--no-colors", "--progress", "--ignore-config", "--encoding", "utf-8",
            "--windows-filenames", "--no-mtime", "--concurrent-fragments", "4",
            "-P", self.folder, "-o", output,
            "--print", "before_dl:ECT-START\t%(playlist_index|0)s\t%(n_entries|0)s\t%(title)s\t%(thumbnail|)s",
            "--print", "after_move:ECT-FILE\t%(filepath)s",
            "--progress-template", "download:ECT-PROG\t%(progress._percent_str)s\t%(progress._speed_str)s\t%(progress._eta_str)s",
            "--progress-template", "postprocess:ECT-POST\t%(progress.postprocessor)s",
            "--embed-metadata",
        ]
        args.append("--yes-playlist" if self.playlist else "--no-playlist")
        if FFMPEG:
            # La carpeta, para que yt-dlp también encuentre ffprobe.
            args += ["--ffmpeg-location", str(Path(FFMPEG).parent)]
        if DENO:
            args += ["--js-runtimes", f"deno:{DENO}"]
        if self.kind == "audio":
            args += ["-x", "--audio-format", self.audio_format, "--embed-thumbnail"]
            if self.audio_format == "mp3":
                args += ["--audio-quality", f"{self.audio_quality}K"]
            else:
                args += ["--audio-quality", "0"]
            if self.audio_format == "wav":
                args.remove("--embed-thumbnail")
        else:
            # MP4 que se reproduce en cualquier lado: H.264 + AAC hasta 1080p.
            # Más de 1080p en YouTube solo existe en VP9/AV1 (sigue siendo .mp4).
            height = None if self.video_quality == "best" else int(self.video_quality)
            if height and height <= 1080:
                sort = f"res:{height},vcodec:h264,acodec:aac"
            elif height:
                sort = f"res:{height},acodec:aac"
            else:
                sort = "res,acodec:aac"
            args += ["-S", sort, "--merge-output-format", "mp4", "--remux-video", "mp4", "--embed-thumbnail"]
        args += ["--", self.url]
        return args


class Downloads:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.order: list[str] = []
        self.lock = threading.Lock()
        self.wakeup = threading.Condition(self.lock)
        for _ in range(MAX_PARALLEL):
            threading.Thread(target=self._worker, daemon=True).start()

    def add(self, urls: list[str], options: dict) -> list[Job]:
        created = []
        with self.lock:
            for url in urls:
                job = Job(url, options)
                self.jobs[job.id] = job
                self.order.append(job.id)
                created.append(job)
            self.wakeup.notify_all()
        return created

    def list(self) -> list[dict]:
        with self.lock:
            return [self.jobs[j].public() for j in reversed(self.order)]

    def active(self) -> bool:
        with self.lock:
            return any(job.status in ("queued", "running", "converting") for job in self.jobs.values())

    def get(self, job_id: str) -> Job | None:
        with self.lock:
            return self.jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self.get(job_id)
        if not job or job.status not in ("queued", "running", "converting"):
            return False
        job.cancel_requested = True
        if job.status == "queued":
            job.status = "cancelled"
        elif job.process:
            _kill_tree(job.process)
        return True

    def retry(self, job_id: str) -> Job | None:
        job = self.get(job_id)
        if not job or job.status not in ("error", "cancelled"):
            return None
        options = {"kind": job.kind, "audio_format": job.audio_format, "audio_quality": job.audio_quality,
                   "video_quality": job.video_quality, "folder": job.folder, "playlist": job.playlist}
        self.remove(job_id)
        new = self.add([job.url], options)[0]
        new.title, new.thumbnail = job.title, job.thumbnail
        return new

    def remove(self, job_id: str) -> None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job and job.status not in ("queued", "running", "converting"):
                self.jobs.pop(job_id, None)
                self.order.remove(job_id)

    def clear_finished(self) -> None:
        with self.lock:
            for job_id in list(self.order):
                if self.jobs[job_id].status in ("done", "error", "cancelled"):
                    self.jobs.pop(job_id)
                    self.order.remove(job_id)

    # ---------- trabajo ----------
    def _next(self) -> Job:
        with self.lock:
            while True:
                for job_id in self.order:
                    job = self.jobs[job_id]
                    if job.status == "queued":
                        job.status = "running"
                        return job
                self.wakeup.wait()

    def _worker(self) -> None:
        while True:
            job = self._next()
            try:
                self._run(job)
            except Exception as exc:  # noqa: BLE001 — que un error no tumbe el hilo
                job.status, job.error = "error", str(exc) or "La descarga falló."
                log(f"[{job.id}] error inesperado: {exc!r}")

    def _run(self, job: Job) -> None:
        Path(job.folder).mkdir(parents=True, exist_ok=True)
        command = job.command()
        log(f"[{job.id}] {job.kind} {job.url}")
        job.process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8",
            errors="replace", bufsize=1, creationflags=_no_window_flags(), cwd=job.folder,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        )
        assert job.process.stdout is not None
        for raw in job.process.stdout:
            self._line(job, raw.rstrip("\r\n"))
        code = job.process.wait()
        job.process = None
        if job.cancel_requested:
            job.status = "cancelled"
            _remove_partials(job)
        elif code == 0 or (job.files and job.playlist):
            job.status, job.percent = "done", 100.0
            if code != 0:
                job.error = "Algunos videos de la lista no se pudieron bajar."
        else:
            job.status = "error"
            job.error = friendly_error("\n".join(job.log_tail))
            _remove_partials(job)
        log(f"[{job.id}] terminó: {job.status} {job.error}".rstrip())

    def _line(self, job: Job, line: str) -> None:
        if line.startswith("ECT-PROG\t"):
            _, percent, speed, eta = (line.split("\t") + ["", "", ""])[:4]
            with contextlib.suppress(ValueError):
                job.percent = float(percent.strip().rstrip("%"))
            job.speed = "" if "Unknown" in speed or speed.strip() == "NA" else speed.strip()
            job.eta = "" if "Unknown" in eta or eta.strip() == "NA" else eta.strip()
            job.status = "running"
        elif line.startswith("ECT-START\t"):
            parts = (line.split("\t") + ["", "", "", ""])[:5]
            with contextlib.suppress(ValueError):
                job.item = int(parts[1] or 0)
                job.items = int(parts[2] or 0)
            job.title = parts[3] if parts[3] != "NA" else job.title
            job.thumbnail = parts[4] if parts[4].startswith("http") else job.thumbnail
            job.percent, job.status = 0.0, "running"
        elif line.startswith("ECT-POST\t"):
            job.status = "converting"
        elif line.startswith("ECT-FILE\t"):
            job.files.append(line.split("\t", 1)[1])
        elif line.strip():
            job.log_tail = (job.log_tail + [line])[-40:]
            if "ERROR" in line or "WARNING" in line:
                log(f"[{job.id}] {line[:300]}")


def _kill_tree(process: subprocess.Popen) -> None:
    """yt-dlp abre FFmpeg/Deno: cerrar todo el árbol de procesos."""
    with contextlib.suppress(OSError):
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True,
                           creationflags=_no_window_flags(), timeout=15)
        else:
            process.send_signal(signal.SIGTERM)


def _remove_partials(job: Job) -> None:
    """Borrar los pedazos (.part, .ytdl) que deja una descarga cancelada o fallida."""
    if not job.title:
        return
    folder = Path(job.folder)
    safe = re.sub(r'[\\/:*?"<>|]', "", job.title)[:40]
    with contextlib.suppress(OSError):
        for path in folder.rglob("*"):
            if path.suffix in (".part", ".ytdl") or ".part-Frag" in path.name or path.name.endswith(".temp"):
                if safe and safe[:15] in re.sub(r'[\\/:*?"<>|]', "", path.name):
                    with contextlib.suppress(OSError):
                        path.unlink()


DOWNLOADS = Downloads()


# ---------------------------------------------------------------------------
# Editor: recortar audio o video (inicio y final) con FFmpeg
# ---------------------------------------------------------------------------
AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac"}
VIDEO_EXTS = {".mp4", ".m4v", ".mov", ".webm", ".mkv"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MEDIA_TYPES = {".gif": "image/gif", ".apng": "image/apng", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".bmp": "image/bmp",".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".wav": "audio/wav",
               ".ogg": "audio/ogg", ".opus": "audio/ogg", ".flac": "audio/flac", ".mp4": "video/mp4",
               ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mkv": "video/x-matroska"}


class MediaRegistry:
    """Solo se sirven archivos que EC-Tube bajó o que el usuario eligió."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.by_token: dict[str, Path] = {}
        self.by_path: dict[str, str] = {}

    def token_for(self, path: str | Path) -> str:
        key = str(Path(path))
        with self.lock:
            token = self.by_path.get(key)
            if not token:
                token = uuid.uuid4().hex
                self.by_path[key], self.by_token[token] = token, Path(key)
            return token

    def path(self, token: str) -> Path | None:
        with self.lock:
            return self.by_token.get(token)


MEDIA = MediaRegistry()


def media_info(path: Path) -> dict:
    ext = path.suffix.lower()
    return {"token": MEDIA.token_for(path), "name": path.name, "folder": str(path.parent),
            "kind": "video" if ext in VIDEO_EXTS else "audio", "type": MEDIA_TYPES.get(ext, ""),
            "size": path.stat().st_size if path.exists() else 0}


def edited_folder_for(source: Path) -> Path:
    """Los recortes van a la carpeta de editados (audio o video), aparte de las descargas."""
    kind = "video" if source.suffix.lower() in VIDEO_EXTS else "audio"
    folder = Path(CONFIG[f"{kind}_edited_folder"])
    folder.mkdir(parents=True, exist_ok=True)
    return folder


TRIM_WORDS = {"original": ("recorte", "trim"), "music": ("música", "music"), "voice": ("voz", "vocals")}


def _unique_trim_path(source: Path, mode: str = "original") -> Path:
    folder = edited_folder_for(source)
    for n in range(1, 1000):
        word = TRIM_WORDS.get(mode, TRIM_WORDS["original"])[1 if current_language() == "en" else 0]
        label = f" ({word})" if n == 1 else f" ({word} {n})"
        candidate = folder / f"{source.stem}{label}{source.suffix}"
        if not candidate.exists():
            return candidate
    raise RuntimeError("Hay demasiados recortes de este archivo.")


SEPARATOR = {"mdx": None, "lock": threading.Lock()}


def _separator(progress, cancelled):
    """El separador se carga una vez y se reutiliza (el modelo se baja la primera vez)."""
    from ectube_separate import MDX, ensure_model

    with SEPARATOR["lock"]:
        if SEPARATOR["mdx"] is None:
            model = ensure_model(HOME / "models", progress=progress, cancelled=cancelled)
            SEPARATOR["mdx"] = MDX(str(model))
            log("Separador listo en: " + ", ".join(SEPARATOR["mdx"].providers))
        return SEPARATOR["mdx"]


AUDIO_CODECS = {".mp3": ["-c:a", "libmp3lame", "-b:a", "320k"], ".m4a": ["-c:a", "aac", "-b:a", "256k"],
                ".aac": ["-c:a", "aac", "-b:a", "256k"], ".wav": ["-c:a", "pcm_s16le"],
                ".ogg": ["-c:a", "libvorbis", "-q:a", "7"], ".opus": ["-c:a", "libopus", "-b:a", "192k"],
                ".flac": ["-c:a", "flac"]}


class TrimJob:
    def __init__(self, source: Path, start: float, end: float, mode: str = "original") -> None:
        self.id = uuid.uuid4().hex[:12]
        self.source, self.start, self.end = source, start, end
        self.mode = mode if mode in TRIM_WORDS else "original"
        self.output = _unique_trim_path(source, self.mode)
        self.phase = ""
        self.status, self.percent, self.error = "running", 0.0, ""
        self.process: subprocess.Popen | None = None
        self.cancelled = False

    def command(self) -> list[str]:
        if not FFMPEG:
            raise RuntimeError("No se encontró FFmpeg.")
        ext = self.source.suffix.lower()
        args = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-ss", f"{self.start:.3f}", "-i", str(self.source),
                "-t", f"{self.end - self.start:.3f}", "-map_metadata", "0"]
        if ext in VIDEO_EXTS:
            # Recodificar para cortar exacto (copiar cortaría en el cuadro clave más cercano).
            args += ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                     "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
            if ext in (".mp4", ".m4v", ".mov"):
                args += ["-movflags", "+faststart"]
        elif ext == ".wav":
            args += ["-map", "0:a:0", "-c", "copy"]
        else:
            # Audio comprimido: copiar sin recomprimir (exacto a ~0.03 s) y conservar la portada.
            args += ["-map", "0", "-c", "copy"]
        return args + ["-progress", "pipe:1", "-nostats", str(self.output)]

    def _separate(self) -> None:
        """Recortar + separar: sacar el audio, quitar voz o música y volver a guardar (con el video si era video)."""
        import numpy as np

        if not FFMPEG:
            raise RuntimeError("No se encontró FFmpeg.")
        duration = max(0.1, self.end - self.start)
        if duration > 30 * 60:
            raise RuntimeError("Para separar voz o música, el tramo debe durar máximo 30 minutos.")
        span = ["-ss", f"{self.start:.3f}", "-i", str(self.source), "-t", f"{duration:.3f}"]
        self.phase = "audio"
        self.process = subprocess.Popen([FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", *span, "-vn",
                                         "-f", "f32le", "-ac", "2", "-ar", "44100", "pipe:1"],
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=_no_window_flags())
        raw, errors = self.process.communicate()
        if self.cancelled:
            return
        if self.process.returncode != 0 or not raw:
            raise RuntimeError(friendly_error(errors.decode("utf-8", "replace")) if errors else "No se pudo leer el audio.")
        mix = np.frombuffer(raw, dtype="<f4").reshape(-1, 2).T.copy()
        self.percent = 3.0

        def model_progress(fraction: float) -> None:
            self.phase, self.percent = "model", 3 + fraction * 7

        def separate_progress(fraction: float) -> None:
            self.phase, self.percent = "separate", 10 + fraction * 82

        mdx = _separator(model_progress, lambda: self.cancelled)
        self.phase = "separate"
        vocals = mdx.vocals(mix, progress=separate_progress, cancelled=lambda: self.cancelled)
        if getattr(self, "save_guide", False):
            # Karaoke «desde la canción con voz»: guardar de una vez la voz guía (no separar dos veces).
            with contextlib.suppress(Exception):
                from ectube_karaoke import voice_envelope

                cache = KARAOKE_DIR / "guides" / f"{_guide_key(self.source)}.npz"
                cache.parent.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(cache, env=voice_envelope(vocals.mean(axis=0)), mix=voice_envelope(mix.mean(axis=0)))
        result = vocals if self.mode == "voice" else mix - vocals
        pcm = np.ascontiguousarray(np.clip(result, -1, 1).T, dtype="<f4").tobytes()
        self.phase, self.percent = "save", 93.0
        ext = self.source.suffix.lower()
        args = [FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-y"]
        if ext in VIDEO_EXTS:
            args += [*span, "-f", "f32le", "-ar", "44100", "-ac", "2", "-i", "pipe:0", "-map", "0:v:0", "-map", "1:a:0",
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k"]
            if ext in (".mp4", ".m4v", ".mov"):
                args += ["-movflags", "+faststart"]
        else:
            args += ["-f", "f32le", "-ar", "44100", "-ac", "2", "-i", "pipe:0",
                     *AUDIO_CODECS.get(ext, ["-c:a", "libmp3lame", "-b:a", "320k"])]
        self.process = subprocess.Popen(args + [str(self.output)], stdin=subprocess.PIPE, stderr=subprocess.PIPE,
                                        creationflags=_no_window_flags())
        _, errors = self.process.communicate(pcm)
        if self.cancelled:
            return
        if self.process.returncode != 0 or not self.output.exists():
            raise RuntimeError(friendly_error(errors.decode("utf-8", "replace")) if errors else "No se pudo guardar.")

    def run(self) -> None:
        if self.mode != "original":
            try:
                log(f"[separar {self.id}] {self.source.name} {self.start:.2f}–{self.end:.2f} → {self.mode}")
                self._separate()
                self.status = "cancelled" if self.cancelled else "done"
                if self.status == "done":
                    self.percent = 100.0
            except InterruptedError:
                self.status = "cancelled"
            except Exception as exc:  # noqa: BLE001
                self.status, self.error = "error", str(exc)
                log(f"[separar {self.id}] error: {exc}")
            if self.status != "done":
                with contextlib.suppress(OSError):
                    self.output.unlink()
            return
        duration = max(0.1, self.end - self.start)
        try:
            log(f"[recorte {self.id}] {self.source.name} {self.start:.2f}–{self.end:.2f}")
            self.process = subprocess.Popen(self.command(), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                            encoding="utf-8", errors="replace", creationflags=_no_window_flags())
            errors: list[str] = []
            threading.Thread(target=lambda: errors.extend(self.process.stderr.readlines()), daemon=True).start()  # type: ignore[union-attr]
            for line in self.process.stdout:  # type: ignore[union-attr]
                if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                    with contextlib.suppress(ValueError):
                        self.percent = min(99.0, int(line.split("=", 1)[1]) / 1e6 / duration * 100)
            code = self.process.wait()
            if self.cancelled:
                self.status = "cancelled"
            elif code == 0 and self.output.exists():
                self.status, self.percent = "done", 100.0
            else:
                self.status = "error"
                self.error = friendly_error("".join(errors[-20:])) if errors else "No se pudo recortar."
                log(f"[recorte {self.id}] error: {''.join(errors[-5:])[:400]}")
        except Exception as exc:  # noqa: BLE001
            self.status, self.error = "error", str(exc)
        if self.status != "done":
            with contextlib.suppress(OSError):
                self.output.unlink()

    def public(self) -> dict:
        data = {"id": self.id, "status": self.status, "percent": round(self.percent, 1), "error": self.error,
                "output": self.output.name, "mode": self.mode, "phase": self.phase}
        if self.status == "done":
            data["media"] = media_info(self.output)
        return data


TRIMS: dict[str, TrimJob] = {}


# ---------------------------------------------------------------------------
# Edición: onda del audio y unir fragmentos de una o varias fuentes (audio con audio, video con video)
# ---------------------------------------------------------------------------
PEAKS_CACHE: dict[tuple, dict] = {}
PROBE_CACHE: dict[tuple, dict] = {}
EDIT_TMP = HOME / "edicion-tmp"


def probe(path: Path) -> dict:
    """Duración, si tiene audio y el tamaño del video (leído de lo que dice FFmpeg)."""
    key = (str(path), path.stat().st_mtime)
    if key in PROBE_CACHE:
        return PROBE_CACHE[key]
    info = {"duration": 0.0, "audio": False, "width": 0, "height": 0, "codec": "", "fps": 0.0, "hdr": False, "deep": False}
    if FFMPEG:
        out = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-i", str(path)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace", creationflags=_no_window_flags()).stderr
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", out)
        if m:
            info["duration"] = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3])
        info["audio"] = bool(re.search(r"Stream #\S+.*?: Audio:", out))
        v = re.search(r"Stream #\S+.*?: Video:(?!.*attached pic).*?(\d{2,5})x(\d{2,5})", out)
        if v:
            info["width"], info["height"] = int(v[1]), int(v[2])
            line = next((x for x in out.splitlines() if ": Video:" in x and "attached pic" not in x), "")
            c = re.search(r"Video:\s*(\w+)", line)
            info["codec"] = c.group(1).lower() if c else ""
            f = re.search(r"([\d.]+)\s*fps", line)
            info["fps"] = float(f.group(1)) if f else 0.0
            info["hdr"] = bool(re.search(r"bt2020|arib-std-b67|smpte2084", line))
            info["deep"] = bool(re.search(r"p1[02]le|p1[02]be", line))
    PROBE_CACHE[key] = info
    return info


# ---------- Efectos de sonido (van encima del sonido de la edición) ----------
FX_BANK = WEB_ROOT / "efectos"          # 63 sonidos de fábrica (CC0, los mismos de EC-Tok)
FX_MINE = HOME / "mis-efectos"          # los que agrega cada quien (su responsabilidad)
FX_MAX_SECONDS = 600
FX_LOCK = threading.Lock()


def _fx_index() -> list[dict]:
    with contextlib.suppress(OSError, ValueError):
        data = json.loads((FX_MINE / "lista.json").read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict) and (FX_MINE / str(x.get("file", ""))).is_file()]
    return []


def effects_public() -> dict:
    bank = []
    with contextlib.suppress(OSError, ValueError):
        for item in json.loads((FX_BANK / "efectos.json").read_text(encoding="utf-8")):
            bank.append({"id": "b/" + item["file"], "name": item["name"], "cat": item["cat"], "seconds": item["seconds"],
                         "url": "/efectos/" + item["file"]})
    mine = [{"id": "m/" + x["file"], "name": x.get("name") or x["file"], "cat": "mine", "seconds": x.get("seconds", 0),
             "url": "/mis-efectos/" + x["file"]} for x in _fx_index()]
    return {"bank": bank, "mine": mine}


def effect_path(effect_id: str) -> Path | None:
    kind, _, name = str(effect_id).partition("/")
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    folder = {"b": FX_BANK, "m": FX_MINE}.get(kind)
    path = folder / name if folder else None
    return path if path and path.is_file() and path.suffix.lower() == ".mp3" else None


def effects_add(paths: list[str]) -> dict:
    """Copiar sonidos de la PC a «Mis sonidos» (se guardan como MP3, solo el audio)."""
    if not FFMPEG:
        raise RuntimeError("No se encontró FFmpeg.")
    FX_MINE.mkdir(parents=True, exist_ok=True)
    added, errors = 0, []
    for raw in paths:
        src = Path(raw)
        info = probe(src) if src.is_file() else {"audio": False, "duration": 0}
        if not info["audio"]:
            errors.append(f"«{src.name}» no tiene audio.")
            continue
        if info["duration"] > FX_MAX_SECONDS:
            errors.append(f"«{src.name}» dura más de 10 minutos.")
            continue
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", src.stem).strip(" .")[:80] or "sonido"
        with FX_LOCK:
            name = next(f"{stem}{'' if n == 1 else f' {n}'}.mp3" for n in range(1, 10000)
                        if not (FX_MINE / f"{stem}{'' if n == 1 else f' {n}'}.mp3").exists())
            (FX_MINE / name).touch()
        result = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", str(src), "-vn",
                                 "-ac", "2", "-ar", "48000", "-c:a", "libmp3lame", "-b:a", "192k", str(FX_MINE / name)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                creationflags=_no_window_flags())
        if result.returncode != 0:
            with contextlib.suppress(OSError):
                (FX_MINE / name).unlink()
            errors.append(f"«{src.name}» no se pudo leer.")
            continue
        with FX_LOCK:
            index = _fx_index()
            index.append({"file": name, "name": src.stem, "seconds": round(probe(FX_MINE / name)["duration"], 2)})
            (FX_MINE / "lista.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
        added += 1
    return {"added": added, "errors": errors}


def effects_remove(effect_id: str) -> None:
    path = effect_path(effect_id)
    if not path or path.parent != FX_MINE:
        raise ValueError("Ese sonido no es de «Mis sonidos».")
    with FX_LOCK:
        index = [x for x in _fx_index() if x.get("file") != path.name]
        (FX_MINE / "lista.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
        path.unlink()


# ---------- Animaciones encima del video (banco de EC-Tok, cintillos y las tuyas) ----------
ANIM_BASE = WEB_ROOT / "anim"           # las básicas que trae EC-Tok (también vienen en el instalador de EC-Tube)
ANIM_BANK = HOME / "banco"              # el banco completo: se baja de los releases «banco-N» del repo de EC-Tok
ANIM_MINE = HOME / "mis-animaciones"    # las de cada quien
BANK_RELEASES = "https://api.github.com/repos/cesarmugica/EC-Tok/releases?per_page=40"
BANK = {"state": "idle", "percent": 0.0, "error": "", "latest": 0, "url": "", "size": 0, "checked": False, "checked_at": 0.0}
ANIM_LOCK = threading.Lock()
SCENES: dict = {}


def reload_scenes() -> None:
    from ectube_overlay import load_scenes

    global SCENES
    SCENES = load_scenes(ANIM_BASE, ANIM_BANK)


def bank_check() -> None:
    import urllib.request

    try:
        request = urllib.request.Request(BANK_RELEASES, headers={"User-Agent": f"EC-Tube/{APP_VERSION}", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            releases = json.loads(response.read())
        best = (0, "", 0)
        for rel in releases:
            tag = rel.get("tag_name") or ""
            if not tag.startswith("banco-") or rel.get("draft") or not tag[6:].isdigit():
                continue
            zipa = next((a for a in rel.get("assets", []) if a["name"].lower().endswith(".zip")), None)
            if zipa and int(tag[6:]) > best[0]:
                best = (int(tag[6:]), zipa["browser_download_url"], int(zipa.get("size") or 0))
        BANK.update(latest=best[0], url=best[1], size=best[2], checked=True, checked_at=time.time(), error="")
    except Exception as exc:  # noqa: BLE001
        BANK.update(checked=True, checked_at=time.time(), error="No se pudo buscar el banco (¿sin internet?).")
        log(f"Banco de animaciones (buscar): {exc}")


def bank_installed() -> int:
    with contextlib.suppress(OSError, ValueError):
        return int((ANIM_BANK / "version.txt").read_text(encoding="utf-8").strip())
    return 0


def bank_status() -> dict:
    from ectube_overlay import ANIM_EXTS as EXTS

    if BANK["state"] not in ("downloading", "installing") and time.time() - BANK["checked_at"] > 3600:
        BANK["checked_at"] = time.time()
        threading.Thread(target=bank_check, daemon=True).start()
    count = sum(1 for p in ANIM_BANK.glob("*") if p.suffix.lower() in EXTS) if ANIM_BANK.is_dir() else 0
    return {**BANK, "installed": bank_installed(), "count": count, "published": bool(BANK["url"]),
            "dismissed": int(CONFIG.get("bank_dismissed") or 0)}


def _bank_download() -> None:
    import urllib.request
    import zipfile

    from ectube_overlay import ANIM_EXTS as EXTS

    BANK.update(state="downloading", percent=0.0, error="")
    tmp = HOME / "banco-descarga.zip"
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        if not BANK["url"]:
            bank_check()
        if not BANK["url"]:
            raise RuntimeError("todavía no hay banco publicado")
        version = BANK["latest"]
        request = urllib.request.Request(BANK["url"], headers={"User-Agent": f"EC-Tube/{APP_VERSION}"})
        with urllib.request.urlopen(request, timeout=60) as response, tmp.open("wb") as out:  # noqa: S310
            total = int(response.headers.get("Content-Length") or 0)
            got = 0
            while chunk := response.read(256 * 1024):
                out.write(chunk)
                got += len(chunk)
                BANK["percent"] = round(got * 100 / total, 1) if total else 0.0
        BANK.update(state="installing")
        new = HOME / "banco-nuevo"
        shutil.rmtree(new, ignore_errors=True)
        with zipfile.ZipFile(tmp) as zf:
            for info in zf.infolist():
                name = Path(info.filename).name  # sin carpetas (y sin «../»)
                if not name or info.is_dir() or (Path(name).suffix.lower() not in EXTS and name not in ("escenas.json", "version.txt")):
                    continue
                new.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, (new / name).open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        (new / "version.txt").write_text(str(version), encoding="utf-8")
        with ANIM_LOCK:
            shutil.rmtree(ANIM_BANK, ignore_errors=True)
            new.replace(ANIM_BANK)
            reload_scenes()
        BANK.update(state="done", percent=100.0)
        log(f"Banco de animaciones {version} instalado")
    except Exception as exc:  # noqa: BLE001
        BANK.update(state="error", error="No se pudo descargar el banco (¿sin internet?)." if BANK["url"] else "Todavía no hay banco publicado.")
        log(f"Banco de animaciones: {exc}")
    finally:
        with contextlib.suppress(OSError):
            tmp.unlink()


def bank_download() -> None:
    if BANK["state"] in ("downloading", "installing"):
        return
    threading.Thread(target=_bank_download, daemon=True).start()


def anims_public() -> dict:
    from ectube_overlay import ANIM_EXTS as EXTS, anim_label

    items = []
    for folder, prefix, url in ((ANIM_BASE, "a", "/anim/"), (ANIM_BANK, "k", "/banco/"), (ANIM_MINE, "u", "/mis-animaciones/")):
        if not folder.is_dir():
            continue
        for path in sorted(folder.iterdir(), key=lambda x: x.name.lower()):
            if not path.is_file() or path.suffix.lower() not in EXTS or "-parte-" in path.name:
                continue
            sc = SCENES.get(path.name) if prefix != "u" else None
            box = None
            if sc and sc.get("track"):
                tr = sc["track"]
                box = [tr[0][0], tr[0][1], min(b[2] for b in tr), min(b[3] for b in tr), tr[0][4] if len(tr[0]) > 4 else 0]
            elif sc and sc.get("sign"):
                x, y, w, h = sc["sign"][:4]
                box = [x + w / 2, y + h / 2, w, h, 0]
            group = "mine" if prefix == "u" else "text" if box else "fx"
            items.append({"id": f"{prefix}/{path.name}", "name": anim_label(path.stem), "url": url + quote(path.name),
                          "video": path.suffix.lower() in (".webm", ".mp4"), "group": group, "text": bool(box), "sign": box,
                          "ratio": float(sc.get("ratio") or 0) if sc else 0,
                          # para que el texto siga al letrero en el lienzo (los personajes en video)
                          "track": sc.get("track") if sc and sc.get("video") else None,
                          "fps": float((sc.get("video") or {}).get("fps") or 16) if sc and sc.get("video") else 0})
    return {"items": items, "bank": bank_status()}


def anim_path(anim_id: str) -> Path | None:
    from ectube_overlay import ANIM_EXTS as EXTS

    kind, _, name = str(anim_id).partition("/")
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None
    folder = {"a": ANIM_BASE, "k": ANIM_BANK, "u": ANIM_MINE}.get(kind)
    path = folder / name if folder else None
    return path if path and path.is_file() and path.suffix.lower() in EXTS else None


def anims_add(paths: list[str]) -> dict:
    """Copiar animaciones de la PC a «Mis animaciones». Los videos que el navegador no abre se pasan a WebM."""
    from ectube_overlay import ANIM_EXTS as EXTS, IMPORT_EXTS

    ANIM_MINE.mkdir(parents=True, exist_ok=True)
    added, errors = 0, []
    for raw in paths:
        src = Path(raw)
        ext = src.suffix.lower()
        if not src.is_file() or ext not in IMPORT_EXTS:
            errors.append(f"«{src.name}» no es una animación compatible.")
            continue
        stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", src.stem).strip(" .")[:80] or "animacion"
        out_ext = ext if ext in EXTS else ".png" if ext in (".jpg", ".jpeg") else ".webm"
        with ANIM_LOCK:
            name = next(f"{stem}{'' if n == 1 else f' {n}'}{out_ext}" for n in range(1, 10000)
                        if not (ANIM_MINE / f"{stem}{'' if n == 1 else f' {n}'}{out_ext}").exists())
        target = ANIM_MINE / name
        try:
            if ext in EXTS:
                shutil.copy2(src, target)
            elif out_ext == ".png":
                from PIL import Image

                Image.open(src).convert("RGBA").save(target)
            else:
                if not FFMPEG:
                    raise RuntimeError
                if probe(src)["duration"] > 120:
                    errors.append(f"«{src.name}» dura más de 2 minutos.")
                    continue
                result = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-i", str(src), "-an",
                                         "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "32", "-deadline", "realtime",
                                         "-cpu-used", "8", str(target)], capture_output=True, creationflags=_no_window_flags())
                if result.returncode != 0:
                    raise RuntimeError
            added += 1
        except Exception:  # noqa: BLE001
            with contextlib.suppress(OSError):
                target.unlink()
            errors.append(f"«{src.name}» no se pudo leer.")
    return {"added": added, "errors": errors}


def anims_remove(anim_id: str) -> None:
    path = anim_path(anim_id)
    if not path or path.parent != ANIM_MINE:
        raise ValueError("Esa animación no es de «Mis animaciones».")
    path.unlink()


# ---------- Videos del iPhone (HEVC / HDR / 10 bits): una copia compatible para poder verlos y editarlos ----------
COMPAT_DIR = HOME / "compatibles"
BROWSER_CODECS = {"h264", "vp8", "vp9", "av1"}
TONEMAP = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
           "zscale=t=bt709:m=bt709:r=tv,format=yuv420p")


def needs_compat(path: Path) -> bool:
    if path.suffix.lower() not in VIDEO_EXTS or not path.is_file():
        return False
    info = probe(path)
    return bool(info["codec"]) and (info["codec"] not in BROWSER_CODECS or info["hdr"] or info["deep"])


def compat_path(path: Path) -> Path:
    stat = path.stat()
    key = hashlib.sha1(f"{path}|{stat.st_size}|{int(stat.st_mtime)}".encode()).hexdigest()[:16]
    return COMPAT_DIR / key / f"{path.stem}.mp4"


class CompatJob:
    """Pasar un video HEVC/HDR (como los del iPhone) a H.264 normal: mismo tamaño y fps, colores corregidos."""

    def __init__(self, source: Path) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.source, self.output = source, compat_path(source)
        self.status, self.percent, self.error = "running", 0.0, ""
        self.process: subprocess.Popen | None = None

    def _run(self, vf: str, tmp: Path) -> tuple[int, list[str]]:
        info = probe(self.source)
        fps = info["fps"]
        if fps > 61:  # cámara lenta de 120/240 fps: se queda en 60
            vf += ",fps=60"
        args = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-i", str(self.source), "-map", "0:v:0", "-map", "0:a:0?",
                "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart", "-progress", "pipe:1", "-nostats", str(tmp)]
        self.process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                        errors="replace", creationflags=_no_window_flags())
        errors: list[str] = []
        threading.Thread(target=lambda: errors.extend(self.process.stderr.readlines()), daemon=True).start()  # type: ignore[union-attr]
        duration = max(0.5, info["duration"])
        for line in self.process.stdout:  # type: ignore[union-attr]
            if line.startswith(("out_time_us=", "out_time_ms=")):
                with contextlib.suppress(ValueError):
                    self.percent = min(99.0, int(line.split("=", 1)[1]) / 1e6 / duration * 100)
        return self.process.wait(), errors

    def run(self) -> None:
        tmp = self.output.with_suffix(".tmp.mp4")
        try:
            if not FFMPEG:
                raise RuntimeError("No se encontró FFmpeg.")
            self.output.parent.mkdir(parents=True, exist_ok=True)
            hdr = probe(self.source)["hdr"]
            log(f"[compatible {self.id}] {self.source.name} ({probe(self.source)['codec']}{', HDR' if hdr else ''})")
            code, errors = self._run(TONEMAP if hdr else "format=yuv420p", tmp)
            if code != 0 and hdr:  # si este FFmpeg no trae zscale: sin ajustar el brillo (mejor eso que nada)
                log(f"[compatible {self.id}] sin tonemap: {''.join(errors[-3:])[:300]}")
                self.percent = 0.0
                code, errors = self._run("format=yuv420p", tmp)
            if code != 0 or not tmp.exists():
                raise RuntimeError(friendly_error("".join(errors[-20:])) if errors else "No se pudo preparar el video.")
            tmp.replace(self.output)
            self.status, self.percent = "done", 100.0
        except Exception as exc:  # noqa: BLE001
            self.status, self.error = "error", str(exc)
            log(f"[compatible {self.id}] error: {exc}")
            with contextlib.suppress(OSError):
                tmp.unlink()

    def public(self) -> dict:
        return {"id": self.id, "status": self.status, "percent": round(self.percent, 1), "error": self.error,
                "media": media_info(self.output) if self.status == "done" else None}


COMPAT_JOBS: dict[str, CompatJob] = {}


def clean_compat(days: int = 30) -> None:
    """Las copias compatibles que no se han usado en un mes se borran solas (el video original no se toca)."""
    if not COMPAT_DIR.is_dir():
        return
    limit = time.time() - days * 86400
    for folder in COMPAT_DIR.iterdir():
        with contextlib.suppress(OSError):
            newest = max((p.stat().st_atime for p in folder.iterdir()), default=0)
            if newest < limit:
                shutil.rmtree(folder, ignore_errors=True)


def waveform(path: Path, buckets: int = 1600) -> dict:
    """La onda: el nivel más alto de cada pedacito (0 a 1), para ver dónde hay silencios o baja el volumen."""
    import numpy as np

    buckets = max(100, min(int(buckets), 6000))
    key = (str(path), path.stat().st_mtime, buckets)
    if key in PEAKS_CACHE:
        return PEAKS_CACHE[key]
    if not FFMPEG:
        raise RuntimeError("No se encontró FFmpeg.")
    rate = 4000
    proc = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1",
                           "-ar", str(rate), "-f", "s16le", "pipe:1"], capture_output=True, creationflags=_no_window_flags())
    samples = np.frombuffer(proc.stdout, dtype="<i2").astype(np.float32) / 32768.0 if proc.stdout else np.zeros(0, np.float32)
    duration = len(samples) / rate or probe(path)["duration"]
    if len(samples):
        size = max(1, int(np.ceil(len(samples) / buckets)))
        count = int(np.ceil(len(samples) / size))  # pedacitos que cubren exactamente toda la canción
        padded = np.pad(np.abs(samples), (0, size * count - len(samples)))
        peaks = padded.reshape(count, size).max(axis=1)
        top = float(np.percentile(peaks, 99.5)) or 1.0
        peaks = np.clip(peaks / top, 0, 1)
    else:
        peaks = np.zeros(buckets, np.float32)
    data = {"duration": round(duration, 3), "peaks": [round(float(x), 3) for x in peaks]}
    if len(PEAKS_CACHE) > 40:
        PEAKS_CACHE.clear()
    PEAKS_CACHE[key] = data
    return data


def _num(value) -> float:
    try:
        return max(0.0, float(value or 0))
    except (TypeError, ValueError):
        return 0.0


def _cut_list(frags: list, modes: list, a: float, b: float,
              positions: list[float] | None = None) -> tuple[list, list, list[float]]:
    """Quedarse solo con lo que cae entre a y b (segundos de la edición final), ajustando los fragmentos de las orillas.
    `positions`: dónde empieza cada fragmento en la edición final (si no, van pegados uno tras otro)."""
    out, out_modes, out_pos, pos = [], [], [], 0.0
    for k, (src, start, end) in enumerate(frags):
        dur = end - start
        if positions is not None:
            pos = positions[k]
        s0, s1 = max(a, pos), min(b, pos + dur)
        if s1 - s0 >= 0.05:
            out.append((src, start + (s0 - pos), start + (s1 - pos)))
            out_modes.append(modes[k] if k < len(modes) else "original")
            out_pos.append(s0 - a)
        pos += dur
    return out, out_modes, out_pos


class EditJob:
    """Une los fragmentos en el orden de la lista. Opcional: quitar la voz o la música al resultado."""

    def __init__(self, kind: str, fragments: list[tuple[Path, float, float]], mode: str = "original",
                 smooth: bool = True, preview: bool = False, audio_mode: str = "own",
                 audio_fragments: list[tuple[Path, float, float]] | None = None, effects: list[dict] | None = None,
                 overlays: list[dict] | None = None, frag_modes: list[str] | None = None,
                 audio_modes: list[str] | None = None, positions: list[float] | None = None,
                 max_total: float | None = None, fade_in: float = 0.0, fade_out: float = 0.0) -> None:
        self.id = uuid.uuid4().hex[:12]
        # Capas: dónde empieza cada fragmento en la edición final. Si se enciman, uno se desvanece mientras entra el otro;
        # si hay espacio entre ellos, queda silencio (y negro en video). None = pegados uno tras otro (lo de siempre).
        self.positions: list[float] | None = None
        if positions and len(positions) == len(fragments):
            acc, seq = 0.0, True
            for (_, st, en), ps in zip(fragments, positions):
                seq = seq and abs(ps - acc) < 0.005
                acc += en - st
            if not seq:
                self.positions = [max(0.0, float(x)) for x in positions]
        # «Tal cual / solo música / solo voz» de CADA fragmento (cada uno se separa por su cuenta antes de unir)
        self.frag_modes = [m if m in TRIM_WORDS else "original" for m in (frag_modes or [])]
        self.audio_modes = [m if m in TRIM_WORDS else "original" for m in (audio_modes or [])]
        # animaciones encima del video: {render (para ectube_overlay.render), at, x, y, w, h (fracciones del cuadro)}
        self.overlays = overlays if kind == "video" else []
        self.overlay_files: list[Path] = []
        # efectos: {path, at, start, end, repeat, volume}; siempre suenan ENCIMA del sonido de la edición
        self.effects = effects or []
        self.kind, self.fragments, self.smooth, self.preview = kind, fragments, smooth, preview
        # Video: «own» = el audio de cada fragmento, «none» = sin audio, «other» = otra pista de audio (también por fragmentos)
        self.audio_mode = audio_mode if kind == "video" and audio_mode in ("own", "none", "other") else "own"
        self.audio_fragments = audio_fragments or []
        if self.audio_mode == "other" and not self.audio_fragments:
            self.audio_mode = "none"
        if any(m != "original" for m in self.frag_modes + self.audio_modes):
            mode = "original"  # ya va por fragmento
        self.mode = "original" if preview or mode not in TRIM_WORDS or self.audio_mode == "none" else mode
        self.total = (max(ps + en - st for (_, st, en), ps in zip(fragments, self.positions)) if self.positions
                      else sum(end - start for _, start, end in fragments))
        # sonidos «al final de todo»: la edición se alarga para que suenen completos (en silencio y, en video, en negro)
        tail = max((e["at"] + (e["end"] - e["start"]) * e["repeat"] for e in self.effects if e.get("extend")), default=0.0)
        if max_total is not None:
            tail = min(tail, max_total)
        if tail > self.total + 0.01:
            if not self.positions:  # se arma por capas para poder alargarla
                acc, self.positions = 0.0, []
                for _, st, en in fragments:
                    self.positions.append(acc)
                    acc += en - st
            self.total = tail
        self.effects = [e for e in self.effects if e["at"] < self.total]
        # entrada y salida suave de toda la edición (desde / hasta silencio, y en video desde / hasta negro)
        self.fade_in = max(0.0, min(float(fade_in or 0), 30.0, self.total / 2))
        self.fade_out = max(0.0, min(float(fade_out or 0), 30.0, self.total / 2))
        self.overlays = [o for o in (self.overlays or []) if o["at"] < self.total]
        first = fragments[0][0]
        if kind == "video":
            ext = ".mp4"
        else:  # audio sacado de un video: MP3
            ext = first.suffix.lower() if first.suffix.lower() in AUDIO_CODECS else ".mp3"
        if preview:
            EDIT_TMP.mkdir(parents=True, exist_ok=True)
            self.output = EDIT_TMP / f"vista-previa-{self.id}{'.mp4' if kind == 'video' else '.mp3'}"
        else:
            word = {"original": ("edición", "edit"), "music": ("edición, música", "edit, music"),
                    "voice": ("edición, voz", "edit, vocals")}[self.mode][1 if current_language() == "en" else 0]
            folder = Path(CONFIG[f"{kind}_edited_folder"])
            folder.mkdir(parents=True, exist_ok=True)
            self.output = next((folder / f"{first.stem} ({word}{'' if n == 1 else f' {n}'}){ext}" for n in range(1, 1000)
                                if not (folder / f"{first.stem} ({word}{'' if n == 1 else f' {n}'}){ext}").exists()), None)
            if self.output is None:
                raise RuntimeError("Hay demasiadas ediciones de este archivo.")
        self.status, self.percent, self.error, self.phase = "running", 0.0, "", "join"
        self.process: subprocess.Popen | None = None
        self.sub: TrimJob | None = None
        self.cancelled = False

    def _audio_chain(self, label: str, dur: float, out: str) -> str:
        fade = ""
        if self.smooth and dur > 0.1:  # quitar el «clic» de las uniones
            fade = f",afade=t=in:d=0.015,afade=t=out:st={max(0.0, dur - 0.015):.3f}:d=0.015"
        return f"{label}aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS{fade}[{out}]"

    def _fades(self, chains: list[str], label: str, kind: str) -> str:
        """Entrada / salida suave de toda la edición. Regresa la etiqueta nueva (o la misma si no hay)."""
        parts = []
        if self.fade_in > 0:
            parts.append(f"{'afade' if kind == 'a' else 'fade'}=t=in:st=0:d={self.fade_in:.3f}")
        if self.fade_out > 0:
            parts.append(f"{'afade' if kind == 'a' else 'fade'}=t=out:st={max(0.0, self.total - self.fade_out):.3f}:d={self.fade_out:.3f}")
        if not parts:
            return label
        chains.append(f"{label}{','.join(parts)}[fade{kind}]")
        return f"[fade{kind}]"

    def _fx_chains(self, base: str, add_input, chains: list[str], out: str) -> None:
        """Mezclar los efectos encima de `base` (dura lo mismo que la edición)."""
        labels = []
        for k, fx in enumerate(self.effects):
            dur = fx["end"] - fx["start"]
            idx = add_input(fx["path"], fx["start"], dur)
            chain = f"[{idx}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS"
            if fx["repeat"] > 1:  # repetido: una copia tras otra
                r = fx["repeat"]
                chains.append(chain + f",asplit={r}" + "".join(f"[fx{k}r{j}]" for j in range(r)))
                chain = "".join(f"[fx{k}r{j}]" for j in range(r)) + f"concat=n={r}:v=0:a=1"
            delay = int(round(fx["at"] * 1000))
            chains.append(chain + f",volume={fx['volume']:.2f},adelay={delay}:all=1[fx{k}]")
            labels.append(f"[fx{k}]")
        chains.append(f"{base}{''.join(labels)}amix=inputs={len(labels) + 1}:duration=first:dropout_transition=0:normalize=0[{out}]")

    def fx_command(self, source: Path, output: Path) -> list[str]:
        """Segunda pasada (cuando antes se quitó la voz o la música): poner los efectos encima."""
        args = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-i", str(source)]
        chains: list[str] = []
        n = 1

        def add_input(path: Path, start: float, dur: float) -> int:
            nonlocal n
            args.extend(["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(path)])
            n += 1
            return n - 1

        chains.append("[0:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[base]")
        self._fx_chains("[base]", add_input, chains, "mix")
        args += ["-filter_complex", ";".join(chains)]
        if self.kind == "video":
            args += ["-map", "0:v:0", "-map", "[mix]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
        else:
            args += ["-map", "[mix]", *AUDIO_CODECS.get(output.suffix.lower(), ["-c:a", "libmp3lame", "-b:a", "320k"])]
        return args + ["-progress", "pipe:1", "-nostats", str(output)]

    def command(self, output: Path, with_fx: bool = True) -> list[str]:
        if not FFMPEG:
            raise RuntimeError("No se encontró FFmpeg.")
        args = [FFMPEG, "-hide_banner", "-nostdin", "-y"]
        chains: list[str] = []
        n = 0

        def add_input(path: Path, start: float, dur: float) -> int:
            nonlocal n
            args.extend(["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(path)])
            n += 1
            return n - 1

        def silence(dur: float) -> int:
            nonlocal n
            args.extend(["-f", "lavfi", "-t", f"{dur:.3f}", "-i", "anullsrc=r=48000:cl=stereo"])
            n += 1
            return n - 1

        def audio_track(frags: list[tuple[Path, float, float]], prefix: str) -> str:
            labels = []
            for i, (path, start, end) in enumerate(frags):
                dur = end - start
                idx = add_input(path, start, dur) if probe(path)["audio"] else silence(dur)
                chains.append(self._audio_chain(f"[{idx}:a:0]", dur, f"{prefix}{i}"))
                labels.append(f"[{prefix}{i}]")
            chains.append("".join(labels) + f"concat=n={len(frags)}:v=0:a=1[{prefix}]")
            return f"[{prefix}]"

        positions = self.positions or []
        order = sorted(range(len(positions)), key=lambda i: positions[i])

        def blend(k: int) -> tuple[float, float]:
            """Cuánto se encima el fragmento (en orden de capas) con el anterior y con el siguiente."""
            i = order[k]
            _, st, en = self.fragments[i]
            dur, ps = en - st, positions[i]
            prev_end = max((positions[j] + self.fragments[j][2] - self.fragments[j][1] for j in order[:k]), default=-1.0)
            fade_in = min(dur / 2, max(0.0, prev_end - ps))
            fade_out = min(dur / 2, max(0.0, ps + dur - positions[order[k + 1]])) if k + 1 < len(order) else 0.0
            return fade_in, fade_out

        def layered_audio(prefix: str) -> str:
            labels = []
            for k, i in enumerate(order):
                path, start, end = self.fragments[i]
                dur = end - start
                idx = add_input(path, start, dur) if probe(path)["audio"] else silence(dur)
                fade_in, fade_out = blend(k)
                if self.smooth:
                    fade_in, fade_out = max(fade_in, 0.015), max(fade_out, 0.015)
                chain = f"[{idx}:a:0]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,asetpts=PTS-STARTPTS"
                if fade_in > 0 and dur > 0.1:
                    chain += f",afade=t=in:d={fade_in:.3f}"
                if fade_out > 0 and dur > 0.1:
                    chain += f",afade=t=out:st={max(0.0, dur - fade_out):.3f}:d={fade_out:.3f}"
                chains.append(chain + f",adelay={int(round(positions[i] * 1000))}:all=1[{prefix}{i}]")
                labels.append(f"[{prefix}{i}]")
            chains.append("".join(labels) + f"amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0,"
                          f"apad,atrim=0:{self.total:.3f}[{prefix}]")
            return f"[{prefix}]"

        if self.kind == "audio":
            for path, *_ in self.fragments:
                if not probe(path)["audio"]:
                    raise RuntimeError(f"«{path.name}» no tiene audio.")
            track = layered_audio("a") if self.positions else audio_track(self.fragments, "a")
            if with_fx and self.effects:
                self._fx_chains(track, add_input, chains, "mix")
                track = "[mix]"
            track = self._fades(chains, track, "a")
            args += ["-filter_complex", ";".join(chains), "-map", track, "-vn"]
            if self.preview:
                args += ["-c:a", "libmp3lame", "-b:a", "128k"]
            else:
                args += AUDIO_CODECS.get(output.suffix.lower(), ["-c:a", "libmp3lame", "-b:a", "320k"])
            return args + ["-progress", "pipe:1", "-nostats", str(output)]

        info = probe(self.fragments[0][0])
        width, height = (info["width"] or 1280) // 2 * 2, (info["height"] or 720) // 2 * 2
        fps = min(60.0, max(24.0, round(info["fps"] or 30, 3)))  # los cuadros por segundo del primer video (60 se queda en 60)
        vlabels = []
        if self.positions:  # capas: fondo negro y cada fragmento encima a su tiempo (el que entra aparece poco a poco)
            chains.append(f"color=c=black:s={width}x{height}:r={fps}:d={self.total:.3f},format=yuv420p[bg]")
            cur = "bg"
            for k, i in enumerate(order):
                path, start, end = self.fragments[i]
                idx = add_input(path, start, end - start)
                fade_in, _ = blend(k)
                chain = (f"[{idx}:v:0]setpts=PTS-STARTPTS,scale={width}:{height}:force_original_aspect_ratio=decrease,"
                         f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuva420p")
                if fade_in > 0:
                    chain += f",fade=t=in:st=0:d={fade_in:.3f}:alpha=1"
                chains.append(chain + f",setpts=PTS+{positions[i]:.3f}/TB[v{i}]")
                chains.append(f"[{cur}][v{i}]overlay=eof_action=pass:format=auto[lv{k}]")
                cur = f"lv{k}"
            chains.append(f"[{cur}]format=yuv420p[v]")
            if self.audio_mode == "own":
                chains.append(f"{layered_audio('la')}anull[a]")
        for i, (path, start, end) in enumerate([] if self.positions else self.fragments):
            dur = end - start
            idx = add_input(path, start, dur)
            chains.append(f"[{idx}:v:0]setpts=PTS-STARTPTS,scale={width}:{height}:force_original_aspect_ratio=decrease,"
                          f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{i}]")
            vlabels.append(f"[v{i}]")
            if self.audio_mode == "own":
                aidx = idx if probe(path)["audio"] else silence(dur)  # video sin audio: silencio del mismo largo
                chains.append(self._audio_chain(f"[{aidx}:a:0]", dur, f"a{i}"))
                vlabels.append(f"[a{i}]")
        count = len(self.fragments)
        if self.overlay_files:  # animaciones encima, cada una en su lugar y a su tiempo
            cur = "v"
            for k, (ov, path) in enumerate(zip(self.overlays, self.overlay_files)):
                args.extend(["-i", str(path)])
                n += 1
                x, y = round(ov["x"] * width), round(ov["y"] * height)
                chains.append(f"[{n - 1}:v]setpts=PTS-STARTPTS+{ov['at']:.3f}/TB[ov{k}]")
                chains.append(f"[{cur}][ov{k}]overlay=x={x}:y={y}:eof_action=pass:format=auto[vo{k}]")
                cur = f"vo{k}"
            chains.append(f"[{cur}]format=yuv420p[vfinal]")
            vout = "[vfinal]"
        else:
            vout = "[v]"
        fx = with_fx and bool(self.effects)
        has_audio = self.audio_mode != "none" or fx
        if self.positions:
            pass  # [v] y [a] ya están armados por capas
        elif self.audio_mode == "own":
            chains.append("".join(vlabels) + f"concat=n={count}:v=1:a=1[v][a]")
        else:
            chains.append("".join(vlabels) + f"concat=n={count}:v=1:a=0[v]")
        if self.audio_mode != "own":
            if self.audio_mode == "other":
                track = audio_track(self.audio_fragments, "b")
                # la pista de audio dura lo mismo que el video: si sobra se corta, si falta queda en silencio
                chains.append(f"{track}apad,atrim=0:{self.total:.3f}[a]")
            elif fx:  # video sin audio, pero con efectos: los efectos suenan sobre silencio
                chains.append(f"[{silence(self.total)}:a:0]anull[a]")
        alabel = "[a]"
        if fx:
            self._fx_chains("[a]", add_input, chains, "mix")
            alabel = "[mix]"
        vout = self._fades(chains, vout, "v")
        if has_audio:
            alabel = self._fades(chains, alabel, "a")
        maps = ["-map", vout] + (["-map", alabel] if has_audio else [])
        args += ["-filter_complex", ";".join(chains), *maps]
        if self.preview:
            args += ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "28"]
        else:
            args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]
        args += ["-c:a", "aac", "-b:a", "128k" if self.preview else "192k"] if has_audio else ["-an"]
        args += ["-movflags", "+faststart"]
        return args + ["-progress", "pipe:1", "-nostats", str(output)]

    def _join(self, output: Path, share: float, cmd: list[str] | None = None, base: float = 0.0) -> None:
        self.process = subprocess.Popen(cmd or self.command(output), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                        encoding="utf-8", errors="replace", creationflags=_no_window_flags())
        errors: list[str] = []
        threading.Thread(target=lambda: errors.extend(self.process.stderr.readlines()), daemon=True).start()  # type: ignore[union-attr]
        for line in self.process.stdout:  # type: ignore[union-attr]
            if line.startswith(("out_time_us=", "out_time_ms=")):
                with contextlib.suppress(ValueError):
                    self.percent = base + min(share - 1, int(line.split("=", 1)[1]) / 1e6 / max(0.1, self.total) * share)
        code = self.process.wait()
        if self.cancelled:
            raise InterruptedError
        if code != 0 or not output.exists():
            log(f"[edición {self.id}] error: {''.join(errors[-6:])[:600]}")
            raise RuntimeError(friendly_error("".join(errors[-20:])) if errors else "No se pudo guardar la edición.")

    def _render_overlays(self) -> None:
        """Dibujar cada animación (con su texto) a su tamaño; las que ya se hicieron antes se reusan."""
        from ectube_overlay import cache_key, overlay_size, render

        if not self.overlays:
            return
        info = probe(self.fragments[0][0])
        width, height = (info["width"] or 1280) // 2 * 2, (info["height"] or 720) // 2 * 2
        cache = EDIT_TMP / "animaciones"
        cache.mkdir(parents=True, exist_ok=True)
        self.phase = "anims"
        for k, ov in enumerate(self.overlays):
            if self.cancelled:
                raise InterruptedError
            w, h = overlay_size(ov["w"], ov["h"], width, height)
            out = cache / f"{cache_key(ov['render'], w, h)}.mov"
            if not out.exists():
                tmp = out.with_suffix(".tmp.mov")
                render(ov["render"], w, h, tmp, FFMPEG, _no_window_flags())
                tmp.replace(out)
            self.overlay_files.append(out)
            self.percent = 10.0 * (k + 1) / len(self.overlays)

    def _separate_parts(self) -> None:
        """Los fragmentos con «solo música» o «solo voz» se separan uno por uno (y se guardan para la próxima vez)."""
        jobs = [(lst, i, m) for lst, modes in ((self.fragments, self.frag_modes), (self.audio_fragments, self.audio_modes))
                for i, m in enumerate(modes) if i < len(lst) and m != "original"]
        if not jobs or (self.kind == "video" and self.audio_mode == "none" and all(lst is self.fragments for lst, _, _ in jobs)):
            return
        cache = EDIT_TMP / "separados"
        cache.mkdir(parents=True, exist_ok=True)
        for k, (lst, i, m) in enumerate(jobs):
            if self.cancelled:
                raise InterruptedError
            src, start, end = lst[i]
            stamp = 0
            with contextlib.suppress(OSError):
                stamp = src.stat().st_mtime_ns
            key = hashlib.sha1(f"{src}|{stamp}|{start:.3f}|{end:.3f}|{m}".encode()).hexdigest()[:20]
            out = cache / f"{key}{src.suffix.lower() if src.suffix.lower() in AUDIO_CODECS or src.suffix.lower() in VIDEO_EXTS else '.mp3'}"
            if not out.exists():
                self.phase = "separate"
                sub = TrimJob(src, start, end, m)
                tmp = out.with_name(out.stem + ".tmp" + out.suffix)
                sub.output = tmp
                self.sub = sub
                done = threading.Event()

                def follow(sub=sub, k=k) -> None:
                    while not done.wait(0.4):
                        self.phase = sub.phase or "separate"
                        self.percent = 5 + (k + sub.percent / 100) / len(jobs) * 60

                threading.Thread(target=follow, daemon=True).start()
                sub.run()
                done.set()
                self.sub = None
                if sub.status == "cancelled" or self.cancelled:
                    raise InterruptedError
                if sub.status != "done" or not tmp.exists():
                    raise RuntimeError(sub.error or "No se pudo separar la voz o la música de un fragmento.")
                tmp.replace(out)
            lst[i] = (out, 0.0, end - start)
            self.percent = 5 + (k + 1) / len(jobs) * 60

    def run(self) -> None:
        temp: Path | None = None
        try:
            self._separate_parts()
            self._render_overlays()
            self.phase = "join"
            log(f"[edición {self.id}] {len(self.fragments)} fragmentos, {self.total:.1f} s, {self.kind}, {self.mode}"
                + (" (vista previa)" if self.preview else ""))
            if self.mode == "original":
                base = self.percent if self.percent > 0 else (10.0 if self.overlays else 0.0)
                self._join(self.output, 100.0 - base, base=base)
            else:  # primero se une todo y luego se separa la voz o la música del resultado
                EDIT_TMP.mkdir(parents=True, exist_ok=True)
                temp = EDIT_TMP / f"unido-{self.id}{self.output.suffix}"
                separated = EDIT_TMP / f"separado-{self.id}{self.output.suffix}" if self.effects else self.output
                # los efectos se ponen al final, para que no se los coma el separador
                self.process = None
                self._join(temp, 25.0, self.command(temp, with_fx=False))
                self.sub = TrimJob(temp, 0.0, self.total, self.mode)
                self.sub.output = separated
                self.phase = "separate"
                done = threading.Event()

                def follow() -> None:
                    while not done.wait(0.4):
                        self.phase = self.sub.phase or "separate"  # type: ignore[union-attr]
                        self.percent = 25 + self.sub.percent * (0.70 if self.effects else 0.75)  # type: ignore[union-attr]

                threading.Thread(target=follow, daemon=True).start()
                self.sub.run()
                done.set()
                if self.sub.status == "cancelled" or self.cancelled:
                    raise InterruptedError
                if self.sub.status != "done":
                    raise RuntimeError(self.sub.error or "No se pudo guardar la edición.")
                if self.effects:
                    self.phase = "effects"
                    try:
                        self._join(self.output, 5.0, self.fx_command(separated, self.output), base=95.0)
                    finally:
                        with contextlib.suppress(OSError):
                            separated.unlink()
            self.status, self.percent = "done", 100.0
        except InterruptedError:
            self.status = "cancelled"
        except Exception as exc:  # noqa: BLE001
            self.status, self.error = "error", str(exc)
            log(f"[edición {self.id}] error: {exc}")
        if temp:
            with contextlib.suppress(OSError):
                temp.unlink()
        if self.status != "done":
            with contextlib.suppress(OSError):
                self.output.unlink()

    def cancel(self) -> None:
        self.cancelled = True
        if self.sub:
            self.sub.cancelled = True
            if self.sub.process:
                _kill_tree(self.sub.process)
        if self.process:
            _kill_tree(self.process)

    def public(self) -> dict:
        data = {"id": self.id, "status": self.status, "percent": round(self.percent, 1), "error": self.error,
                "output": self.output.name, "mode": self.mode, "phase": self.phase, "preview": self.preview}
        if self.status == "done":
            data["media"] = media_info(self.output)
        return data


EDITS: dict[str, EditJob] = {}


def clear_edit_tmp() -> None:
    """Las vistas previas viejas no se guardan: se borran al abrir EC-Tube."""
    if EDIT_TMP.is_dir():
        for item in EDIT_TMP.iterdir():
            with contextlib.suppress(OSError):
                shutil.rmtree(item) if item.is_dir() else item.unlink()


# ---------------------------------------------------------------------------
# Reproductor: biblioteca (carpetas de descargas y editados) y listas guardadas
# ---------------------------------------------------------------------------
PLAYLISTS_PATH = HOME / "playlists.json"
PLAYLISTS_LOCK = threading.Lock()
MAX_LISTS, MAX_ITEMS = 100, 5000


def library(where: str, kind: str = "audio") -> dict:
    """Archivos de una carpeta (y sus subcarpetas, p. ej. listas de YouTube), los más nuevos primero."""
    kind = "video" if kind == "video" else "audio"
    folder = Path(CONFIG[f"{kind}_edited_folder"] if where == "edited" else CONFIG[f"{kind}_folder"])
    exts = VIDEO_EXTS if kind == "video" else AUDIO_EXTS
    files = []
    if folder.is_dir():
        base_depth = len(folder.parts)
        for root, dirs, names in os.walk(folder):
            if len(Path(root).parts) - base_depth >= 3:
                dirs[:] = []
            for name in names:
                path = Path(root) / name
                if path.suffix.lower() in exts and not name.endswith((".part", ".ytdl")):
                    with contextlib.suppress(OSError):
                        stat = path.stat()
                        files.append((stat.st_mtime, path, stat.st_size))
            if len(files) > 3000:
                break
    files.sort(key=lambda item: item[0], reverse=True)
    return {"folder": str(folder), "items": [
        {"token": MEDIA.token_for(path), "name": path.stem, "file": path.name,
         "sub": str(path.parent.relative_to(folder)) if path.parent != folder else "",
         "mtime": int(mtime), "size": size} for mtime, path, size in files[:2000]]}


def _clean_player(data: object) -> dict:
    data = data if isinstance(data, dict) else {}
    volume = data.get("volume", 0.8)
    return {"volume": float(min(1.0, max(0.0, volume))) if isinstance(volume, (int, float)) else 0.8,
            "shuffle": bool(data.get("shuffle")),
            "repeat": data.get("repeat") if data.get("repeat") in ("off", "all", "one") else "all"}


def load_playlists() -> dict:
    with PLAYLISTS_LOCK, contextlib.suppress(OSError, json.JSONDecodeError):
        data = json.loads(PLAYLISTS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("lists"), list):
            return data
    first = "Mi lista" if current_language() != "en" else "My list"
    return {"lists": [{"id": uuid.uuid4().hex[:10], "name": first, "items": []}], "current": "", "player": {}}


def playlists_public(data: dict) -> dict:
    lists = []
    for entry in data.get("lists", []):
        items = []
        for item in entry.get("items", []):
            path = Path(str(item.get("path") or ""))
            items.append({"token": MEDIA.token_for(path), "name": path.stem, "exists": path.is_file(),
                          "duration": item.get("duration")})
        lists.append({"id": entry.get("id"), "name": entry.get("name"), "items": items})
    current = data.get("current") if any(entry["id"] == data.get("current") for entry in lists) else (lists[0]["id"] if lists else "")
    return {"lists": lists, "current": current, "player": _clean_player(data.get("player"))}


def save_playlists(incoming: dict) -> dict:
    """La página manda las listas con «token» de cada canción; aquí se cambian por la ruta real."""
    raw_lists = incoming.get("lists")
    if not isinstance(raw_lists, list) or not raw_lists:
        raise ValueError("Debe quedar al menos una lista.")
    lists = []
    for entry in raw_lists[:MAX_LISTS]:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()[:80] or "Lista"
        list_id = str(entry.get("id") or "")
        if not re.fullmatch(r"[0-9a-f]{10}", list_id):
            list_id = uuid.uuid4().hex[:10]
        items = []
        for item in (entry.get("items") or [])[:MAX_ITEMS]:
            if not isinstance(item, dict):
                continue
            path = MEDIA.path(str(item.get("token") or ""))
            if path is None:
                continue  # solo canciones que EC-Tube ya conoce (biblioteca, archivos elegidos o listas guardadas)
            duration = item.get("duration")
            items.append({"path": str(path),
                          "duration": round(float(duration), 2) if isinstance(duration, (int, float)) and 0 < duration < 86400 else None})
        lists.append({"id": list_id, "name": name, "items": items})
    data = {"lists": lists, "current": str(incoming.get("current") or ""), "player": _clean_player(incoming.get("player"))}
    with PLAYLISTS_LOCK:
        HOME.mkdir(parents=True, exist_ok=True)
        tmp = PLAYLISTS_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(PLAYLISTS_PATH)
    return playlists_public(data)


# ---------------------------------------------------------------------------
# Karaoke: proyectos (música + letra con tiempos) y exportar el video
# ---------------------------------------------------------------------------
KARAOKE_DIR = HOME / "karaoke"
HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


def _karaoke_path(project_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", project_id or ""):
        raise ValueError("Proyecto inválido.")
    return KARAOKE_DIR / f"{project_id}.json"


def karaoke_public(project: dict) -> dict:
    data = {k: project.get(k) for k in ("id", "title", "lyrics", "lines", "offset", "sung_color", "bg", "color1",
                                       "color2", "format", "mark_mode", "method", "holds", "edited", "hide_unedited", "video_type", "lyrics_highlight", "accepted", "reviewed", "voice_removed", "updated")}
    for key in ("source", "image", "guide"):
        path = Path(project[key]) if project.get(key) else None
        data[key] = {"token": MEDIA.token_for(path), "name": path.name, "exists": path.is_file(),
                     "video": path.suffix.lower() in VIDEO_EXTS} if path else None
    return data


def karaoke_list() -> list[dict]:
    items = []
    if KARAOKE_DIR.is_dir():
        for path in KARAOKE_DIR.glob("*.json"):
            with contextlib.suppress(OSError, json.JSONDecodeError):
                data = json.loads(path.read_text(encoding="utf-8"))
                items.append({"id": data.get("id"), "title": data.get("title") or "", "updated": data.get("updated", 0)})
    return sorted(items, key=lambda item: item["updated"], reverse=True)


def karaoke_load(project_id: str) -> dict:
    return json.loads(_karaoke_path(project_id).read_text(encoding="utf-8"))


def karaoke_save(data: dict) -> dict:
    project_id = str(data.get("id") or "") or uuid.uuid4().hex[:12]
    path = _karaoke_path(project_id)
    project = {"id": project_id, "title": str(data.get("title") or "").strip()[:120],
               "lyrics": str(data.get("lyrics") or "")[:20000], "updated": int(time.time())}
    for key in ("source", "image", "guide"):
        token = data.get(f"{key}_token")
        found = MEDIA.path(str(token)) if token else None
        project[key] = str(found) if found else None
    lines = []
    for line in (data.get("lines") or [])[:1000]:
        units = []
        for unit in (line or [])[:200]:
            if not isinstance(unit, dict):
                continue
            start, end = unit.get("start"), unit.get("end")
            units.append({"text": str(unit.get("text") or "")[:80], "space": bool(unit.get("space")),
                          "start": round(float(start), 3) if isinstance(start, (int, float)) else None,
                          "end": round(float(end), 3) if isinstance(end, (int, float)) else None})
        lines.append(units)
    project["lines"] = lines
    offset = data.get("offset", 0)
    project["offset"] = float(min(2, max(-2, offset))) if isinstance(offset, (int, float)) else 0.0
    project["sung_color"] = data.get("sung_color") if HEX_COLOR.fullmatch(str(data.get("sung_color") or "")) else "#36C5F0"
    project["color1"] = data.get("color1") if HEX_COLOR.fullmatch(str(data.get("color1") or "")) else "#1B1340"
    project["color2"] = data.get("color2") if HEX_COLOR.fullmatch(str(data.get("color2") or "")) else "#6C4CE6"
    project["bg"] = data.get("bg") if data.get("bg") in ("video", "image", "color") else "color"
    project["format"] = data.get("format") if data.get("format") in ("16:9", "9:16") else "16:9"
    holds = []
    for hold in (data.get("holds") or [])[:1000]:
        ok = isinstance(hold, list) and len(hold) == 2 and all(isinstance(x, (int, float)) for x in hold)
        holds.append([round(float(hold[0]), 3), round(float(hold[1]), 3)] if ok else None)
    project["holds"] = holds
    project["accepted"] = bool(data.get("accepted"))
    project["reviewed"] = bool(data.get("reviewed"))
    project["voice_removed"] = bool(data.get("voice_removed"))
    project["video_type"] = "lyrics" if data.get("video_type") == "lyrics" else "karaoke"
    project["lyrics_highlight"] = bool(data.get("lyrics_highlight"))
    project["edited"] = [bool(x) for x in (data.get("edited") or [])[:1000]]
    project["hide_unedited"] = bool(data.get("hide_unedited"))
    project["method"] = data.get("method") if data.get("method") in ("guided", "auto", "semi", "manual") else None
    project["mark_mode"] = data.get("mark_mode") if data.get("mark_mode") in ("line", "word") else "line"
    KARAOKE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(project, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    return karaoke_public(project)


def _media_duration(path: Path) -> float:
    probe = _tool("ffprobe") or (str(Path(FFMPEG).with_name("ffprobe" + (".exe" if IS_WINDOWS else ""))) if FFMPEG else None)
    with contextlib.suppress(Exception):
        result = subprocess.run([probe, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                                capture_output=True, text=True, timeout=30, creationflags=_no_window_flags())
        return float(result.stdout.strip())
    return 0.0


class KaraokeExport:
    """Arma el video: fondo (video, imagen o color) + letra (ASS con \\kf) + el audio de la música."""

    def __init__(self, project: dict, fmt: str) -> None:
        from ectube_karaoke import SIZES

        self.id = uuid.uuid4().hex[:12]
        self.project, self.fmt = project, fmt if fmt in SIZES else "16:9"
        self.width, self.height = SIZES[self.fmt]
        source = Path(project.get("source") or "")
        if not source.is_file():
            raise RuntimeError("La música del karaoke ya no está en su carpeta.")
        self.source = source
        # Video con letra: suena la canción CON voz (la voz guía), corrida igual que la pista.
        self.lyrics = project.get("video_type") == "lyrics"
        self.voice: Path | None = None
        self.voice_shift = 0.0
        guide = Path(project.get("guide") or "")
        if self.lyrics and project.get("guide") and guide.is_file() and guide != source:
            self.voice = guide
            with contextlib.suppress(Exception):
                g = guide_for(guide)
                for _ in range(50):
                    if g.state != "preparing":
                        break
                    time.sleep(0.1)
                if g.state == "ready":
                    self.voice_shift = g.offset_for(source)
        folder = Path(CONFIG["karaoke_folder"])
        folder.mkdir(parents=True, exist_ok=True)
        name = re.sub(r'[<>:"/\\|?*]+', "", project.get("title") or source.stem).strip() or "Karaoke"
        suffix = " (vertical)" if self.fmt == "9:16" else ""
        word = ("lyrics" if current_language() == "en" else "letra") if self.lyrics else "karaoke"
        output = folder / f"{name} ({word}){suffix}.mp4"
        n = 2
        while output.exists():
            output = folder / f"{name} ({word} {n}){suffix}.mp4"
            n += 1
        self.output = output
        self.status, self.percent, self.error = "running", 0.0, ""
        self.process: subprocess.Popen | None = None
        self.cancelled = False

    def command(self, work: Path) -> list[str]:
        if not FFMPEG:
            raise RuntimeError("No se encontró FFmpeg.")
        w, h = self.width, self.height
        bg = self.project.get("bg")
        is_video = self.source.suffix.lower() in VIDEO_EXTS
        fit = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
        args = [FFMPEG, "-hide_banner", "-nostdin", "-y"]
        if bg == "video" and is_video:
            args += ["-i", str(self.source)]
            chain = f"[0:v]{fit},eq=brightness=-0.10:saturation=0.9,fps=30"
            audio = "0:a:0"
        elif bg == "image" and self.project.get("image") and Path(self.project["image"]).is_file():
            args += ["-loop", "1", "-framerate", "30", "-i", self.project["image"], "-i", str(self.source)]
            chain = f"[0:v]{fit},eq=brightness=-0.08"
            audio = "1:a:0"
        else:
            c1, c2 = self.project.get("color1", "#1B1340"), self.project.get("color2", "#6C4CE6")
            args += ["-f", "lavfi", "-i", f"gradients=s={w}x{h}:c0=0x{c1[1:]}:c1=0x{c2[1:]}:x0=0:y0=0:x1={w}:y1={h}:speed=0.002:rate=30",
                     "-i", str(self.source)]
            chain = "[0:v]setsar=1"
            audio = "1:a:0"
        if self.voice:
            # tiempo_en_pista = tiempo_en_guía + corrimiento → retrasar (o adelantar) la canción con voz
            index = sum(1 for a in args if a == "-i")
            shift = self.voice_shift
            args += (["-itsoffset", f"{shift:.3f}"] if shift > 0 else ["-ss", f"{-shift:.3f}"] if shift < 0 else []) + ["-i", str(self.voice)]
            audio = f"{index}:a:0"
        args += ["-filter_complex", f"{chain},ass=karaoke.ass,format=yuv420p[v]", "-map", "[v]", "-map", audio,
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "192k",
                 "-movflags", "+faststart", "-shortest", "-progress", "pipe:1", "-nostats", str(self.output)]
        return args

    def run(self) -> None:
        from ectube_karaoke import build_ass

        work = KARAOKE_DIR / f"render-{self.id}"
        try:
            work.mkdir(parents=True, exist_ok=True)
            (work / "karaoke.ass").write_text(build_ass(self.project, self.fmt), encoding="utf-8")
            duration = max(1.0, _media_duration(self.source))
            log(f"[karaoke {self.id}] {self.output.name} ({self.fmt}, fondo {self.project.get('bg')})")
            # Se corre DENTRO de la carpeta de trabajo: así el filtro «ass» no tiene que lidiar con rutas de Windows.
            self.process = subprocess.Popen(self.command(work), cwd=str(work), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                            text=True, encoding="utf-8", errors="replace", creationflags=_no_window_flags())
            errors: list[str] = []
            threading.Thread(target=lambda: errors.extend(self.process.stderr.readlines()), daemon=True).start()  # type: ignore[union-attr]
            for line in self.process.stdout:  # type: ignore[union-attr]
                if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                    with contextlib.suppress(ValueError):
                        self.percent = min(99.0, int(line.split("=", 1)[1]) / 1e6 / duration * 100)
            code = self.process.wait()
            if self.cancelled:
                self.status = "cancelled"
            elif code == 0 and self.output.exists():
                self.status, self.percent = "done", 100.0
            else:
                self.status = "error"
                self.error = friendly_error("".join(errors[-20:])) if errors else "No se pudo crear el video."
                log(f"[karaoke {self.id}] error: {''.join(errors[-8:])[:800]}")
        except Exception as exc:  # noqa: BLE001
            self.status, self.error = "error", str(exc)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if self.status != "done":
            with contextlib.suppress(OSError):
                self.output.unlink()

    def public(self) -> dict:
        return {"id": self.id, "status": self.status, "percent": round(self.percent, 1), "error": self.error,
                "output": self.output.name}


KARAOKE_JOBS: dict[str, KaraokeExport] = {}


# ---------------------------------------------------------------------------
# Subtítulos: bloques de texto sobre el video (como en las películas)
# ---------------------------------------------------------------------------
SUBS_DIR = HOME / "subtitulos"


def _subs_path(project_id: str) -> Path:
    if not re.fullmatch(r"[0-9a-f]{12}", project_id or ""):
        raise ValueError("Proyecto inválido.")
    return SUBS_DIR / f"{project_id}.json"


def source_url(path: Path) -> str:
    """El enlace de YouTube que yt-dlp guarda dentro del archivo al descargarlo (si lo bajó EC-Tube)."""
    if not FFMPEG or not path.is_file():
        return ""
    out = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-i", str(path)], capture_output=True, text=True,
                         encoding="utf-8", errors="replace", creationflags=_no_window_flags()).stderr
    m = re.search(r"^\s*(?:purl|comment)\s*:\s*(https?://\S+)", out, re.M | re.I)
    return m.group(1) if m else ""


def subs_public(project: dict) -> dict:
    from ectube_subs import clean_style

    data = {k: project.get(k) for k in ("id", "title", "blocks", "url", "lang", "script", "updated")}
    data["style"] = clean_style(project.get("style"))
    path = Path(project["source"]) if project.get("source") else None
    data["source"] = {"token": MEDIA.token_for(path), "name": path.name, "exists": path.is_file()} if path else None
    return data


def subs_list() -> list[dict]:
    items = []
    if SUBS_DIR.is_dir():
        for path in SUBS_DIR.glob("*.json"):
            with contextlib.suppress(OSError, json.JSONDecodeError):
                data = json.loads(path.read_text(encoding="utf-8"))
                items.append({"id": data.get("id"), "title": data.get("title") or "", "updated": data.get("updated", 0)})
    return sorted(items, key=lambda item: item["updated"], reverse=True)


def subs_load(project_id: str) -> dict:
    return json.loads(_subs_path(project_id).read_text(encoding="utf-8"))


def subs_save(data: dict) -> dict:
    from ectube_subs import clean_blocks, clean_style

    project_id = str(data.get("id") or "") or uuid.uuid4().hex[:12]
    path = _subs_path(project_id)
    old = {}
    with contextlib.suppress(OSError, json.JSONDecodeError):
        old = json.loads(path.read_text(encoding="utf-8"))
    project = {"id": project_id, "title": str(data.get("title") or "").strip()[:120], "updated": int(time.time()),
               "blocks": clean_blocks(data.get("blocks")), "style": clean_style(data.get("style")),
               "url": str(data.get("url") or "")[:500], "lang": str(data.get("lang") or "es")[:8],
               "script": str(data.get("script") or "")[:50000]}
    token = data.get("source_token")
    found = MEDIA.path(str(token)) if token else None
    project["source"] = str(found) if found else (old.get("source") if "source_token" not in data else None)
    SUBS_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(project, ensure_ascii=False, indent=1), encoding="utf-8")
    return subs_public(project)


SUB_LANGS = {"es": "es.*", "en": "en.*", "pt": "pt.*", "auto": ".*-orig"}


class SubsFetch:
    """Traer los subtítulos que YouTube ya tiene para el video (hechos por alguien o automáticos)."""

    def __init__(self, url: str, lang: str) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.url, self.lang = url, lang if lang in SUB_LANGS else "es"
        self.status, self.error, self.blocks, self.kind, self.found_lang = "running", "", [], "", ""

    def run(self) -> None:
        from ectube_subs import parse_json3, parse_vtt

        work = SUBS_DIR / f"yt-{self.id}"
        try:
            path = ytdlp_path()
            if not path:
                raise RuntimeError("No se encontró el motor de descargas (yt-dlp).")
            work.mkdir(parents=True, exist_ok=True)
            args = [path, "--ignore-config", "--no-colors", "--encoding", "utf-8", "--skip-download", "--no-playlist",
                    "--write-subs", "--write-auto-subs", "--sub-langs", SUB_LANGS[self.lang], "--sub-format", "json3/vtt/best",
                    "-P", str(work), "-o", "sub"]
            if DENO:
                args += ["--js-runtimes", f"deno:{DENO}"]
            result = subprocess.run([*args, "--", self.url], capture_output=True, text=True, encoding="utf-8", errors="replace",
                                    creationflags=_no_window_flags(), timeout=180)
            files = sorted(p for p in work.iterdir() if p.suffix.lower() in (".json3", ".vtt"))
            if not files:
                if result.returncode != 0:
                    raise RuntimeError(friendly_error(result.stderr))
                raise RuntimeError("Este video no tiene subtítulos de YouTube en ese idioma. Prueba con otro idioma, "
                                   "o escribe tu guion.")
            # preferir los hechos por alguien (lang sin «-orig» ni traducción) sobre los automáticos
            best = sorted(files, key=lambda p: ("orig" in p.name, len(p.name)))[0]
            text = best.read_text(encoding="utf-8", errors="replace")
            self.blocks = parse_json3(text) if best.suffix.lower() == ".json3" else parse_vtt(text)
            self.found_lang = best.name.split(".")[-2] if best.name.count(".") >= 2 else ""
            if not self.blocks:
                raise RuntimeError("Los subtítulos de YouTube vinieron vacíos.")
            self.status = "done"
        except subprocess.TimeoutExpired:
            self.status, self.error = "error", "YouTube tardó demasiado en responder. Intenta otra vez."
        except Exception as exc:  # noqa: BLE001
            self.status, self.error = "error", str(exc)
            log(f"[subtítulos {self.id}] {exc}")
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def public(self) -> dict:
        return {"id": self.id, "status": self.status, "error": self.error, "blocks": self.blocks, "lang": self.found_lang}


SUBS_FETCHES: dict[str, SubsFetch] = {}


class SubsExport:
    """Pegar los subtítulos en el video (MP4) y guardar también el .srt."""

    def __init__(self, project: dict) -> None:
        from ectube_subs import timed

        source = Path(project.get("source") or "")
        if not source.is_file():
            raise RuntimeError("El video ya no está en su carpeta.")
        if not timed(project.get("blocks") or []):
            raise RuntimeError("Todavía no hay subtítulos con tiempos.")
        self.id = uuid.uuid4().hex[:12]
        self.project, self.source = project, source
        folder = Path(CONFIG["video_edited_folder"])
        folder.mkdir(parents=True, exist_ok=True)
        word = "subtitles" if current_language() == "en" else "subtítulos"
        stem = re.sub(r'[<>:"/\\|?*]+', "", project.get("title") or source.stem).strip() or source.stem
        output = folder / f"{stem} ({word}).mp4"
        n = 2
        while output.exists():
            output = folder / f"{stem} ({word} {n}).mp4"
            n += 1
        self.output = output
        self.srt = output.with_suffix(".srt")
        self.status, self.percent, self.error = "running", 0.0, ""
        self.process: subprocess.Popen | None = None
        self.cancelled = False

    def run(self) -> None:
        from ectube_subs import build_ass, build_srt

        work = SUBS_DIR / f"render-{self.id}"
        try:
            if not FFMPEG:
                raise RuntimeError("No se encontró FFmpeg.")
            info = probe(self.source)
            width, height = (info["width"] or 1280) // 2 * 2, (info["height"] or 720) // 2 * 2
            work.mkdir(parents=True, exist_ok=True)
            style = self.project.get("style") or {}
            (work / "subs.ass").write_text(build_ass(self.project["blocks"], style, width, height), encoding="utf-8")
            self.srt.write_text(build_srt(self.project["blocks"], bool(style.get("upper"))), encoding="utf-8")
            duration = max(1.0, info["duration"] or _media_duration(self.source))
            args = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-i", str(self.source),
                    "-vf", f"scale={width}:{height},setsar=1,ass=subs.ass,format=yuv420p", "-map", "0:v:0"]
            args += ["-map", "0:a:0?", "-c:a", "aac", "-b:a", "192k"] if info["audio"] else []
            args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-movflags", "+faststart",
                     "-progress", "pipe:1", "-nostats", str(self.output)]
            log(f"[subtítulos {self.id}] {self.output.name}")
            # dentro de la carpeta de trabajo: así el filtro «ass» no lidia con rutas de Windows
            self.process = subprocess.Popen(args, cwd=str(work), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                            encoding="utf-8", errors="replace", creationflags=_no_window_flags())
            errors: list[str] = []
            threading.Thread(target=lambda: errors.extend(self.process.stderr.readlines()), daemon=True).start()  # type: ignore[union-attr]
            for line in self.process.stdout:  # type: ignore[union-attr]
                if line.startswith(("out_time_us=", "out_time_ms=")):
                    with contextlib.suppress(ValueError):
                        self.percent = min(99.0, int(line.split("=", 1)[1]) / 1e6 / duration * 100)
            code = self.process.wait()
            if self.cancelled:
                self.status = "cancelled"
            elif code == 0 and self.output.exists():
                self.status, self.percent = "done", 100.0
            else:
                self.status = "error"
                self.error = friendly_error("".join(errors[-20:])) if errors else "No se pudo crear el video."
                log(f"[subtítulos {self.id}] error: {''.join(errors[-8:])[:800]}")
        except Exception as exc:  # noqa: BLE001
            self.status, self.error = "error", str(exc)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if self.status != "done":
            with contextlib.suppress(OSError):
                self.output.unlink()

    def public(self) -> dict:
        return {"id": self.id, "status": self.status, "percent": round(self.percent, 1), "error": self.error,
                "output": self.output.name, "srt": self.srt.name,
                "media": MEDIA.token_for(self.output) if self.status == "done" else ""}


SUBS_JOBS: dict[str, SubsExport] = {}


def _audio_16k(path: Path):
    """El audio en mono a 16 kHz (lo que necesita el reconocimiento de voz)."""
    import numpy as np

    if not FFMPEG:
        raise RuntimeError("No se encontró FFmpeg.")
    result = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(path), "-vn", "-ac", "1",
                             "-ar", "16000", "-f", "f32le", "pipe:1"], capture_output=True, creationflags=_no_window_flags())
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError("No se pudo leer el audio del video.")
    return np.frombuffer(result.stdout, dtype="<f4").copy()


class AsrJob:
    """🤖 Escuchar el audio y escribir los subtítulos (la primera vez baja el «oído»)."""

    def __init__(self, source: Path, lang: str, quality: str) -> None:
        from ectube_asr import MODELS

        self.id = uuid.uuid4().hex[:12]
        self.source, self.lang = source, lang if lang in ("es", "en", "pt") else None
        self.quality = quality if quality in MODELS else "base"
        self.status, self.phase, self.percent, self.error, self.blocks, self.heard = "running", "model", 0.0, "", [], ""
        self.cancelled = False

    def _progress(self, value: float) -> None:
        self.percent = value

    def run(self) -> None:
        from ectube_asr import download_model, model_dir, model_ready, transcribe

        try:
            if not model_ready(HOME, self.quality):
                self.phase = "model"
                try:
                    download_model(HOME, self.quality, self._progress, lambda: self.cancelled, f"EC-Tube/{APP_VERSION}")
                except InterruptedError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    log(f"[oído] no se pudo bajar: {exc}")
                    raise RuntimeError("No se pudo bajar el «oído» (¿sin internet?). Intenta otra vez.") from exc
            self.phase, self.percent = "decode", 0.0
            audio = _audio_16k(self.source)
            if self.cancelled:
                raise InterruptedError
            self.phase = "listen"
            log(f"[oído {self.id}] {self.source.name} ({len(audio) / 16000:.0f} s, {self.quality}, {self.lang or 'auto'})")
            self.blocks, self.heard = transcribe(audio, model_dir(HOME, self.quality), self.lang, self._progress, lambda: self.cancelled)
            if not self.blocks:
                raise RuntimeError("No se escuchó voz en el video.")
            self.status = "done"
        except InterruptedError:
            self.status = "cancelled"
        except Exception as exc:  # noqa: BLE001
            self.status, self.error = "error", str(exc)
            log(f"[oído {self.id}] error: {exc}")

    def public(self) -> dict:
        return {"id": self.id, "status": self.status, "phase": self.phase, "percent": round(self.percent, 1), "error": self.error,
                "blocks": self.blocks if self.status == "done" else [], "lang": self.heard}


ASR_JOBS: dict[str, AsrJob] = {}


# ---------- voz guía (para «ajustar a la voz») ----------
GUIDES: dict[str, dict] = {}
GUIDES_LOCK = threading.Lock()


def _decode_audio(path: Path, channels: int = 2):
    import numpy as np

    if not FFMPEG:
        raise RuntimeError("No se encontró FFmpeg.")
    result = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(path), "-vn",
                             "-f", "f32le", "-ac", str(channels), "-ar", "44100", "pipe:1"],
                            capture_output=True, creationflags=_no_window_flags(), timeout=600)
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError("No se pudo leer el audio de " + path.name)
    data = np.frombuffer(result.stdout, dtype="<f4")
    return data.reshape(-1, channels).T.copy() if channels > 1 else data.copy()


def _guide_key(path: Path) -> str:
    stat = path.stat()
    return hashlib.sha1(f"{path}|{stat.st_size}|{int(stat.st_mtime)}".encode()).hexdigest()[:16]


def guess_guide(source: Path) -> Path | None:
    """Si la pista del karaoke la hiciste con EC-Tube («X (música).mp3»), buscar la canción original «X.*»."""
    match = re.match(r"^(.*) \((?:música|music)(?: \d+)?\)$", source.stem)
    if not match:
        return None
    stem = match.group(1)
    folders = [Path(CONFIG.get(key) or "") for key in ("audio_folder", "video_folder", "audio_edited_folder", "video_edited_folder")]
    folders += [source.parent, *(Path.home() / base / name for base in ("Music", "Videos", "Downloads")
                                 for name in ("EC-Tube", "EC-Tube Editados"))]  # también las carpetas de antes
    for folder in folders:
        if folder.is_dir():
            for ext in sorted(AUDIO_EXTS | VIDEO_EXTS):
                candidate = folder / f"{stem}{ext}"
                if candidate.is_file() and candidate != source:
                    return candidate
    return None


class Guide:
    """Separa la voz de la canción original una vez y guarda solo su «volumen en el tiempo» (pesa poquito)."""

    def __init__(self, path: Path) -> None:
        self.path, self.key = path, _guide_key(path)
        self.state, self.percent, self.error = "preparing", 0.0, ""
        self.env = None
        self.offsets: dict[str, float] = {}
        self.mix_env = None

    def public(self) -> dict:
        return {"state": self.state, "percent": round(self.percent), "error": self.error, "name": self.path.name}

    def run(self) -> None:
        import numpy as np

        from ectube_karaoke import voice_envelope

        cache = KARAOKE_DIR / "guides" / f"{self.key}.npz"
        try:
            if cache.is_file():
                data = np.load(cache)
                self.env, self.mix_env = data["env"], data["mix"]
            else:
                mix = _decode_audio(self.path)
                self.percent = 5
                if mix.shape[1] > 15 * 60 * 44100:
                    raise RuntimeError("La canción guía dura más de 15 minutos.")
                mdx = _separator(lambda f: setattr(self, "percent", 5 + f * 5), lambda: False)
                vocals = mdx.vocals(mix, progress=lambda f: setattr(self, "percent", 10 + f * 88))
                self.env = voice_envelope(vocals.mean(axis=0))
                self.mix_env = voice_envelope(mix.mean(axis=0))
                cache.parent.mkdir(parents=True, exist_ok=True)
                np.savez_compressed(cache, env=self.env, mix=self.mix_env)
            from ectube_karaoke import clean_voice

            self.env = clean_voice(self.env, self.mix_env)  # solo donde de verdad se canta
            self.state, self.percent = "ready", 100
            log(f"[karaoke] voz guía lista: {self.path.name}")
        except Exception as exc:  # noqa: BLE001
            self.state, self.error = "error", str(exc)
            log(f"[karaoke] voz guía: {exc}")

    def offset_for(self, source: Path) -> float:
        """Corrimiento entre la canción guía y la pista del karaoke (0 si son la misma o no se puede saber)."""
        from ectube_karaoke import estimate_offset, voice_envelope

        if source == self.path:
            return 0.0
        key = str(source)
        if key not in self.offsets:
            try:
                self.offsets[key] = estimate_offset(self.mix_env, voice_envelope(_decode_audio(source, 1)))
            except Exception as exc:  # noqa: BLE001
                log(f"[karaoke] corrimiento: {exc}")
                self.offsets[key] = 0.0
            log(f"[karaoke] corrimiento guía→pista: {self.offsets[key]:+.2f} s")
        return self.offsets[key]


def guide_for(path: Path) -> Guide:
    with GUIDES_LOCK:
        guide = GUIDES.get(str(path))
        if guide is None or guide.key != _guide_key(path) or guide.state == "error":
            guide = Guide(path)
            GUIDES[str(path)] = guide
            threading.Thread(target=guide.run, daemon=True).start()
        return guide


WAVES: dict[str, str] = {}


def _env_bytes(env) -> str:
    import base64

    import numpy as np

    level = np.clip((np.asarray(env, dtype=np.float32) + 60) / 60, 0, 1) * 255
    return base64.b64encode(level.astype(np.uint8).tobytes()).decode()


def karaoke_wave(source: Path, guide_path: Path | None) -> dict:
    """Formas de onda para la línea de tiempo (100 por segundo, 0-255): la pista y, si hay, la voz guía."""
    import numpy as np

    from ectube_karaoke import ENV_RATE, voice_envelope

    key = f"{source}|{source.stat().st_mtime}"
    if key not in WAVES:
        WAVES[key] = _env_bytes(voice_envelope(_decode_audio(source, 1)))
    voice = None
    if guide_path and guide_path.is_file():
        guide = guide_for(guide_path)
        if guide.state == "ready":
            shift = int(round(guide.offset_for(source) * ENV_RATE))
            env = guide.env
            env = np.concatenate([np.full(shift, -90, np.float32), env]) if shift >= 0 else env[-shift:]
            voice = _env_bytes(env)
    return {"rate": ENV_RATE, "music": WAVES[key], "voice": voice}


def karaoke_autosync(guide_path: Path, source: Path, lines: list) -> list:
    from ectube_karaoke import auto_align

    guide = guide_for(guide_path)
    if guide.state != "ready":
        raise RuntimeError("La voz guía todavía se está preparando.")
    shift = guide.offset_for(source)
    texts = [[str(t)[:80] for t in (line or [])[:200]] for line in lines[:1000]]
    result = auto_align(guide.env, texts)
    return [[[round(float(s + shift), 3), round(float(e + shift), 3)] for s, e in line] if line else None
            for line in result]


def karaoke_align(guide_path: Path, source: Path, lines: list[dict]) -> list:
    from ectube_karaoke import align_line

    guide = guide_for(guide_path)
    if guide.state != "ready":
        raise RuntimeError("La voz guía todavía se está preparando.")
    shift = guide.offset_for(source)
    result = []
    for line in lines[:1000]:
        units = [{"text": str(u.get("text") or "")} for u in (line.get("units") or [])[:200]]
        try:
            start, end = float(line.get("start")), float(line.get("end"))
        except (TypeError, ValueError):
            result.append(None)
            continue
        strict = bool(line.get("strict"))  # tiempos escritos a mano: entra y sale EXACTO donde dijo el usuario
        times = align_line(guide.env, units, start - shift, end - shift, pad=(0.0, 0.0) if strict else (0.30, 0.45))
        if times and strict:
            lo, hi = start - shift, end - shift
            times = [(min(max(s, lo), hi - 0.05), min(max(e, lo + 0.05), hi)) for s, e in times]
            times[0] = (lo, max(times[0][1], lo + 0.05))
            times[-1] = (min(times[-1][0], hi - 0.05), hi)
        result.append([[round(float(s + shift), 3), round(float(e + shift), 3)] for s, e in times] if times else None)
    return result


def pick_files(initial: str, title: tuple[str, str] | None = None, exts: set | None = None) -> list[str]:
    """Elegir varias canciones para el reproductor (o varios archivos de los tipos de `exts`)."""
    if not IS_WINDOWS:
        return []
    exts = exts or (AUDIO_EXTS | VIDEO_EXTS)
    patterns = ";".join("*" + ext for ext in sorted(exts))
    english = current_language() == "en"
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost=$true; ShowInTaskbar=$false; Opacity=0; StartPosition='CenterScreen'}; $owner.Show(); $owner.Activate();"
        "$d = New-Object System.Windows.Forms.OpenFileDialog; $d.Multiselect = $true;"
        f"$d.Title = '{(title or ('Choose songs for the list', 'Elige canciones para la lista'))[0 if english else 1]}';"
        f"$d.Filter = '{english and 'Files' or 'Archivos'}|{patterns}|{english and 'All files' or 'Todos los archivos'}|*.*';"
        f"$d.InitialDirectory = '{initial.replace(chr(39), chr(39) * 2)}';"
        "if ($d.ShowDialog($owner) -eq 'OK') { [Console]::OutputEncoding = [Text.Encoding]::UTF8; $d.FileNames -join \"`n\" }"
    )
    with PICK_LOCK:
        result = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", creationflags=_no_window_flags(),
                                timeout=600)
    return [line.strip() for line in result.stdout.splitlines()
            if line.strip() and Path(line.strip()).suffix.lower() in exts]


def pick_file(kind: str = "media") -> str | None:
    """Diálogo nativo de Windows para elegir un archivo de audio o video (o una imagen)."""
    if not IS_WINDOWS:
        return None
    exts = IMAGE_EXTS if kind == "image" else AUDIO_EXTS | VIDEO_EXTS
    patterns = ";".join("*" + ext for ext in sorted(exts))
    english = current_language() == "en"
    candidates = ([Path.home() / "Pictures"] if kind == "image" else
                  [CONFIG.get("audio_edited_folder"), CONFIG.get("video_edited_folder"), CONFIG.get("audio_folder"),
                   CONFIG.get("video_folder")] if kind == "karaoke" else [CONFIG.get("audio_folder")])
    initial = next((str(c) for c in candidates if c and Path(c).is_dir()), str(Path.home()))
    titles = {"image": ("Choose the background image", "Elige la imagen de fondo"),
              "karaoke": ("Choose the music (audio or video)", "Elige la música (audio o video)")}
    title = titles.get(kind, ("Choose the audio or video to trim", "Elige el audio o video que quieres recortar"))[0 if english else 1]
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost=$true; ShowInTaskbar=$false; Opacity=0; StartPosition='CenterScreen'}; $owner.Show(); $owner.Activate();"
        "$d = New-Object System.Windows.Forms.OpenFileDialog;"
        f"$d.Title = '{title}';"
        f"$d.Filter = '{english and ('Images' if kind == 'image' else 'Audio and video') or ('Imágenes' if kind == 'image' else 'Audio y video')}|{patterns}|{english and 'All files' or 'Todos los archivos'}|*.*';"
        f"$d.InitialDirectory = '{initial.replace(chr(39), chr(39) * 2)}';"
        "if ($d.ShowDialog($owner) -eq 'OK') { [Console]::OutputEncoding = [Text.Encoding]::UTF8; $d.FileName }"
    )
    with PICK_LOCK:
        result = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", creationflags=_no_window_flags(),
                                timeout=600)
    chosen = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else ""
    return chosen or None


# ---------------------------------------------------------------------------
# Elegir carpeta y abrir carpeta (Windows)
# ---------------------------------------------------------------------------
PICK_LOCK = threading.Lock()


def pick_folder(initial: str) -> str | None:
    """Diálogo nativo de Windows para elegir carpeta (vía PowerShell)."""
    if not IS_WINDOWS:
        return None
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost=$true; ShowInTaskbar=$false; Opacity=0; StartPosition='CenterScreen'}; $owner.Show(); $owner.Activate();"
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
        f"$d.Description = '{'Folder for EC-Tube downloads' if current_language() == 'en' else 'Carpeta para las descargas de EC-Tube'}';"
        "$d.ShowNewFolderButton = $true;"
        f"$d.SelectedPath = '{initial.replace(chr(39), chr(39) * 2)}';"
        "if ($d.ShowDialog($owner) -eq 'OK') { [Console]::OutputEncoding = [Text.Encoding]::UTF8; $d.SelectedPath }"
    )
    with PICK_LOCK:
        result = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script], capture_output=True,
                                text=True, encoding="utf-8", errors="replace", creationflags=_no_window_flags(),
                                timeout=600)
    chosen = result.stdout.strip().splitlines()[-1].strip() if result.stdout.strip() else ""
    return chosen or None


def open_in_explorer(path: Path, select: bool = False) -> None:
    if IS_WINDOWS:
        if select and path.is_file():
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            os.startfile(str(path if path.is_dir() else path.parent))  # type: ignore[attr-defined]
    else:
        opener = shutil.which("xdg-open")
        if opener:
            subprocess.Popen([opener, str(path if path.is_dir() else path.parent)])


# ---------------------------------------------------------------------------
# Ventana
# ---------------------------------------------------------------------------
def _app_browser() -> str | None:
    if not IS_WINDOWS:
        return shutil.which("chromium") or shutil.which("google-chrome")
    bases = [os.environ.get(name) for name in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for rel in (Path("Microsoft/Edge/Application/msedge.exe"), Path("Google/Chrome/Application/chrome.exe")):
        for base in bases:
            if base and (Path(base) / rel).is_file():
                return str(Path(base) / rel)
    return None


def open_app_window(url: str) -> None:
    browser = _app_browser()
    if browser:
        with contextlib.suppress(OSError):
            subprocess.Popen([browser, f"--app={url}", "--window-size=1100,820"], close_fds=True)
            return
    webbrowser.open(url)


# ---------------------------------------------------------------------------
# Servidor HTTP
# ---------------------------------------------------------------------------
LAST_PING = time.time()
IDLE_EXIT_SECONDS = 90  # sin ventana abierta ni descargas → se cierra solo


class Handler(BaseHTTPRequestHandler):
    port = DEFAULT_PORT
    server_version = "EC-Tube"
    sys_version = ""
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt: str, *args) -> None:  # noqa: ANN002
        if "/api/jobs" in (args[0] if args else "") and '"GET' in fmt % args:
            return  # el sondeo de la lista llenaría el registro
        text = fmt % args
        if "/api/ping" in text or '"GET /media/' in text or '"GET /api/trim/' in text or '"GET /api/edit/' in text:
            return
        log("HTTP " + (fmt % args))

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    # ---------- seguridad (igual que EC-Cam) ----------
    def _local_request(self) -> bool:
        try:
            if not ipaddress.ip_address(self.client_address[0]).is_loopback:
                return False
        except ValueError:
            return False
        host = urlsplit("//" + (self.headers.get("Host") or "")).hostname or ""
        return host.lower() in LOCAL_HOSTS

    def _same_origin_post(self) -> bool:
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            return False
        origin = self.headers.get("Origin")
        if not origin:
            return True
        parts = urlsplit(origin)
        return (parts.hostname or "").lower() in LOCAL_HOSTS and parts.port == self.port

    # ---------- respuestas ----------
    def send_json(self, data: object, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path: Path, data: bytes | None = None) -> None:
        data = path.read_bytes() if data is None else data
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if path.suffix == ".html":
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' https: data:; style-src 'self' 'unsafe-inline'; "
                             "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 4 * 1024 * 1024:
            raise ValueError("demasiado grande")
        data = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(data, dict):
            raise ValueError("JSON inválido")
        return data

    # ---------- GET ----------
    def do_GET(self) -> None:  # noqa: N802
        global LAST_PING
        if not self._local_request():
            self.send_error(403)
            return
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            lang = current_language(self.headers.get("Accept-Language") or "")
            html = (WEB_ROOT / "index.html").read_text(encoding="utf-8").replace('<html lang="es">', f'<html lang="{lang}">', 1)
            self.send_file(WEB_ROOT / "index.html", html.encode("utf-8"))
        elif path == "/api/info":
            LAST_PING = time.time()
            self.send_json({
                "version": APP_VERSION, "build_date": BUILD_DATE,
                "engine": ENGINE.version, "engine_updating": ENGINE.updating,
                "engine_message": ENGINE.last_update_message,
                "ffmpeg": bool(FFMPEG), "deno": bool(DENO),
                "settings": {k: v for k, v in CONFIG.items() if k != "port"},
            })
        elif path == "/api/jobs":
            LAST_PING = time.time()
            self.send_json({"jobs": DOWNLOADS.list(), "engine_updating": ENGINE.updating})
        elif path.startswith("/media/"):
            self._send_media(path.rsplit("/", 1)[-1])
            return
        elif path.startswith("/api/edit/"):
            job = EDITS.get(path.rsplit("/", 1)[-1])
            if job:
                self.send_json(job.public())
            else:
                self.send_json({"ok": False, "error": "No existe esa edición."}, 404)
        elif path.startswith("/api/trim/"):
            job = TRIMS.get(path.rsplit("/", 1)[-1])
            if job:
                self.send_json(job.public())
            else:
                self.send_json({"ok": False, "error": "No existe ese recorte."}, 404)
        elif path == "/api/ping":
            LAST_PING = time.time()
            self.send_json({"ok": True})
        elif path == "/api/update":
            UPDATER.check()  # si ya pasó una hora desde la última vez, vuelve a buscar (la ventana pregunta seguido)
            self.send_json(UPDATER.public())
        elif path == "/api/library":
            query = parse_qs(urlsplit(self.path).query)
            where, kind = query.get("where", ["downloads"])[0], query.get("kind", ["audio"])[0]
            self.send_json({"ok": True, **library("edited" if where == "edited" else "downloads", kind)})
        elif path == "/api/playlists":
            self.send_json({"ok": True, **playlists_public(load_playlists())})
        elif path == "/api/karaoke/projects":
            self.send_json({"ok": True, "projects": karaoke_list()})
        elif path == "/api/karaoke/project":
            try:
                self.send_json({"ok": True, "project": karaoke_public(karaoke_load(parse_qs(urlsplit(self.path).query).get("id", [""])[0]))})
            except (ValueError, OSError, json.JSONDecodeError):
                self.send_json({"ok": False, "error": "No se encontró ese karaoke."}, 404)
        elif path.startswith("/api/karaoke/export/"):
            job = KARAOKE_JOBS.get(path.rsplit("/", 1)[-1])
            self.send_json(job.public() if job else {"ok": False, "error": "No existe esa exportación."}, 200 if job else 404)
        elif path == "/api/subs/projects":
            self.send_json({"ok": True, "projects": subs_list()})
        elif path == "/api/subs/project":
            try:
                self.send_json({"ok": True, "project": subs_public(subs_load(parse_qs(urlsplit(self.path).query).get("id", [""])[0]))})
            except (ValueError, OSError, json.JSONDecodeError):
                self.send_json({"ok": False, "error": "No se encontró ese proyecto de subtítulos."}, 404)
        elif path.startswith("/api/subs/fetch/"):
            job = SUBS_FETCHES.get(path.rsplit("/", 1)[-1])
            self.send_json(job.public() if job else {"ok": False, "error": "No existe esa búsqueda."}, 200 if job else 404)
        elif path == "/api/subs/asr":
            from ectube_asr import MODELS, model_ready

            self.send_json({"ok": True, "models": {q: {"ready": model_ready(HOME, q), "mb": mb} for q, (_, mb) in MODELS.items()}})
        elif path.startswith("/api/subs/auto/"):
            job = ASR_JOBS.get(path.rsplit("/", 1)[-1])
            self.send_json(job.public() if job else {"ok": False, "error": "No existe ese trabajo."}, 200 if job else 404)
        elif path.startswith("/api/compat/"):
            job = COMPAT_JOBS.get(path.rsplit("/", 1)[-1])
            self.send_json(job.public() if job else {"ok": False, "error": "No existe ese trabajo."}, 200 if job else 404)
        elif path.startswith("/api/subs/export/"):
            job = SUBS_JOBS.get(path.rsplit("/", 1)[-1])
            self.send_json(job.public() if job else {"ok": False, "error": "No existe esa exportación."}, 200 if job else 404)
        elif path == "/api/anims":
            self.send_json({"ok": True, **anims_public()})
        elif path == "/api/bank/status":
            self.send_json({"ok": True, **bank_status()})
        elif path.startswith(("/anim/", "/banco/", "/mis-animaciones/")):
            prefix = {"anim": "a", "banco": "k", "mis-animaciones": "u"}[path.split("/")[1]]
            target = anim_path(prefix + "/" + unquote(path.rsplit("/", 1)[-1]))
            if target:
                self._send_path(target)
            else:
                self.send_error(404)
            return
        elif path == "/api/effects":
            self.send_json({"ok": True, **effects_public()})
        elif path.startswith(("/efectos/", "/mis-efectos/")):
            fx = effect_path(("b/" if path.startswith("/efectos/") else "m/") + unquote(path.rsplit("/", 1)[-1]))
            if fx:
                self.send_file(fx)
            else:
                self.send_error(404)
        elif path.startswith("/img/") or path in ("/app.js", "/style.css", "/favicon.ico"):
            target = (WEB_ROOT / path.lstrip("/")).resolve()
            if WEB_ROOT.resolve() in target.parents and target.is_file():
                self.send_file(target)
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    # ---------- POST ----------
    def do_POST(self) -> None:  # noqa: N802
        if not self._local_request() or not self._same_origin_post():
            self.send_json({"ok": False, "error": "Solicitud rechazada."}, 403)
            return
        try:
            data = self.read_json()
        except (ValueError, json.JSONDecodeError):
            self.send_json({"ok": False, "error": "Solicitud inválida."}, 400)
            return
        path = urlsplit(self.path).path
        match = re.fullmatch(r"/api/jobs/([0-9a-f]{12})/(cancel|retry|remove|open|reveal)", path)
        if path == "/api/jobs":
            self._add_jobs(data)
        elif path == "/api/settings":
            self._save_settings(data)
            self.send_json({"ok": True, "settings": {k: v for k, v in CONFIG.items() if k != "port"}})
        elif path == "/api/jobs/clear":
            DOWNLOADS.clear_finished()
            self.send_json({"ok": True})
        elif match:
            self._job_action(match.group(1), match.group(2))
        elif path == "/api/pick-folder":
            kind = "video" if data.get("kind") == "video" else "audio"
            key = ("karaoke_folder" if data.get("which") == "karaoke" else
                   f"{kind}_edited_folder" if data.get("which") == "edited" else f"{kind}_folder")
            chosen = pick_folder(CONFIG[key])
            if chosen:
                CONFIG[key] = chosen
                save_config(CONFIG)
            self.send_json({"ok": True, "folder": CONFIG[key], "changed": bool(chosen),
                            "settings": {k: v for k, v in CONFIG.items() if k != "port"}})
        elif path == "/api/open-folder":
            kind = "video" if data.get("kind") == "video" else "audio"
            key = ("karaoke_folder" if data.get("which") == "karaoke" else
                   f"{kind}_edited_folder" if data.get("which") == "edited" else f"{kind}_folder")
            folder = Path(CONFIG[key])
            folder.mkdir(parents=True, exist_ok=True)
            open_in_explorer(folder)
            self.send_json({"ok": True})
        elif path == "/api/anims/add":
            from ectube_overlay import IMPORT_EXTS

            chosen = pick_files(str(Path.home() / "Pictures" if (Path.home() / "Pictures").is_dir() else Path.home()),
                                ("Choose your animations (GIF, WebP, PNG, WebM…)", "Elige tus animaciones (GIF, WebP, PNG, WebM…)"),
                                IMPORT_EXTS)
            result = anims_add(chosen) if chosen else {"added": 0, "errors": []}
            self.send_json({"ok": True, **result, **anims_public()})
        elif path == "/api/anims/remove":
            try:
                anims_remove(str(data.get("id") or ""))
                self.send_json({"ok": True, **anims_public()})
            except (ValueError, OSError) as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
        elif path == "/api/bank/download":
            bank_download()
            self.send_json({"ok": True, **bank_status()})
        elif path == "/api/bank/dismiss":
            CONFIG["bank_dismissed"] = int(BANK.get("latest") or 0)
            save_config(CONFIG)
            self.send_json({"ok": True})
        elif path == "/api/effects/add":
            chosen = pick_files(str(Path.home() / "Music" if (Path.home() / "Music").is_dir() else Path.home()),
                                ("Choose your sounds (one or several)", "Elige tus sonidos (uno o varios)"))
            try:
                result = effects_add(chosen) if chosen else {"added": 0, "errors": []}
                self.send_json({"ok": True, **result, **effects_public()})
            except RuntimeError as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
        elif path == "/api/effects/remove":
            try:
                effects_remove(str(data.get("id") or ""))
                self.send_json({"ok": True, **effects_public()})
            except (ValueError, OSError) as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
        elif path == "/api/pick-file":
            chosen = pick_file()
            if not chosen:
                self.send_json({"ok": True, "media": None})
            elif Path(chosen).suffix.lower() not in AUDIO_EXTS | VIDEO_EXTS:
                self.send_json({"ok": False, "error": "Ese archivo no es de audio o video compatible."}, 400)
            else:
                self.send_json({"ok": True, "media": media_info(Path(chosen))})
        elif path == "/api/karaoke/save":
            try:
                self.send_json({"ok": True, "project": karaoke_save(data)})
            except (ValueError, OSError) as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
        elif path == "/api/karaoke/delete":
            with contextlib.suppress(ValueError, OSError):
                _karaoke_path(str(data.get("id") or "")).unlink()
            self.send_json({"ok": True})
        elif path == "/api/karaoke/pick":
            kind = "image" if data.get("kind") == "image" else "karaoke"
            chosen = pick_file(kind)
            if not chosen:
                self.send_json({"ok": True, "media": None})
            elif Path(chosen).suffix.lower() not in (IMAGE_EXTS if kind == "image" else AUDIO_EXTS | VIDEO_EXTS):
                self.send_json({"ok": False, "error": "Ese archivo no es compatible."}, 400)
            else:
                self.send_json({"ok": True, "media": media_info(Path(chosen))})
        elif path == "/api/karaoke/guide":
            # Preparar (o ver cómo va) la voz guía. Si no se da, adivinarla a partir de la pista.
            source = MEDIA.path(str(data.get("source_token") or "")) if data.get("source_token") else None
            guide_path = MEDIA.path(str(data.get("guide_token") or "")) if data.get("guide_token") else None
            if guide_path is None and source is not None and data.get("guess"):
                guide_path = guess_guide(source)
            if guide_path is None or not guide_path.is_file():
                self.send_json({"ok": True, "guide": None})
            else:
                guide = guide_for(guide_path) if data.get("prepare", True) else None
                self.send_json({"ok": True, "guide": {**media_info(guide_path), **(guide.public() if guide else {})}})
        elif path == "/api/karaoke/from-song":
            # Canción con voz → EC-Tube saca la pista sin voz (y de paso la voz guía).
            source = MEDIA.path(str(data.get("token") or ""))
            if not source or not source.is_file():
                self.send_json({"ok": False, "error": "El archivo ya no está en su carpeta."}, 404)
                return
            duration = _media_duration(source)
            if duration < 1:
                self.send_json({"ok": False, "error": "No se pudo leer la duración de la canción."}, 400)
                return
            job = TrimJob(source, 0.0, duration, "music")
            job.save_guide = True
            TRIMS[job.id] = job
            threading.Thread(target=job.run, daemon=True).start()
            self.send_json({"ok": True, **job.public()})
        elif path == "/api/karaoke/wave":
            source = MEDIA.path(str(data.get("source_token") or ""))
            guide_path = MEDIA.path(str(data.get("guide_token") or "")) if data.get("guide_token") else None
            if not source or not source.is_file():
                self.send_json({"ok": False, "error": "Falta la pista."}, 400)
                return
            try:
                self.send_json({"ok": True, **karaoke_wave(source, guide_path)})
            except RuntimeError as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
        elif path == "/api/karaoke/autosync":
            source = MEDIA.path(str(data.get("source_token") or ""))
            guide_path = MEDIA.path(str(data.get("guide_token") or ""))
            if not source or not guide_path:
                self.send_json({"ok": False, "error": "Falta la pista o la voz guía."}, 400)
                return
            try:
                self.send_json({"ok": True, "lines": karaoke_autosync(guide_path, source, data.get("lines") or [])})
            except RuntimeError as exc:
                self.send_json({"ok": False, "error": str(exc)}, 409)
        elif path == "/api/karaoke/align":
            source = MEDIA.path(str(data.get("source_token") or ""))
            guide_path = MEDIA.path(str(data.get("guide_token") or ""))
            if not source or not guide_path:
                self.send_json({"ok": False, "error": "Falta la pista o la voz guía."}, 400)
                return
            try:
                self.send_json({"ok": True, "lines": karaoke_align(guide_path, source, data.get("lines") or [])})
            except RuntimeError as exc:
                self.send_json({"ok": False, "error": str(exc)}, 409)
        elif path == "/api/karaoke/export":
            try:
                job = KaraokeExport(karaoke_load(str(data.get("id") or "")), str(data.get("format") or "16:9"))
            except (ValueError, OSError, json.JSONDecodeError, RuntimeError) as exc:
                self.send_json({"ok": False, "error": str(exc) if isinstance(exc, RuntimeError) else "Guarda el karaoke primero."}, 400)
                return
            KARAOKE_JOBS[job.id] = job
            threading.Thread(target=job.run, daemon=True).start()
            self.send_json({"ok": True, **job.public()})
        elif re.fullmatch(r"/api/karaoke/export/[0-9a-f]{12}/(cancel|reveal)", path):
            job = KARAOKE_JOBS.get(path.split("/")[4])
            if not job:
                self.send_json({"ok": False, "error": "No existe esa exportación."}, 404)
            elif path.endswith("cancel"):
                job.cancelled = True
                if job.process:
                    _kill_tree(job.process)
                self.send_json({"ok": True})
            else:
                open_in_explorer(job.output if job.output.exists() else Path(CONFIG["karaoke_folder"]), select=True)
                self.send_json({"ok": True})
        elif path == "/api/subs/save":
            try:
                self.send_json({"ok": True, "project": subs_save(data)})
            except (ValueError, OSError) as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
        elif path == "/api/subs/delete":
            with contextlib.suppress(ValueError, OSError):
                _subs_path(str(data.get("id") or "")).unlink()
            self.send_json({"ok": True})
        elif path == "/api/subs/pick":
            chosen = pick_file()
            if not chosen:
                self.send_json({"ok": True, "media": None})
            elif Path(chosen).suffix.lower() not in VIDEO_EXTS:
                self.send_json({"ok": False, "error": "Elige un video (los subtítulos van encima de un video)."}, 400)
            else:
                self.send_json({"ok": True, "media": media_info(Path(chosen)), "url": source_url(Path(chosen))})
        elif path == "/api/subs/source-url":
            found = MEDIA.path(str(data.get("token") or ""))
            self.send_json({"ok": True, "url": source_url(found) if found else ""})
        elif path == "/api/subs/download":
            url = str(data.get("url") or "").strip()
            if not re.match(r"https?://", url):
                self.send_json({"ok": False, "error": "Pega un enlace válido (https://…)."}, 400)
                return
            job = DOWNLOADS.add([url], {"kind": "video", "audio_format": CONFIG["audio_format"], "audio_quality": CONFIG["audio_quality"],
                                        "video_quality": CONFIG["video_quality"], "folder": CONFIG["video_folder"], "playlist": False})[0]
            self.send_json({"ok": True, "job": job.public()})
        elif path == "/api/compat":
            source = MEDIA.path(str(data.get("token") or ""))
            if not source or not needs_compat(source):
                self.send_json({"ok": True, "needed": False})
                return
            out = compat_path(source)
            if out.is_file():
                with contextlib.suppress(OSError):
                    os.utime(out)
                self.send_json({"ok": True, "needed": True, "media": media_info(out)})
                return
            job = next((j for j in COMPAT_JOBS.values() if j.source == source and j.status == "running"), None)
            if not job:
                job = CompatJob(source)
                COMPAT_JOBS[job.id] = job
                threading.Thread(target=job.run, daemon=True).start()
            info = probe(source)
            self.send_json({"ok": True, "needed": True, "job": job.public(), "hdr": info["hdr"], "codec": info["codec"]})
        elif path == "/api/subs/auto":
            source = MEDIA.path(str(data.get("token") or ""))
            if not source or not source.is_file():
                self.send_json({"ok": False, "error": "Primero elige el video."}, 400)
                return
            if any(j.status == "running" for j in ASR_JOBS.values()):
                self.send_json({"ok": False, "error": "Ya está escuchando otro video; espera a que termine."}, 400)
                return
            job = AsrJob(source, str(data.get("lang") or ""), str(data.get("quality") or "base"))
            ASR_JOBS[job.id] = job
            threading.Thread(target=job.run, daemon=True).start()
            self.send_json({"ok": True, **job.public()})
        elif re.fullmatch(r"/api/subs/auto/[0-9a-f]{12}/cancel", path):
            job = ASR_JOBS.get(path.split("/")[4])
            if job:
                job.cancelled = True
            self.send_json({"ok": True})
        elif path == "/api/subs/fetch":
            url = str(data.get("url") or "").strip()
            if not re.match(r"https?://", url):
                self.send_json({"ok": False, "error": "Pega el enlace de YouTube del video (https://…)."}, 400)
                return
            job = SubsFetch(url, str(data.get("lang") or "es"))
            SUBS_FETCHES[job.id] = job
            threading.Thread(target=job.run, daemon=True).start()
            self.send_json({"ok": True, **job.public()})
        elif path == "/api/subs/import":
            from ectube_subs import parse_srt

            chosen = pick_files(str(Path.home() / "Downloads"), ("Choose a subtitle file (.srt or .vtt)", "Elige un archivo de subtítulos (.srt o .vtt)"), {".srt", ".vtt"})
            if not chosen:
                self.send_json({"ok": True, "blocks": None})
            else:
                try:
                    blocks = parse_srt(Path(chosen[0]).read_text(encoding="utf-8-sig", errors="replace"))
                    self.send_json({"ok": True, "blocks": blocks})
                except OSError:
                    self.send_json({"ok": False, "error": "No se pudo leer ese archivo."}, 400)
        elif path == "/api/subs/srt":
            from ectube_subs import build_srt, timed

            try:
                project = subs_load(str(data.get("id") or ""))
            except (ValueError, OSError, json.JSONDecodeError):
                self.send_json({"ok": False, "error": "Guarda el proyecto primero."}, 400)
                return
            if not timed(project.get("blocks") or []):
                self.send_json({"ok": False, "error": "Todavía no hay subtítulos con tiempos."}, 400)
                return
            folder = Path(CONFIG["video_edited_folder"])
            folder.mkdir(parents=True, exist_ok=True)
            stem = re.sub(r'[<>:"/\\|?*]+', "", project.get("title") or Path(project.get("source") or "subtitulos").stem).strip() or "subtitulos"
            out = folder / f"{stem}.srt"
            out.write_text(build_srt(project["blocks"], bool((project.get("style") or {}).get("upper"))), encoding="utf-8")
            open_in_explorer(out, select=True)
            self.send_json({"ok": True, "output": out.name})
        elif path == "/api/subs/export":
            try:
                job = SubsExport(subs_load(str(data.get("id") or "")))
            except (ValueError, OSError, json.JSONDecodeError, RuntimeError) as exc:
                self.send_json({"ok": False, "error": str(exc) if isinstance(exc, RuntimeError) else "Guarda el proyecto primero."}, 400)
                return
            SUBS_JOBS[job.id] = job
            threading.Thread(target=job.run, daemon=True).start()
            self.send_json({"ok": True, **job.public()})
        elif re.fullmatch(r"/api/subs/export/[0-9a-f]{12}/(cancel|reveal)", path):
            job = SUBS_JOBS.get(path.split("/")[4])
            if not job:
                self.send_json({"ok": False, "error": "No existe esa exportación."}, 404)
            elif path.endswith("cancel"):
                job.cancelled = True
                if job.process:
                    _kill_tree(job.process)
                self.send_json({"ok": True})
            else:
                open_in_explorer(job.output if job.output.exists() else job.output.parent, select=job.output.exists())
                self.send_json({"ok": True})
        elif path == "/api/pick-songs":
            chosen = pick_files(CONFIG["audio_folder"])
            self.send_json({"ok": True, "items": [{"token": MEDIA.token_for(Path(p)), "name": Path(p).stem} for p in chosen]})
        elif path == "/api/playlists":
            try:
                self.send_json({"ok": True, **save_playlists(data)})
            except (ValueError, OSError) as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
        elif path in ("/api/file/open", "/api/file/reveal"):
            target = MEDIA.path(str(data.get("token") or ""))
            if not target or not target.is_file():
                self.send_json({"ok": False, "error": "El archivo ya no está en su carpeta."}, 404)
            elif path.endswith("open") and IS_WINDOWS:
                os.startfile(str(target))  # type: ignore[attr-defined]
                self.send_json({"ok": True})
            else:
                open_in_explorer(target, select=True)
                self.send_json({"ok": True})
        elif path == "/api/media-info":
            source = MEDIA.path(str(data.get("token") or ""))
            if not source or not source.is_file():
                self.send_json({"ok": False, "error": "El archivo ya no está en su carpeta."}, 404)
            else:
                self.send_json({"ok": True, "media": media_info(source)})
        elif path == "/api/trim":
            self._start_trim(data)
        elif path == "/api/peaks":
            source = MEDIA.path(str(data.get("token") or ""))
            if not source or not source.is_file():
                self.send_json({"ok": False, "error": "El archivo ya no está en su carpeta."}, 404)
            else:
                try:
                    self.send_json({"ok": True, **waveform(source, int(data.get("buckets") or 1600))})
                except Exception as exc:  # noqa: BLE001
                    self.send_json({"ok": False, "error": str(exc)}, 500)
        elif path == "/api/media-path":  # volver a abrir las fuentes de la edición guardada (si siguen en su carpeta)
            target = Path(str(data.get("path") or ""))
            ok = target.is_absolute() and target.suffix.lower() in AUDIO_EXTS | VIDEO_EXTS and target.is_file()
            self.send_json({"ok": True, "media": media_info(target)} if ok else
                           {"ok": False, "error": "El archivo ya no está en su carpeta."}, 200 if ok else 404)
        elif path == "/api/edit":
            self._start_edit(data)
        elif re.fullmatch(r"/api/edit/[0-9a-f]{12}/(cancel|reveal)", path):
            job = EDITS.get(path.split("/")[3])
            if not job:
                self.send_json({"ok": False, "error": "No existe esa edición."}, 404)
            elif path.endswith("cancel"):
                job.cancel()
                self.send_json({"ok": True})
            else:
                open_in_explorer(job.output if job.output.exists() else job.output.parent, select=job.output.exists())
                self.send_json({"ok": True})
        elif re.fullmatch(r"/api/trim/[0-9a-f]{12}/(cancel|reveal)", path):
            job = TRIMS.get(path.split("/")[3])
            if not job:
                self.send_json({"ok": False, "error": "No existe ese recorte."}, 404)
            elif path.endswith("cancel"):
                job.cancelled = True
                if job.process:
                    _kill_tree(job.process)
                self.send_json({"ok": True})
            else:
                open_in_explorer(job.output if job.output.exists() else job.source, select=True)
                self.send_json({"ok": True})
        elif path == "/api/update/check":
            UPDATER.check(force=True)
            self.send_json({"ok": True})
        elif path == "/api/update/install":
            try:
                UPDATER.install()
                self.send_json({"ok": True})
            except RuntimeError as exc:
                self.send_json({"ok": False, "error": str(exc)}, 400)
        elif path == "/api/engine/update":
            threading.Thread(target=ENGINE.update, kwargs={"force": True}, daemon=True).start()
            self.send_json({"ok": True})
        else:
            self.send_json({"ok": False, "error": "No encontrado."}, 404)

    def _fragments(self, raw, allowed: set) -> list | str:
        """Leer y revisar una lista de fragmentos. Regresa la lista o el error."""
        if not isinstance(raw, list) or not raw:
            return "Agrega al menos un fragmento."
        if len(raw) > 200:
            return "Son demasiados fragmentos (máximo 200)."
        out = []
        for item in raw:
            source = MEDIA.path(str((item or {}).get("token") or "")) if isinstance(item, dict) else None
            try:
                start, end = float(item.get("start")), float(item.get("end"))
            except (TypeError, ValueError, AttributeError):
                return "Tiempos inválidos."
            if not source or not source.is_file():
                return "El archivo ya no está en su carpeta."
            if source.suffix.lower() not in allowed:
                return "En la pista de video solo van videos."
            if start < 0 or end - start < 0.1:
                return "Cada fragmento debe durar al menos 0.1 segundos."
            out.append((source, start, end))
        return out

    def _effects(self, raw) -> list | str:
        """Leer y revisar los efectos de sonido. Regresa la lista o el error."""
        if not raw:
            return []
        if not isinstance(raw, list) or len(raw) > 200:
            return "Son demasiados efectos (máximo 200)."
        out = []
        for item in raw:
            path = effect_path((item or {}).get("id", "")) if isinstance(item, dict) else None
            if not path:
                return "Uno de los efectos ya no existe. Quítalo de la lista."
            try:
                at, start, end = float(item.get("at")), float(item.get("start")), float(item.get("end"))
                repeat, volume = int(item.get("repeat") or 1), float(item.get("volume") if item.get("volume") is not None else 1)
            except (TypeError, ValueError):
                return "Tiempos inválidos."
            end = min(end, probe(path)["duration"] or end)
            if at < 0 or start < 0 or end - start < 0.05:
                return "Cada efecto debe durar al menos 0.05 segundos."
            out.append({"path": path, "at": at, "start": start, "end": end,
                        "repeat": max(1, min(repeat, 50)), "volume": max(0.0, min(volume, 3.0)),
                        "extend": bool(item.get("extend"))})  # «al final de todo»: alarga la edición para que suene completo
        return out

    def _overlays(self, raw) -> list | str:
        """Leer y revisar las animaciones encima del video. Regresa la lista o el error."""
        if not raw:
            return []
        if not isinstance(raw, list) or len(raw) > 60:
            return "Son demasiadas animaciones (máximo 60)."
        out = []
        for item in raw:
            if not isinstance(item, dict):
                return "Animación inválida."
            try:
                at, dur = float(item.get("at")), float(item.get("dur"))
                x, y, w, h = (float(item.get(k)) for k in ("x", "y", "w", "h"))
            except (TypeError, ValueError):
                return "Tiempos o tamaño inválidos en una animación."
            if at < 0 or dur < 0.2 or dur > 600 or w <= 0.01 or h <= 0.01 or w > 4 or h > 4:
                return "Cada animación debe durar al menos 0.2 segundos y tener un tamaño válido."
            text = str(item.get("text") or "")[:300]
            if item.get("kind") == "banner":
                spec = {"kind": "banner", "text": text, "dur": dur, "color": str(item.get("color") or "#FE2C55")[:7],
                        "pop": item.get("pop") is not False}
            else:
                path = anim_path(item.get("id", ""))
                if not path:
                    return "Una de las animaciones ya no existe. Quítala de la lista."
                scene = SCENES.get(path.name) if path.parent != ANIM_MINE else None
                spec = {"kind": "anim", "path": str(path), "scene": scene, "text": text if scene else "", "dur": dur,
                        "pop": item.get("pop") is not False}
            out.append({"render": spec, "at": at, "x": x, "y": y, "w": w, "h": h})
        return out

    def _start_edit(self, data: dict) -> None:
        kind = "video" if data.get("kind") == "video" else "audio"
        fragments = self._fragments(data.get("fragments"), VIDEO_EXTS if kind == "video" else AUDIO_EXTS | VIDEO_EXTS)
        if isinstance(fragments, str):
            self.send_json({"ok": False, "error": fragments}, 400)
            return
        audio_mode = str(data.get("audio_mode") or "own")
        audio_fragments: list = []
        if kind == "video" and audio_mode == "other":
            audio_fragments = self._fragments(data.get("audio_fragments"), AUDIO_EXTS | VIDEO_EXTS)
            if isinstance(audio_fragments, str):
                self.send_json({"ok": False, "error": "Pista de audio: " + audio_fragments}, 400)
                return
        effects = self._effects(data.get("effects"))
        if isinstance(effects, str):
            self.send_json({"ok": False, "error": effects}, 400)
            return
        overlays = self._overlays(data.get("overlays")) if kind == "video" else []
        if isinstance(overlays, str):
            self.send_json({"ok": False, "error": overlays}, 400)
            return
        if sum(e - s for _, s, e in fragments) > 3 * 3600:
            self.send_json({"ok": False, "error": "La edición final puede durar máximo 3 horas."}, 400)
            return
        modes = [str((x or {}).get("mode") or "original") if isinstance(x, dict) else "original" for x in data.get("fragments") or []]
        amodes = [str((x or {}).get("mode") or "original") if isinstance(x, dict) else "original" for x in data.get("audio_fragments") or []]
        positions: list[float] | None = None
        try:  # capas: dónde empieza cada fragmento (si el usuario los separó o los enciman)
            raw = [x.get("pos") for x in data.get("fragments") or [] if isinstance(x, dict)]
            if len(raw) == len(fragments) and all(x is not None for x in raw):
                positions = [max(0.0, min(3 * 3600.0, float(x))) for x in raw]
        except (TypeError, ValueError):
            positions = None
        max_total = None
        cut = data.get("cut")
        if isinstance(cut, list) and len(cut) == 2:  # recortar la edición completa (inicio y final de todo)
            try:
                a, b = float(cut[0]), float(cut[1])
            except (TypeError, ValueError):
                a, b = 0.0, 0.0
            if b - a >= 0.1:
                max_total = b - a
                fragments, modes, positions = _cut_list(fragments, modes, a, b, positions)
                if audio_fragments:
                    audio_fragments, amodes, _ = _cut_list(audio_fragments, amodes, a, b)
                effects = [{**e, "at": e["at"] - a} for e in effects if a <= e["at"] < b]
                overlays = [{**o, "at": o["at"] - a} for o in overlays if a <= o["at"] < b]
                if not fragments:
                    self.send_json({"ok": False, "error": "El recorte de la edición final quedó vacío."}, 400)
                    return
        preview = bool(data.get("preview"))
        # una vista previa a la vez por «lugar»: la de la edición final («final») y la mezcla de un bloque («bloque»)
        slot = "bloque" if data.get("slot") == "bloque" else "final"
        if preview:
            for old in [j for j in EDITS.values() if j.preview and getattr(j, "slot", "final") == slot]:
                old.cancel()
                with contextlib.suppress(OSError):
                    old.output.unlink()
                EDITS.pop(old.id, None)
        try:
            job = EditJob(kind, fragments, str(data.get("mode") or "original"), data.get("smooth") is not False, preview,
                          audio_mode, audio_fragments, effects, overlays, modes, amodes, positions, max_total,
                          *((0.0, 0.0) if preview else (_num(data.get("fade_in")), _num(data.get("fade_out")))))
        except RuntimeError as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)
            return
        job.slot = slot
        EDITS[job.id] = job
        threading.Thread(target=job.run, daemon=True).start()
        self.send_json({"ok": True, **job.public()})

    def _start_trim(self, data: dict) -> None:
        source = MEDIA.path(str(data.get("token") or ""))
        try:
            start, end = float(data.get("start")), float(data.get("end"))
        except (TypeError, ValueError):
            self.send_json({"ok": False, "error": "Tiempos inválidos."}, 400)
            return
        if not source or not source.is_file():
            self.send_json({"ok": False, "error": "El archivo ya no está en su carpeta."}, 404)
            return
        if start < 0 or end - start < 0.2:
            self.send_json({"ok": False, "error": "El recorte debe durar al menos 0.2 segundos."}, 400)
            return
        try:
            job = TrimJob(source, start, end, str(data.get("mode") or "original"))
        except RuntimeError as exc:
            self.send_json({"ok": False, "error": str(exc)}, 400)
            return
        TRIMS[job.id] = job
        threading.Thread(target=job.run, daemon=True).start()
        self.send_json({"ok": True, **job.public()})

    def _send_media(self, token: str) -> None:
        """Servir el archivo con soporte de Range (para poder adelantar en el reproductor)."""
        self._send_path(MEDIA.path(token))

    def _send_path(self, source: Path | None) -> None:
        if not source or not source.is_file():
            self.send_error(404)
            return
        size = source.stat().st_size
        start, end = 0, size - 1
        header = self.headers.get("Range") or ""
        match = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
        partial = bool(match and (match.group(1) or match.group(2)))
        if partial:
            if match.group(1):
                start = int(match.group(1))
                if match.group(2):
                    end = min(int(match.group(2)), size - 1)
            else:
                start = max(0, size - int(match.group(2)))
            if start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
        length = end - start + 1
        self.send_response(206 if partial else 200)
        self.send_header("Content-Type", MEDIA_TYPES.get(source.suffix.lower(), "application/octet-stream"))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if partial:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        with contextlib.suppress(ConnectionError, OSError), source.open("rb") as handle:
            handle.seek(start)
            remaining = length
            while remaining > 0:
                chunk = handle.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    def _save_settings(self, data: dict) -> None:
        if data.get("kind") in ("audio", "video"):
            CONFIG["kind"] = data["kind"]
        if data.get("audio_format") in AUDIO_FORMATS:
            CONFIG["audio_format"] = data["audio_format"]
        if str(data.get("audio_quality")) in AUDIO_QUALITIES:
            CONFIG["audio_quality"] = str(data["audio_quality"])
        if str(data.get("video_quality")) in VIDEO_QUALITIES:
            CONFIG["video_quality"] = str(data["video_quality"])
        if isinstance(data.get("playlist"), bool):
            CONFIG["playlist"] = data["playlist"]
        if data.get("language") in ("es", "en"):
            CONFIG["language"] = data["language"]
        save_config(CONFIG)

    def _add_jobs(self, data: dict) -> None:
        self._save_settings(data)
        raw = data.get("urls")
        text = "\n".join(raw) if isinstance(raw, list) else str(raw or "")
        urls, seen = [], set()
        for token in re.split(r"\s+", text):
            token = token.strip().strip("<>\"'")
            if URL_RE.match(token) and token not in seen:
                seen.add(token)
                urls.append(token)
        if not urls:
            self.send_json({"ok": False, "error": "Pega al menos un enlace (que empiece con https://)."}, 400)
            return
        if len(urls) > 200:
            self.send_json({"ok": False, "error": "Máximo 200 enlaces a la vez."}, 400)
            return
        if not ytdlp_path():
            self.send_json({"ok": False, "error": "No se encontró el motor de descargas. Reinstala EC-Tube."}, 500)
            return
        kind = CONFIG["kind"]
        options = {"kind": kind, "audio_format": CONFIG["audio_format"], "audio_quality": CONFIG["audio_quality"],
                   "video_quality": CONFIG["video_quality"], "folder": CONFIG[f"{kind}_folder"],
                   "playlist": CONFIG["playlist"]}
        jobs = DOWNLOADS.add(urls, options)
        self.send_json({"ok": True, "added": len(jobs)})

    def _job_action(self, job_id: str, action: str) -> None:
        job = DOWNLOADS.get(job_id)
        if not job:
            self.send_json({"ok": False, "error": "Ya no existe esa descarga."}, 404)
            return
        if action == "cancel":
            self.send_json({"ok": DOWNLOADS.cancel(job_id)})
        elif action == "retry":
            self.send_json({"ok": DOWNLOADS.retry(job_id) is not None})
        elif action == "remove":
            DOWNLOADS.remove(job_id)
            self.send_json({"ok": True})
        elif action in ("open", "reveal"):
            target = Path(job.files[-1]) if job.files else Path(job.folder)
            if action == "open" and job.files and job.playlist:
                target = Path(job.files[-1]).parent
            if not target.exists():
                self.send_json({"ok": False, "error": "El archivo ya no está en esa carpeta."}, 404)
                return
            if action == "open" and target.is_file() and IS_WINDOWS:
                os.startfile(str(target))  # type: ignore[attr-defined]  # reproducir
            else:
                open_in_explorer(target, select=True)
            self.send_json({"ok": True})


def _update_blocker() -> str:
    trimming = any(job.status == "running" for job in [*TRIMS.values(), *KARAOKE_JOBS.values(), *EDITS.values(), *SUBS_JOBS.values(), *ASR_JOBS.values(), *COMPAT_JOBS.values()])
    return "Espera a que terminen las descargas y recortes." if DOWNLOADS.active() or trimming else ""


from ectube_update import Updater  # noqa: E402

UPDATER = Updater(app="EC-Tube", repo="EC-Tube", tag_prefix="v", current=APP_VERSION, folder=HOME / "updates", log=log,
                  busy=_update_blocker, extra_args=lambda: [f"/LANG={current_language()}"])


def _idle_watch(server: ThreadingHTTPServer) -> None:
    """Cerrar el servidor si la ventana se cerró y no hay descargas pendientes."""
    while True:
        time.sleep(15)
        trimming = any(job.status == "running" for job in [*TRIMS.values(), *KARAOKE_JOBS.values(), *EDITS.values(), *SUBS_JOBS.values(), *ASR_JOBS.values()])
        if time.time() - LAST_PING > IDLE_EXIT_SECONDS and not DOWNLOADS.active() and not trimming:
            log("Sin ventana abierta ni descargas: EC-Tube se cierra.")
            threading.Thread(target=server.shutdown, daemon=True).start()
            return


def _selftest_asr() -> int:
    """Prueba del «oído» en el programa ya compilado (la usa GitHub al armar el instalador)."""
    from ectube_asr import download_model, model_dir, transcribe

    out = Path(os.environ["ECTUBE_SELFTEST_OUT"])
    try:
        download_model(HOME, "base", lambda p: None, lambda: False)
        blocks, lang = transcribe(_audio_16k(Path(os.environ["ECTUBE_SELFTEST_ASR"])), model_dir(HOME, "base"), None,
                                  lambda p: None, lambda: False)
        out.write_text(json.dumps({"ok": True, "lang": lang, "blocks": blocks}, ensure_ascii=False), encoding="utf-8")
        return 0
    except Exception as exc:  # noqa: BLE001
        import traceback

        out.write_text(json.dumps({"ok": False, "error": f"{exc}", "trace": traceback.format_exc()}), encoding="utf-8")
        return 1


def main() -> int:
    if os.environ.get("ECTUBE_SELFTEST_ASR"):
        return _selftest_asr()
    parser = argparse.ArgumentParser(description=f"EC-Tube {APP_VERSION}")
    parser.add_argument("--port", type=int, help=f"puerto (por defecto {DEFAULT_PORT})")
    parser.add_argument("--no-browser", action="store_true", help="no abrir la ventana")
    parser.add_argument("--stay", action="store_true", help="no cerrarse al cerrar la ventana")
    parser.add_argument("--version", action="version", version=f"EC-Tube {APP_VERSION} {BUILD_DATE}".strip())
    args = parser.parse_args()

    port = args.port or int(CONFIG.get("port") or DEFAULT_PORT)
    url = f"http://127.0.0.1:{port}/"
    handler = type("EcTubeHandler", (Handler,), {"port": port})
    try:
        server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    except OSError:
        # Ya está abierto: solo mostrar la ventana.
        if not args.no_browser:
            open_app_window(url)
        return 0
    server.daemon_threads = True
    log(f"EC-Tube {APP_VERSION} ({BUILD_DATE or 'desarrollo'}) en {url}")
    log(f"yt-dlp: {ytdlp_path() or 'NO ENCONTRADO'} · FFmpeg: {FFMPEG or 'NO'} · Deno: {DENO or 'NO'}")
    ENGINE.refresh_version()
    threading.Thread(target=ENGINE.update, daemon=True).start()
    threading.Thread(target=clear_edit_tmp, daemon=True).start()
    reload_scenes()
    threading.Thread(target=bank_check, daemon=True).start()
    threading.Thread(target=clean_compat, daemon=True).start()
    if not args.stay:
        threading.Thread(target=_idle_watch, args=(server,), daemon=True).start()
    if not args.no_browser:
        threading.Timer(0.6, open_app_window, args=(url,)).start()
    threading.Timer(8, UPDATER.check).start()  # ¿hay versión nueva de EC-Tube?
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
