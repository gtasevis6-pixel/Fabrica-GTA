# Fábrica GTA · 3 videos por día, solos

Todos los días, en cada turno de `config.json` (por defecto 13:30, 18:30 y 22:00, hora de Argentina), este repo:

1. **Busca material.**
   - **Clips:** los más vistos de GTA 6 en Twitch de las últimas 24 horas, con prioridad a los streamers que hablan en español. Kick también, en modo experimental.
   - **Novedades y guías:** noticias de Google Noticias en español, RockstarINTEL y r/GTA6.
2. **Elige.** Una IA (Gemini, gratis) mira los 5 mejores clips: los fotogramas, lo que se dice y las vistas. Se queda con el que tiene más chances de explotar y descarta spoilers, desnudos, exploits y filtraciones.
3. **Edita en vertical.** El clip va al centro y el mismo clip desenfocado de fondo. Arriba lleva el gancho y abajo subtítulos grandes palabra por palabra: si el clip no está en español, van traducidos. También lleva el crédito del streamer siempre visible y una barra de progreso.
   - Las novedades salen con voz en off y gameplay del día de fondo.
4. **Revisa.** Otra IA, que no hizo el video, lo mira terminado y dice sí o no. Si falla solo un texto, lo corrige. Si el clip no sirve, prueba con el siguiente.
5. **Te lo manda por mail** y espera **5 minutos**. Si no hacés nada, se publica solo en YouTube Shorts, Instagram Reels, Facebook y TikTok (los que tengas activados).
6. **Guarda el historial** en `publicaciones/` y `data/`, para no repetir clips ni noticias.
   Además deja una **nota por video en `notas/`** (solo si salió en al menos una red), lista para un blog futuro (ver abajo).
7. **Vigila campañas de clipping de GTA** en tableros públicos y te avisa por mail si aparece una nueva.

**Costo: US$ 0.** Usa GitHub Actions (gratis en repos públicos), la clave gratuita de Gemini, la API gratuita de Twitch y Whisper para los subtítulos.

> ⚠️ **Sobre los derechos.** Los clips son de los streamers. La fábrica siempre los acredita (en el video y en el texto) y transforma el clip: gancho, subtítulos y recorte. Igual, lo más seguro y lo que además te paga es clipear a streamers con **campaña de clipping** activa. Cuando te sumes a una, poné el nombre del canal en `config.json` → `clips.streamers_con_campana` y sus clips salen primero. Si un streamer te pide que no lo uses, agregalo a `clips.canales_bloqueados`.

---

## Puesta en marcha

### Paso 1 · Crear el repo y subir los archivos (5 minutos)

1. En GitHub: **New repository** → nombre `fabrica-gta` → **Public** (así Actions es gratis) → **Create repository**.
2. Descomprimí el zip en tu compu.
3. En el repo, tocá **uploading an existing file** (o **Add file → Upload files**).
4. Arrastrá **todo el contenido** de la carpeta, incluida la carpeta `.github` (en Windows se ve sin hacer nada; en Mac: `Cmd + Shift + .` en el Finder). Después del commit, fijate que en el repo aparezca `.github/workflows/` con `diario.yml` y `revisar.yml`.
5. **Commit changes**.

### Paso 2 · Activar la página donde se alojan los videos (1 minuto)

**Settings → Pages → Build and deployment → Source: GitHub Actions.**

Instagram necesita un link público para bajar el video. Ahí se sube cada uno.

### Paso 3 · Cargar las claves (15 minutos)

Van en **Settings → Secrets and variables → Actions → New repository secret**. Nunca las pegues en un chat ni en un archivo.

| Secreto | Dónde se saca |
|---|---|
| `GEMINI_API_KEY` | https://aistudio.google.com/apikey → **Create API key**. Conviene un proyecto de Google nuevo, separado de tus otras fábricas, así no comparten el cupo gratis. |
| `TWITCH_CLIENT_ID` y `TWITCH_CLIENT_SECRET` | Ver abajo. |
| `SMTP_USER` y `SMTP_PASS` | `SMTP_USER` es tu Gmail. `SMTP_PASS` es una **contraseña de aplicación**: https://myaccount.google.com/apppasswords. Sin esto no te llega el mail para aprobar. |

