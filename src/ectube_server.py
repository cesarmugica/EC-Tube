"""EC-Tube — descargar audio y video de YouTube (y otros sitios) en la PC.

Servidor local (solo 127.0.0.1) con una página sencilla. Las descargas las
hace yt-dlp.exe (se actualiza solo una vez al día), con Deno para resolver
los retos de YouTube y FFmpeg para convertir/unir audio y video.
"""

from __future__ import annotations

import argparse
import contextlib
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
from urllib.parse import urlsplit

APP_VERSION = "1.0.0"

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
def _default_folder(kind: str) -> str:
    base = Path.home() / ("Music" if kind == "audio" else "Videos")
    if not base.is_dir():
        base = Path.home() / "Downloads"
    return str(base / "EC-Tube")


CONFIG_PATH = HOME / "config.json"
DEFAULT_CONFIG = {
    "port": DEFAULT_PORT,
    "kind": "audio",
    "audio_format": "mp3",
    "audio_quality": "320",
    "video_quality": "1080",
    "audio_folder": "",
    "video_folder": "",
    "playlist": False,
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
    config["audio_folder"] = config["audio_folder"] or _default_folder("audio")
    config["video_folder"] = config["video_folder"] or _default_folder("video")
    return config


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
        }

    # ---------- comando ----------
    def command(self) -> list[str]:
        path = ytdlp_path()
        if not path:
            raise RuntimeError("No se encontró el motor de descargas (yt-dlp).")
        name = "%(playlist_index)02d - %(title)s.%(ext)s" if self.playlist else "%(title)s.%(ext)s"
        output = ("%(playlist_title,playlist|Lista)s/" + name) if self.playlist else name
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
# Elegir carpeta y abrir carpeta (Windows)
# ---------------------------------------------------------------------------
PICK_LOCK = threading.Lock()


def pick_folder(initial: str) -> str | None:
    """Diálogo nativo de Windows para elegir carpeta (vía PowerShell)."""
    if not IS_WINDOWS:
        return None
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$owner = New-Object System.Windows.Forms.Form -Property @{TopMost=$true; ShowInTaskbar=$false};"
        "$d = New-Object System.Windows.Forms.FolderBrowserDialog;"
        "$d.Description = 'Carpeta para las descargas de EC-Tube';"
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
        if "/api/ping" in (fmt % args):
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

    def send_file(self, path: Path) -> None:
        data = path.read_bytes()
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
        if length > 256 * 1024:
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
            self.send_file(WEB_ROOT / "index.html")
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
        elif path == "/api/ping":
            LAST_PING = time.time()
            self.send_json({"ok": True})
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
            chosen = pick_folder(CONFIG[f"{kind}_folder"])
            if chosen:
                CONFIG[f"{kind}_folder"] = chosen
                save_config(CONFIG)
            self.send_json({"ok": True, "folder": CONFIG[f"{kind}_folder"], "changed": bool(chosen)})
        elif path == "/api/open-folder":
            kind = "video" if data.get("kind") == "video" else "audio"
            folder = Path(CONFIG[f"{kind}_folder"])
            folder.mkdir(parents=True, exist_ok=True)
            open_in_explorer(folder)
            self.send_json({"ok": True})
        elif path == "/api/engine/update":
            threading.Thread(target=ENGINE.update, kwargs={"force": True}, daemon=True).start()
            self.send_json({"ok": True})
        else:
            self.send_json({"ok": False, "error": "No encontrado."}, 404)

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


def _idle_watch(server: ThreadingHTTPServer) -> None:
    """Cerrar el servidor si la ventana se cerró y no hay descargas pendientes."""
    while True:
        time.sleep(15)
        if time.time() - LAST_PING > IDLE_EXIT_SECONDS and not DOWNLOADS.active():
            log("Sin ventana abierta ni descargas: EC-Tube se cierra.")
            threading.Thread(target=server.shutdown, daemon=True).start()
            return


def main() -> int:
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
    if not args.stay:
        threading.Thread(target=_idle_watch, args=(server,), daemon=True).start()
    if not args.no_browser:
        threading.Timer(0.6, open_app_window, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
