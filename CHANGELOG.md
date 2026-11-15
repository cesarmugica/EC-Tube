# Historial de versiones

## 2.9.6 — Casilla para la pantalla auxiliar
- Debajo del video: **«Mostrar pantalla auxiliar de video»** (prendida de inicio), con su nota: una ventanita abajo a la derecha con el video y la letra, que aparece cuando bajas y el video de arriba ya no se ve. Se recuerda tu elección.

## 2.9.5 — Karaoke más compacto
- «👁 Ver cómo quedó», «⏺ Marcar», Velocidad y Ajuste fino pasan debajo del video; a la derecha quedan Play/pausa, Entra/Sale = ahora y las notas. Así 📝 Frases sube y cabe todo en la pantalla.
- En la pestaña Karaoke ya no aparece la barra del reproductor de música (solo si de verdad está sonando algo), para que no tape las frases.

## 2.9.4 — Editar la letra desde 📝 Frases
- Cada frase tiene botones: **⏺** marcar desde aquí · **✏** editar el texto · **➕** agregar una frase debajo · **🗑** borrarla (por ejemplo, una parte hablada que no quieres en el karaoke).
- Las demás frases conservan sus tiempos. Si editas una frase y tiene las mismas palabras, conserva sus tiempos; si cambia, se reparte en el mismo tramo.
- La letra del paso 1 se actualiza sola, y todo se puede deshacer con ↶ / Ctrl+Z.

## 2.9.3 — Todo en una pantalla
- Play/pausa, el tiempo y **Entra/Sale = ahora** pasan a la columna de la derecha, junto al video.
- 📝 Frases queda pegada debajo del video y muestra unas 5 frases con scroll; al poner una salida, la lista se recorre sola para que veas la siguiente frase.

## 2.9.2 — Mini reproductor flotante
- Cuando bajas a 📝 Frases o a la línea de tiempo y el video grande ya no se ve, aparece abajo a la derecha un **mini reproductor** con el video y la letra iluminándose, el tiempo exacto, ▶/⏸, ⟲ 3 s y **⤓ Entra / ⤒ Sale = ahora** para la frase elegida.
- ⬆ te sube al video grande; ✕ lo esconde (vuelve a salir la próxima vez que bajes). No aparece en el paso 3 para no tapar el botón de crear.

## 2.9.1 — Nombres más claros
- «▶ Vista previa» ahora se llama **👁 Ver cómo quedó** (y reproduce desde un poco antes de la primera frase): es para revisar el resultado. Para escuchar mientras marcas está **▶ Play / ⏸ Pausa** debajo del video.

## 2.9.0 — Karaoke: escuchar, pausar y marcar «ahora»
- Debajo del video: **▶ Play / ⏸ Pausa**, **⟲ 3 s / 3 s ⟳** y el tiempo exacto (0:25.3).
- **⤓ Entra = ahora** y **⤒ Sale = ahora**: ponen el momento actual a la frase elegida (resaltada en amarillo en 📝 Frases). Al poner la salida pasa sola a la siguiente frase. Haz clic en una frase para elegirla.
- Teclas (cuando no estás escribiendo): **K** play/pausa · **I** entra = ahora · **O** sale = ahora · **← / →** 3 s atrás/adelante.
- Así puedes oír una frase, pausar y anotar sus tiempos con calma. Sigue existiendo ⏺ Marcar con la espaciadora.
- Paso a paso, paso 3: el botón ahora es **⬇ Ir a marcar** (ya no arranca el marcado con espaciadora de golpe).

## 2.8.1 — Paso a paso: revisar y regresar
- Nuevo paso **4 · Revisa y ajusta** con botón **▶ Vista previa**: te lleva abajo y empieza a reproducir desde la primera frase.
- Abajo, junto a la línea de tiempo, **✅ Aceptar tiempos y regresar a los pasos**: fija los tiempos y te sube de nuevo a la lista. También hay **⬆ Regresar a los pasos** junto al título del paso 2.
- Los pasos siguientes se recorren: 5 Aceptar · 6 Quitar voz · 7 Crear el video.