**Cómo sacar las claves de Twitch (gratis):**

1. Entrá a https://dev.twitch.tv/console con tu cuenta de Twitch. Si te lo pide, activá la verificación en dos pasos en *Configuración → Seguridad*.
2. **Applications → Register Your Application**:
   - Name: `fabrica-gta-tuusuario` (tiene que ser único)
   - OAuth Redirect URLs: `http://localhost`
   - Category: **Other**
   - Client Type: **Confidential**
3. **Create** → entrá a **Manage**. Copiá el **Client ID** → secreto `TWITCH_CLIENT_ID`.
4. Tocá **New Secret**, copiala → secreto `TWITCH_CLIENT_SECRET`.

### Paso 4 · Tus datos

En `config.json` (lápiz → Commit changes):
- `"usuario"`: el @ de la página (aparece chiquito abajo del video). Ya viene con `@GTASeVIs`.
- `"email_aviso"`: vacío = los mails llegan al Gmail de `SMTP_USER`. Si ponés otro, tené en cuenta que el repo es público.
- `"automatico"`: viene en `false`, así no corre sola mientras probás. Cuando la prueba ande y tengas al menos una red conectada, ponelo en `true` y arrancan los 3 videos por día.

Guardá con **Commit changes**.

### Paso 5 · Primera prueba (sin publicar nada)

1. **Actions → Fábrica GTA → Run workflow**. Dejá **"¿Publicar en las redes?"** destildado y tocá **Run workflow**.
2. Esperá unos 10 minutos y entrá a la ejecución. Abajo de todo vas a ver el **resumen**: el link al video, la portada, de qué streamer es y el texto.
3. Para probar el video de novedades: igual, pero en **tipo** escribí `novedad`.

Si algo falla, el motivo aparece en rojo arriba de todo en la ejecución. Mandame captura.

---

## Conectar las redes

Hacelo de a una. Cuando cada una ande, poné `true` en `config.json` → `publicar`.

Antes de todo: **cuentas nuevas**, con el mismo nombre en todas las redes, Instagram en modo **profesional** (*Configuración → Tipo de cuenta → Creador*).

Los pasos son los mismos que hiciste en `shorts-fabrica` (@ramacontable), pero con las cuentas y apps nuevas de esta página:

### YouTube

1. En https://console.cloud.google.com creá un proyecto nuevo y habilitá **YouTube Data API v3**.
2. **Google Auth Platform**: tipo **Externo**. Como página principal usá el link de este repo y como política de privacidad el link a `PRIVACIDAD.md`. En **Público → Publicar app** (tiene que quedar **En producción**).
3. **Clientes → Crear cliente → Aplicación web**, con URI de redirección `https://developers.google.com/oauthplayground`. Copiá el ID y el secreto.
4. En https://developers.google.com/oauthplayground:
   1. En el engranaje, tildá **Use your own OAuth credentials** y pegá el ID y el secreto.
   2. Autorizá `https://www.googleapis.com/auth/youtube.upload` con la cuenta del canal **nuevo**.
   3. Tocá **Exchange authorization code for tokens** y copiá el **Refresh token**.
5. Guardá los secretos `YT_CLIENT_ID`, `YT_CLIENT_SECRET` y `YT_REFRESH_TOKEN`, y poné `"youtube": true`.

### Instagram

1. Entrá a https://developers.facebook.com → **Crear app** → producto **Instagram** → **Configuración de la API con inicio de sesión de Instagram**.
2. En **Generar tokens**, agregá la cuenta nueva y copiá el token → secreto `IG_TOKEN`.
3. Para que el token se renueve solo, creá un token de GitHub en https://github.com/settings/personal-access-tokens/new:
   - Solo este repo
   - **Secrets: Read and write**

   Guardalo como secreto `GH_PAT`.
4. Poné `"instagram_reel": true`.

### Facebook (Reels de una página)

1. Creá la página y vinculá el Instagram.
2. Con el Explorer de Meta, sacá el token de la página (el que no vence) y su `id` → secretos `FB_PAGE_TOKEN` y `FB_PAGE_ID`.
3. Poné `"facebook": true`.

### TikTok

