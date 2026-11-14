# Historial de versiones

## 2.0.1
- Al actualizar con «⬆ Actualizar», la ventana vieja se cierra sola (antes se quedaba abierta atrás de la nueva, sin funcionar).

## 2.0.0 — Separar voz y música
- **En el editor, «Qué guardar»:** ✂ Tal cual · 🎵 **Solo música** (quita la voz: pista para cantar) · 🎤 **Solo voz** (quita la música). Funciona con el tramo que elijas (o la canción completa) y con audio o video (el video se conserva, con el audio nuevo).
- Usa el separador MDX-Net «Kim Vocal 2» de UVR. Se baja solo la primera vez (~65 MB, con revisión de huella) y usa tu tarjeta de video con DirectML (NVIDIA, AMD o Intel); si no hay, el procesador (más lento).
- Se guarda en la carpeta de editados como «… (música)» o «… (voz)».
- Hasta 30 minutos por separación.
- *EN:* New “What to save” in the editor: as is / music only (remove vocals) / vocals only (remove music).

## 1.4.0 — Reproductor y carpeta de editados
- **Carpetas separadas:** los recortes ya no se guardan junto al original; van a su propia carpeta («Recortes en», por defecto `Música\EC-Tube Editados` y `Videos\EC-Tube Editados`), que puedes cambiar o abrir igual que la de descargas.
- **🎵 Reproductor** (pestaña nueva), ligero, tipo Winamp:
  - barra fija abajo con ⏮ ▶/⏸ ⏹ ⏭, posición, volumen, aleatorio y repetir (toda la lista / esta canción / no); sigue sonando aunque cambies de pestaña; funciona con las teclas multimedia del teclado y con la barra espaciadora;
  - **varias listas guardadas**: nueva, renombrar, borrar, vaciar; doble clic para reproducir; arrastra o ▲▼ para cambiar el orden; muestra la duración de cada canción y del total;
  - **agregar canciones** desde ⬇ Descargas o ✂ Editados (con buscador y «Agregar todas») o desde cualquier carpeta con «Otros archivos…»;
  - si una canción ya no está en su carpeta, se marca y se salta.
- *EN:* Trims now go to their own “Trims in” folder; new 🎵 Player tab (Winamp-style) with multiple saved playlists.

## 1.3.0 — Botón «Actualizar»
- EC-Tube busca solo si hay versión nueva (al abrir) y muestra **⬆ Actualizar**: la baja, revisa que no venga dañada, se instala en silencio (en tu idioma) y se vuelve a abrir. Sin pasar por Edge, así que ya no sale el aviso de «no se descarga comúnmente».
- No actualiza mientras haya descargas o recortes en curso.
- «Buscar actualización» arriba a la derecha.

## 1.2.0 — Español e inglés
- La app y el instalador están en **español o inglés**. Se elige en el instalador y se cambia cuando quieras con el selector 🌐 de arriba.
- En inglés, los recortes se guardan como «(trim)» y las listas sin nombre en «Playlist».

## 1.1.0 — Editor para recortar
- **✂ Recortar:** en cada descarga terminada (o con «✂ Recortar un archivo…» para cualquier audio o video de tu PC). Marcas de inicio y final arrastrables, botones «Inicio aquí» / «Final aquí» desde el reproductor, tiempos escritos a mano y «▶ Escuchar recorte».
- El original no se toca: se guarda una copia «(recorte)» en la misma carpeta. El audio se corta sin recomprimir; el video se recodifica para que el corte sea exacto.

## 1.0.0 — Primera versión
- Pegar uno o varios enlaces y descargar **audio** (MP3 128/192/320 kbps, M4A, WAV) o **video** (MP4 de 360p a 4K).
- Lista de descargas con progreso, velocidad, tiempo restante, cancelar, reintentar, reproducir y abrir la carpeta.
- Listas de reproducción completas (opcional).
- Motor yt-dlp con actualización automática diaria y botón «Actualizar motor»; Deno y FFmpeg incluidos.
- Recuerda formato, calidad y carpetas. Se cierra solo al cerrar la ventana si no hay descargas.