## 2.8.0 — Karaoke «🧭 Paso a paso» (recomendado)
Para canciones con voz (video o solo audio), el flujo más limpio:
1. **Sube la canción** con voz y música, tal cual.
2. **Pega la letra.**
3. **Oyendo al cantante**, marca cuándo entra y sale cada frase (espaciadora sostenida por frase, o escribe entra/sale en 📝 Frases, o arrastra en la línea de tiempo).
4. **✅ Aceptar tiempos** para fijarlos.
5. **🎤➜🎵 Quitar voz**: EC-Tube saca la pista sin voz para el karaoke. Tus entradas y salidas no se mueven; solo las palabras de cada frase se acomodan a la voz.
6. **Crea el video**: 🎤 karaoke (sin voz) o 🎵 video con letra (con voz). Para el video con letra puedes saltarte el paso 5.
- Los otros métodos (Automático, Frase + voz, A mano) siguen ahí.

## 2.7.1 — Los tiempos que escribes se respetan
- Al escribir **entra/sale** de una frase con voz guía, las palabras se acomodaban a la voz buscando hasta 0.3 s antes, y si ahí estaba la cola de la frase anterior, te movía la entrada (escribías 0:56.8 y quedaba 0:56.4). Ahora lo que escribes es exacto: la frase entra y sale justo ahí, y la voz solo acomoda las palabras **dentro**.
- Después de escribir, abajo te dice «✓ Frase N: entra … · sale …», o te avisa si se va a encimar con la anterior o la siguiente.

## 2.7.0 — Video con letra (lyric video)
- En **3 · Fondo y video** eliges el **tipo de video**:
  - **🎤 Karaoke (sin voz)**: como siempre (pista sin voz, letra que se ilumina, cuenta regresiva ● ● ●).
  - **🎵 Video con letra (con voz)**: suena la canción **con voz** (la voz guía, corrida igual que la pista), sin cuenta regresiva, y la letra aparece y se desvanece suave. Opcional: **«Iluminar la letra mientras se canta»**.
- Los mismos tiempos sirven para los dos: puedes sacar el karaoke y el video con letra del mismo proyecto. El archivo se llama «… (karaoke).mp4» o «… (letra).mp4».
- Si no hay voz guía, el video con letra usa el audio de la pista que elegiste (útil si elegiste directamente la canción con voz).

## 2.6.1 — Karaoke: ocultar lo que no has editado
- Casilla **«Ocultar en la vista previa las que no he editado»** en 📝 Frases: así lo que ya estaba no se mezcla con lo que estás arreglando. Todas se ocultan y van apareciendo conforme las editas.
- Cuenta como editada (✓ verde en la lista) una frase a la que le escribes entra/sale, la marcas con la espaciadora o la mueves en la línea de tiempo. En la línea de tiempo las no editadas se ven atenuadas.
- **↺ empezar de nuevo** quita todas las ✓. Solo afecta la vista previa: el video final lleva todas las frases.

## 2.6.0 — Karaoke: escribir a qué hora entra y sale cada frase
- La lista **📝 Frases** ahora va a todo lo ancho y cada frase tiene dos casillas: **entra** y **sale**. Escribe el tiempo (`0:29`, `0:34.5`, `29`…) y presiona Enter; pasa sola a la siguiente casilla.
- Es una forma más, no reemplaza nada: funciona junto con marcar con la espaciadora, el borrador automático y la línea de tiempo.
- Si la frase ya tenía tiempos, se estiran o encogen conservando su ritmo; si no, se reparten. Con voz guía, las palabras se acomodan a la voz dentro de ese tramo.
- Se deshace con ↶ / Ctrl+Z (antes, deshacer a veces no regresaba el último cambio).
- Los botones ➖ ➕ de la línea de tiempo ya no se bajan a otro renglón.

