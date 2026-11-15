"""Botón «Actualizar»: busca la versión nueva en los Releases del repo
público de la app (github.com/cesarmugica/<repo>), la baja, revisa su SHA-256 y corre
el instalador en silencio. Al bajarlo el programa (no Edge), Windows no
muestra el aviso de «no se descarga comúnmente».
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import subprocess
import threading
import time
import urllib.request
from pathlib import Path
from typing import Callable

RELEASES_API = "https://api.github.com/repos/cesarmugica/{repo}/releases?per_page=40"
CHECK_EVERY = 6 * 3600


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", text)[:3])


class Updater:
    def __init__(self, *, app: str, repo: str, tag_prefix: str, current: str, folder: Path, log: Callable[[str], None],
                 busy: Callable[[], str] = lambda: "", extra_args: Callable[[], list[str]] = lambda: []) -> None:
        self.app, self.repo, self.prefix, self.current = app, repo, tag_prefix, current
        self.folder, self.log, self.busy, self.extra_args = folder, log, busy, extra_args
        self.state = "idle"      # idle, checking, available, uptodate, downloading, installing, error
        self.latest = ""
        self.notes = ""
        self.asset_url = ""
        self.sums_url = ""
        self.asset_name = ""
        self.percent: float | None = None
        self.error = ""
        self.checked = 0.0
        self.lock = threading.Lock()

    def public(self) -> dict:
        return {"state": self.state, "current": self.current, "latest": self.latest, "notes": self.notes[:1500],
                "percent": None if self.percent is None else round(self.percent), "error": self.error,
                "busy": self.busy()}

    def _get(self, url: str, timeout: float = 20) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": f"{self.app}/{self.current}",
                                                       "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return response.read()

    # ---------- buscar ----------
    def check(self, force: bool = False) -> None:
        if self.state in ("downloading", "installing", "checking"):
            return
        if not force and time.time() - self.checked < CHECK_EVERY:
            return
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self) -> None:
        self.state, self.error = "checking", ""
        try:
            releases = json.loads(self._get(RELEASES_API.format(repo=self.repo)))
            best = None
            for release in releases:
                tag = release.get("tag_name") or ""
                if not tag.startswith(self.prefix) or release.get("draft") or release.get("prerelease"):
                    continue
                version = tag[len(self.prefix):]
                exe = next((a for a in release.get("assets", []) if a["name"].lower().endswith(".exe")), None)
                if exe and (best is None or _version_tuple(version) > _version_tuple(best[0])):
                    sums = next((a for a in release.get("assets", []) if a["name"].upper().startswith("SHA256")), None)
                    best = (version, exe, sums, release.get("body") or "")
            self.checked = time.time()
            if best and _version_tuple(best[0]) > _version_tuple(self.current):
                self.latest, exe, sums, self.notes = best[0], best[1], best[2], best[3]
                self.asset_url, self.asset_name = exe["browser_download_url"], exe["name"]
                self.sums_url = sums["browser_download_url"] if sums else ""
                self.state = "available"
                self.log(f"Actualización disponible: {self.app} {self.latest}")
            else:
                self.latest = best[0] if best else ""
                self.state = "uptodate"
        except Exception as exc:  # noqa: BLE001
            self.state, self.error = "error", "No se pudo buscar actualización (¿sin internet?)."
            self.log(f"Buscar actualización: {exc}")

    # ---------- instalar ----------
    def install(self) -> None:
        with self.lock:
            if self.state != "available":
                raise RuntimeError("No hay una versión nueva para instalar.")
            reason = self.busy()
            if reason:
                raise RuntimeError(reason)
            self.state, self.error, self.percent = "downloading", "", 0.0
        threading.Thread(target=self._install, daemon=True).start()

    def _install(self) -> None:
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            for old in self.folder.glob("*.exe"):
                with contextlib.suppress(OSError):
                    old.unlink()
            target = self.folder / self.asset_name
            tmp = target.with_suffix(".part")
            digest = hashlib.sha256()
            request = urllib.request.Request(self.asset_url, headers={"User-Agent": f"{self.app}/{self.current}"})
            with urllib.request.urlopen(request, timeout=60) as response, tmp.open("wb") as out:  # noqa: S310
                total = int(response.headers.get("Content-Length") or 0)
                got = 0
                while chunk := response.read(256 * 1024):
                    out.write(chunk)
                    digest.update(chunk)
                    got += len(chunk)
                    self.percent = got * 100 / total if total else None
            if self.sums_url:
                sums = self._get(self.sums_url).decode("utf-8", "replace")
                expected = next((line.split()[0].lower() for line in sums.splitlines()
                                 if self.asset_name.lower() in line.lower()), "")
                if expected and expected != digest.hexdigest():
                    tmp.unlink(missing_ok=True)
                    raise RuntimeError("El instalador se bajó dañado (no coincide su huella). Vuelve a intentar.")
            tmp.replace(target)
            self.state, self.percent = "installing", None
            self.log(f"Instalando {self.asset_name}…")
            # El instalador cierra este programa, se instala solo y lo vuelve a abrir.
            flags = 0
            if os.name == "nt":
                flags = getattr(subprocess, "DETACHED_PROCESS", 0x8) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
            subprocess.Popen([str(target), "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", *self.extra_args()],
                             close_fds=True,
                             creationflags=flags)
        except Exception as exc:  # noqa: BLE001
            self.state, self.error, self.percent = "available", str(exc), None
            self.log(f"Actualizar: {exc}")
