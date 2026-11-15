# Historial de versiones

## 2.4.0 — Karaoke: la letra sigue la voz del cantante
- **🎤 Voz guía:** la canción original (con voz). Si la pista la hiciste con EC-Tube («… (música)»), la encuentra sola; si no, «Elegir…».
- La primera vez EC-Tube le saca la voz (como en el editor, tarda un par de minutos) y se acuerda para la próxima.
- Al marcar **por frase**, en cuanto sueltas la ESPACIADORA la frase se acomoda a la voz: cada palabra se ilumina cuando el cantante la canta. Si canta rápido, se ilumina rápido; si termina antes de que sueltes, la frase termina con su voz.
- Si la pista y la canción original no empiezan igual (una recortada), se detecta el corrimiento solo.
- **✨ Ajustar a la voz** vuelve a acomodar todas las frases (por ejemplo, si eliges la voz guía después de marcar).
- Sin voz guía, funciona como antes (reparto parejo).

## 2.3.0 — Karaoke: marcar por frase (como Apple Music)
- Nuevo **«Marcar por: Frase»** (viene puesto): cuando empieza la frase aprietas la ESPACIADORA, la mantienes mientras se canta y la sueltas al terminar. La frase se ilumina de corrido de principio a fin y la siguiente queda lista.
- Mientras sostienes, la frase se va iluminando en la vista previa; al soltar queda con sus tiempos.
- ⌫ deshace la frase completa. Si prefieres el modo anterior, elige «Marcar por: Palabra».

## 2.2.2 — Karaoke más parejo
- **Tamaño de letra igual en todo el karaoke** (el que le queda a la línea más larga). Solo una línea que de plano no quepa se achica ella sola.
- Marcar: si Windows no avisa que soltaste la ESPACIADORA (pasaba al final de una frase, antes de un puente), la palabra se quedaba «sostenida» hasta la siguiente frase. Ahora el siguiente toque la cierra y sigue normal, y al cambiar de ventana también se suelta.
- Mientras sostienes, la palabra se llena solo hasta la mitad y cambia a lleno al soltar: así se nota cuándo ya quedó marcada.

## 2.2.1 — Karaoke: ves lo que vas marcando
- Al marcar, la vista previa ya muestra la línea en la que vas **y la que sigue**, desde antes de cantarlas.
- La palabra que te toca marcar va en **amarillo**; al apretar ESPACIO se llena de color en vivo y al soltar queda marcada.
- Arriba dice qué hacer («aprieta ESPACIO…» / «SOSTÉN… suelta…») y en la lista de líneas también se ve palabra por palabra en cuál vas.

## 2.2.0 — Carpeta «EC-Tube Outputs»
- Todo queda ordenado en tu carpeta de usuario, en **`EC-Tube Outputs`**:
  - `MUSIC\Downloaded` (audio que bajas) y `MUSIC\Edited` (recortes, solo música, solo voz)
  - `VIDEO\Downloaded` y `VIDEO\Edited`
  - `KARAOKE\Downloaded` y `KARAOKE\Edited` (los videos de karaoke que creas)
- Si tenías las carpetas de antes por defecto (`Música\EC-Tube`, `Videos\EC-Tube`, `… Editados`, `… Karaoke`), cambian solas a las nuevas. Si tú habías elegido otra carpeta, se respeta. Los archivos que ya tenías se quedan donde estaban.

## 2.1.4
- Karaoke: la música se puede elegir **directo de tus carpetas de EC-Tube** (editados y descargas, audio y video) desde una lista, sin la ventana de Windows. «Elegir de otra carpeta…» sigue para cualquier otro lugar y ahora abre en una carpeta que sí existe.

## 2.1.3
- **📁 Tus archivos** (en «Descargar y recortar»): lista lo que hay de verdad en tus carpetas de descargas o editados (audio o video), aunque EC-Tube se haya cerrado o actualizado, con buscador y botones **✂ Editar**, ▶ abrir y 📂 ver en la carpeta. «🔄 Volver a leer la carpeta» la actualiza (también se actualiza sola al terminar una descarga o un recorte).
- Las ventanas de Windows para elegir archivo o carpeta ahora salen al frente (antes podían abrirse detrás de EC-Tube).

## 2.1.2
- Editor: al elegir «Solo música» o «Solo voz», el botón cambia a **«🎵 Quitar la voz y guardar»** / **«🎤 Quitar la música y guardar»** y aparece la explicación (antes parecía que el menú no hacía nada).

## 2.1.1
- Karaoke: aviso **⚠ IMPORTANTE** para cuando vayas a subir el karaoke a YouTube, TikTok u otras plataformas (derechos de la canción, reclamos, bloqueos, pistas con licencia, «No listado») y un texto de créditos para la descripción del video, con tu título ya puesto y botón «📋 Copiar texto».

## 2.1.0 — 🎤 Karaoke
- **Pestaña nueva «🎤 Karaoke»** para hacer videos de karaoke con la letra iluminándose:
  1. **Música:** eliges la pista (audio o video). Tip: quítale la voz a una canción con «🎵 Solo música» del editor.
  2. **Letra:** un renglón = una línea en pantalla; con «/» una palabra se ilumina por sílabas (*co/ra/zón*).
  3. **Marcar:** suena la música y **mantienes la ESPACIADORA** mientras se canta cada palabra o sílaba (sueltas al terminarla). ⌫ deshace, Esc detiene, «⏺ desde aquí» vuelve a marcar desde cualquier línea, velocidad 50–100 % para marcar con calma y «Ajuste fino» para adelantar o atrasar toda la letra.
  4. **Vista previa** igual al video final: dos líneas a la vez, la palabra se va llenando de color, título al inicio y cuenta regresiva ● ● ● antes de entrar a cantar después de una pausa larga.
  5. **Fondo:** el video original, una imagen tuya o un degradado de colores; también eliges el color de la letra cantada.
  6. **Video:** horizontal 16:9 o vertical 9:16 (TikTok), MP4 1080p, en la carpeta nueva `Videos\EC-Tube Karaoke`.
- Los karaokes se guardan solos como proyectos: puedes volver a abrirlos, corregir tiempos y volver a crear el video.

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