Necesita una app aprobada en https://developers.tiktok.com (**Content Posting API**). Hasta que la aprueben, lo que sube la API queda en privado (`tiktok_privacidad: SELF_ONLY`). Mientras tanto, el mail te trae el video para subirlo a mano desde el celular. Cuando quieras activarlo, lo hacemos juntos.

---

## Tu control: los 5 minutos

Cada video te llega por mail con el asunto **"[GTA] Revisá en 5 min"**. El mail trae:
- el video y la portada
- el clip original con el link
- el texto que va a salir

**Si no hacés nada, a los 5 minutos se publica.** Si querés intervenir, tocá **Revisar video** en el mail (o *Actions → Revisar video*) → **Run workflow** y elegí:

- **Publicar ya**: sale en el próximo minuto.
- **No publicar**: ese video no sale y el clip no se vuelve a usar.
- **Otro clip / otro tema**: arma otro con un clip distinto (o con otra noticia) y te lo vuelve a mandar. Se puede pedir una vez por turno.

Para darte más tiempo: `config.json` → `minutos_aprobacion`.

## Cómo cambiar cosas (todo en `config.json`)

| Qué | Dónde |
|---|---|
| Horarios y cantidad de videos | `turnos`: podés agregar los turnos que quieras copiando una línea. Tipos: `clip`, `novedad` o `guia`. |
| Idioma de los clips | `clips.idiomas` (primero estos) y `clips.aceptar_otros_idiomas` (si no hay, usa otros con subtítulos traducidos). |
| Streamers con campaña de clipping | `clips.streamers_con_campana`: salen primero. |
| Streamers que no querés usar | `clips.canales_bloqueados`. |
| Largo de los clips | `clips.duracion_min` y `clips.duracion_max` (en segundos). |
| Agrandar el video del centro | `clips.zoom`: `1.0` normal, `1.3` recorta los costados y se ve más grande. |
| Juegos de Twitch | `fuentes.twitch.juegos`: primero GTA VI; si no hay clips, GTA V. |
| Kick | `fuentes.kick.activo` (experimental). |
| Búsquedas de noticias y guías | `noticias.busquedas` y `noticias.busquedas_guia`. |
| Voz de las novedades | `voz_gemini` (`auto`, `Puck`, `Orus`, `Charon`, `Kore`...), `voz_tempo`. Respaldo de Microsoft: `voz`. |
| Música de fondo en las novedades | Subí un `.mp3` libre de derechos como `assets/music.mp3`. |
| Las reglas de lo que se puede decir | `prompts/reglas.md` |

## Qué fuentes se usan y cuáles no

- ✅ **Twitch**: la API oficial y gratuita. Trae los clips más vistos por juego e idioma.
- 🧪 **Kick**: no tiene API pública de clips y a veces bloquea a GitHub. Si falla, sigue sin Kick.
- ✅ **Noticias**: Google Noticias en español, RockstarINTEL y r/GTA6 (por RSS).
- ❌ **X, TikTok e Instagram como fuente de clips**: no hay forma gratuita y permitida de buscar y bajar videos de otros desde GitHub. Para ideas de qué funciona, mirá esas redes vos y sumá los streamers que veas a `streamers_con_campana`.
- ❌ **YouTube como fuente de clips**: YouTube bloquea las descargas desde servidores como los de GitHub.

## Si algo falla

- GitHub te manda un mail cuando una ejecución falla, y el motivo queda arriba de todo en la ejecución.
- Si un turno no encuentra nada que valga la pena, no publica relleno: te avisa por mail y sigue en el turno siguiente.
- Todo queda en `publicaciones/` (un archivo por video) y en `data/historial.json`.

## Preparado para un blog (más adelante)

Cada video publicado deja un archivo en `notas/`, en el formato que leen los armadores de blogs gratis (Jekyll, Hugo, Astro). Cada nota tiene arriba:
- el título, la fecha y el tipo
- las etiquetas
- el link al Short de YouTube
- las fuentes
- el streamer y el clip original

Las novedades y guías traen, además, una nota de 120 a 220 palabras escrita solo con datos de las fuentes.

El día que armemos el blog, arranca con todo el archivo acumulado. Cada nota embebe su Short de YouTube, así que no hay que guardar los videos en ningún lado. Por ahora no hace falta hacer nada más.