## 2.5.4 — Karaoke: la letra ya no arranca antes de que se cante
- El separador deja «fantasmas» de la música en la voz (sobre todo en la intro). Antes contaban como si alguien cantara y la letra empezaba antes de tiempo. Ahora solo cuenta como voz lo que suena de verdad por encima de la música; lo demás se ignora (para el borrador automático, para «Frase + voz» y en la línea de tiempo).
- En el borrador automático, la voz suelta antes del primer renglón (intro, «yeah», partes habladas) se salta más fácil.

## 2.5.3 — Arreglo: «🤖 Poner tiempos solo» se quedaba apagado
- Al terminar de quitar la voz, una consulta vieja (la que intenta adivinar la canción original en tus carpetas) podía llegar al último y apagar el botón para siempre, aunque la voz ya estuviera lista. Ahora solo cuenta la respuesta más reciente, y si algo falla se vuelve a intentar.
- Para adivinar la canción original también se busca en la carpeta de la pista y en las carpetas de antes (`Música\EC-Tube`, `Videos\EC-Tube`…).

## 2.5.2 — Karaoke: siempre sabes qué sigue
- Debajo del método elegido hay una **lista de pasos en vivo**: ✅ lo que ya está, ⏳ lo que EC-Tube está haciendo (con su %), 👉 lo que te toca ahora, y el botón para hacerlo ahí mismo.
- Automático: 1 canción con voz → 2 quitar la voz → 3 escuchar la voz → 4 pegar la letra → 5 🤖 Poner tiempos solo → 6 revisar y corregir → 7 crear el video.
- Antes, mientras EC-Tube terminaba de escuchar la voz, «🤖 Poner tiempos solo» se veía apagado sin decir por qué; ahora el paso 3 muestra el avance.

## 2.5.1 — Karaoke: eliges cómo sincronizar
- Arriba del karaoke: **«¿Cómo quieres poner los tiempos de la letra?»** con tres opciones y la explicación de cómo trabaja cada una, paso a paso:
  - **🤖 Automático** (tengo la canción con voz): EC-Tube saca la pista y pone los tiempos solo; tú corriges.
  - **🎤 Frase + voz** (tengo la pista y la original): marcas cada frase con la espaciadora y la voz acomoda las palabras.
  - **✋ A mano** (solo tengo la pista): marcas por palabra o por frase.
- Solo se ven los botones del método elegido. Se guarda con cada proyecto y lo puedes cambiar cuando quieras.

## 2.5.0 — Karaoke: varias maneras de sincronizar + línea de tiempo
Como los programas de karaoke (Youka, MyKaraoke, Aegisub): marcar rápido y luego corregir fácil.
- **🎤 Desde la canción con voz…**: eliges la canción original; EC-Tube saca la pista sin voz (para el video) y deja la canción como voz guía, separando una sola vez.
- **🤖 Borrador automático**: con voz guía, pone los tiempos de TODA la canción sin marcar nada (busca los tramos donde se canta, empareja cada renglón con su tramo, se salta «uuh»/adlibs y afina palabra por palabra). Luego corriges lo que no cuadre.
- **🎚 Línea de tiempo** debajo de la vista previa: forma de onda de la pista (gris) y de la voz guía (color) con un bloque por palabra.
  - Arrastra una palabra para moverla; jala sus orillas para alargarla o acortarla (si está pegada a la vecina, la orilla común se mueve junta).
  - **Shift**+arrastrar mueve la frase completa; **◀ 0.1 s / 0.1 s ▶** la recorren poquito.
  - **🔁 Oír frase** repite solo esa frase (a la velocidad elegida) mientras la acomodas.
  - **↶ Deshacer** (Ctrl+Z) para marcar, ajustes, borrador y arrastres.
  - Clic en lo vacío = ir a ese momento; arrastrar lo vacío = recorrer; rueda = acercar/alejar.
- Siguen las dos formas de marcar (por **Frase** o por **Palabra**) con o sin voz guía; un aviso dice cuál conviene en cada caso.
- Solo con la pista (sin voz original) se marca a mano —igual que en cualquier programa— y se corrige en la línea de tiempo.

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
