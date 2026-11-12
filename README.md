# EC-Tube

Descarga **audio y video** de YouTube (y de los demás sitios que soporta yt-dlp) en Windows, con una ventana sencilla: pegas el enlace, eliges formato y calidad, y listo.

- **Audio:** MP3 (128, 192 o 320 kbps), M4A (calidad original) o WAV. Con portada, título y artista dentro del archivo.
- **Video:** MP4 de 360p a 4K. Hasta 1080p usa H.264, que se reproduce en cualquier lado.
- Varias descargas a la vez, con progreso, cancelar y reintentar.
- **✂ Editor para recortar** el inicio y el final de un audio o video (lo que bajaste o cualquier archivo de tu PC). Guarda una copia «(recorte)» y no toca el original.
- Listas de reproducción completas (opcional), en una carpeta con el nombre de la lista.
- El motor (yt-dlp) se actualiza solo una vez al día, para que siga funcionando cuando YouTube cambia algo. También hay un botón **Actualizar motor**.
- Se cierra solo cuando cierras la ventana y no hay descargas pendientes.
- En **español o inglés** (🌐 en la app; también se elige en el instalador).

## Instalar

1. Descarga `EC-Tube-Setup-x.y.z.exe` de [Releases](../../releases/latest) y ejecútalo (no pide permisos de administrador).
2. Abre **EC-Tube** desde el escritorio.

Las descargas van por defecto a `Música\EC-Tube` (audio) y `Videos\EC-Tube` (video); se cambian con **Cambiar…**.

## Cómo está hecho

- `src/ectube_server.py`: servidor local (solo `127.0.0.1:8791`) que maneja la cola y corre `yt-dlp.exe`.
- `src/web/index.html`: la ventana (se abre con Edge en modo aplicación).
- `windows/build.ps1` + `windows/ectube.iss`: GitHub Actions descarga yt-dlp, Deno y FFmpeg, compila con PyInstaller y arma el instalador con Inno Setup. Cada versión nueva de `APP_VERSION` publica un Release.
- Datos: `%LOCALAPPDATA%\EC-Tube` (`config.json`, `bin\yt-dlp.exe`, `logs\ectube.log`).

## Componentes

- [yt-dlp](https://github.com/yt-dlp/yt-dlp) (Unlicense) — descargas.
- [Deno](https://deno.com) (MIT) — yt-dlp lo usa para resolver los retos de YouTube.
- [FFmpeg](https://ffmpeg.org) (GPL, build de gyan.dev) — conversión y unión de audio y video.

Uso personal. Descarga solo contenido tuyo, libre o con permiso de sus autores; los términos de YouTube no permiten descargar fuera de su app.
