"""Edición vertical 1080x1920 con ffmpeg.

Diseño de cada video (clip o novedad):
  - fondo: el mismo video agrandado, desenfocado y oscurecido (así no quedan franjas negras)
  - al centro: el video completo (16:9), con un poco de zoom si se pide
  - arriba: el gancho en letras grandes (los primeros segundos más grande, después queda como título)
  - abajo del video: el crédito del streamer (siempre visible) y subtítulos grandes palabra por palabra
  - barra de progreso amarilla abajo de todo
"""
import json
import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from . import util

W, H, FPS = 1080, 1920, 30
FONTS = util.RAIZ / "fonts"
AMARILLO_ASS = "&H0000D7FF"   # BGR: amarillo dorado
ROSA_ASS = "&H00B469FF"


def run(cmd, timeout=900):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError("Falló " + " ".join(str(c) for c in cmd[:5]) + ": " + r.stderr[-1500:])
    return r.stdout


def duracion(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of",
                      "default=nw=1:nk=1", str(path)]).strip())


def info_video(path):
    j = json.loads(run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height", "-of", "json", str(path)]))
    s = (j.get("streams") or [{}])[0]
    return int(s.get("width", 1920)), int(s.get("height", 1080))


def tiene_audio(path):
    out = run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0",
               str(path)])
    return bool(out.strip())


# ------------------------------------------------------------------ fuentes tipográficas
def _ruta_fuente(nombre):
    for p in (FONTS / nombre, Path("/usr/share/fonts/truetype/google-fonts") / nombre):
        if p.exists():
            return str(p)
    return None


def fuente_titulo():
    return "Anton" if _ruta_fuente("Anton-Regular.ttf") else "Poppins"


def pil_fuente(size, tipo="titulo"):
    nombres = {"titulo": ["Anton-Regular.ttf", "Poppins-Black.ttf", "Poppins-ExtraBold.ttf", "Poppins-Bold.ttf"],
               "texto": ["Poppins-SemiBold.ttf", "Poppins-Bold.ttf"]}[tipo]
    for n in nombres:
        r = _ruta_fuente(n)
        if r:
            return ImageFont.truetype(r, size)
    return ImageFont.truetype("DejaVuSans-Bold.ttf", size)


# ------------------------------------------------------------------ geometría
def caja_video(ancho, alto, zoom=1.0):
    """Dónde va el video nítido dentro del 1080x1920. Devuelve (w, h, y)."""
    zoom = max(1.0, min(float(zoom or 1.0), 1.8))
    w = int(round(W * zoom / 2)) * 2
    h = int(round(w * alto / max(1, ancho) / 2)) * 2
    h = min(h, 1240)
    y = int((H - h) / 2 - 70)
    return w, h, max(360, y)


# ------------------------------------------------------------------ subtítulos y textos (ASS)
def _t(s):
    s = max(0.0, s)
    return f"{int(s // 3600)}:{int(s % 3600 // 60):02d}:{s % 60:05.2f}"


def _limpio(t):
    return re.sub(r"[{}\\\n]", "", str(t or "")).strip()


def _bloques(palabras, max_palabras=3, max_chars=16):
    """Agrupa palabras [ini, fin, texto] en bloques cortos que entran en una o dos líneas."""
    bloques, cur = [], []
    for w in palabras:
        cur.append(w)
        txt = " ".join(x[2] for x in cur)
        if len(cur) >= max_palabras or len(txt) >= max_chars or re.search(r"[.,;:?!…]$", w[2]):
            bloques.append(cur)
            cur = []
    if cur:
        bloques.append(cur)
    return bloques


def armar_ass(ruta, dur, gancho="", credito="", usuario="", palabras=None, frases=None, y_video=None,
              h_video=None, gancho_segundos=3.0):
    """palabras: [[ini, fin, texto], ...] para subtítulos palabra por palabra.
    frases: [[ini, fin, texto], ...] para subtítulos por frase (traducciones)."""
    fuente = fuente_titulo()
    y_video = y_video or 560
    h_video = h_video or 608
    abajo = y_video + h_video
    y_sub = min(H - 330, abajo + 230)
    y_credito = abajo + 52
    cab = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {W}
PlayResY: {H}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Gancho,{fuente},118,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,1,0,1,9,4,8,60,60,0,1
Style: Titulo,{fuente},78,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,1,0,1,7,3,8,60,60,0,1
Style: Sub,{fuente},104,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,1,0,0,0,100,100,1,0,1,9,4,5,50,50,0,1
Style: Frase,Poppins,64,&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,1,0,0,0,100,100,0,0,3,14,0,5,70,70,0,1
Style: Credito,Poppins,40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,1,0,1,4,1,5,40,40,0,1
Style: Usuario,Poppins,36,&H40FFFFFF,&H40FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,1,0,1,3,1,5,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    ev = []
    g = _limpio(gancho).upper()
    if g:
        corte = min(gancho_segundos, dur)
        # el gancho entra grande y con un "pop"; después queda más chico como título
        ev.append(f"Dialogue: 2,{_t(0)},{_t(corte)},Gancho,,0,0,0,,{{\\an8\\pos({W // 2},{max(150, y_video - 330)})"
                  f"\\fscx80\\fscy80\\t(0,160,\\fscx100\\fscy100)\\c{AMARILLO_ASS}}}{g}")
        if dur > corte:
            ev.append(f"Dialogue: 1,{_t(corte)},{_t(dur)},Titulo,,0,0,0,,{{\\an8\\pos({W // 2},"
                      f"{max(170, y_video - 250)})}}{g}")
    if credito:
        ev.append(f"Dialogue: 1,{_t(0)},{_t(dur)},Credito,,0,0,0,,{{\\an5\\pos({W // 2},{y_credito})}}"
                  f"{_limpio(credito)}")
    if usuario:
        ev.append(f"Dialogue: 1,{_t(0)},{_t(dur)},Usuario,,0,0,0,,{{\\an5\\pos({W // 2},{H - 120})}}"
                  f"{_limpio(usuario)}")
    if palabras:
        for bloque in _bloques(palabras):
            for i, w in enumerate(bloque):
                ini = w[0]
                fin = bloque[i + 1][0] if i + 1 < len(bloque) else max(w[1], ini + 0.25)
                partes = []
                for j, x in enumerate(bloque):
                    txt = _limpio(x[2]).upper()
                    partes.append(f"{{\\c{AMARILLO_ASS}}}{txt}{{\\c&H00FFFFFF&}}" if j == i else txt)
                ev.append(f"Dialogue: 3,{_t(ini)},{_t(min(fin, dur))},Sub,,0,0,0,,{{\\an5\\pos({W // 2},{y_sub})}}"
                          + " ".join(partes))
    if frases:
        for ini, fin, txt in frases:
            if txt and fin > ini:
                ev.append(f"Dialogue: 3,{_t(ini)},{_t(min(fin, dur))},Frase,,0,0,0,,{{\\an5\\pos({W // 2},{y_sub})}}"
                          f"{_limpio(txt)}")
    Path(ruta).write_text(cab + "\n".join(ev) + "\n", encoding="utf-8")
    return ruta


# ------------------------------------------------------------------ armado
def _filtro_vertical(ancho, alto, zoom, dur, ass, con_barra=True, entrada="0:v"):
    w, h, y = caja_video(ancho, alto, zoom)
    recorte = f",crop={W}:{h}" if w > W else ""   # con zoom el video se pasa de ancho: recorto los costados
    partes = [
        f"[{entrada}]split=2[v_fondo][v_frente]",
        f"[v_fondo]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},"
        f"boxblur=24:2,eq=brightness=-0.18:saturation=1.15[fondo]",
        f"[v_frente]scale={w}:{h}{recorte},setsar=1[frente]",
        f"[fondo][frente]overlay=(W-w)/2:{y}[base]",
        f"[base]subtitles='{_esc(ass)}':fontsdir='{_esc(FONTS)}'[con_texto]",
    ]
    if con_barra:
        partes += [f"color=c=0xFFD700:s={W}x12:r={FPS}[barra]",
                   f"[con_texto][barra]overlay=x='-W+W*t/{max(dur, 0.1):.3f}':y={H - 12}:shortest=1,"
                   f"fps={FPS},format=yuv420p[v]"]
    else:
        partes.append(f"[con_texto]fps={FPS},format=yuv420p[v]")
    return ";".join(partes), y, h


def _esc(p):
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def render_clip(origen, destino, carpeta, gancho, credito, usuario, palabras=None, frases=None,
                recorte=None, zoom=1.0):
    """Arma el Short a partir de un clip (con su audio original)."""
    carpeta = Path(carpeta)
    ini, fin = 0.0, duracion(origen)
    if recorte and len(recorte) == 2:
        a, b = float(recorte[0] or 0), float(recorte[1] or fin)
        if 0 <= a < b <= fin + 0.5 and b - a >= 5:
            ini, fin = a, min(b, fin)
    dur = fin - ini
    ancho, alto = info_video(origen)
    _, h, y = caja_video(ancho, alto, zoom)
    # tiempos de subtítulos relativos al recorte
    pal = [[p[0] - ini, p[1] - ini, p[2]] for p in (palabras or []) if p[1] > ini and p[0] < fin]
    fra = [[max(0, f[0] - ini), f[1] - ini, f[2]] for f in (frases or []) if f[1] > ini and f[0] < fin]
    ass = armar_ass(carpeta / "textos.ass", dur, gancho, credito, usuario, pal or None, fra or None, y, h)
    filtro, _, _ = _filtro_vertical(ancho, alto, zoom, dur, ass)
    audio = []
    if tiene_audio(origen):
        filtro += ";[0:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[a]"
        audio = ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{ini:.2f}", "-t", f"{dur:.2f}", "-i", str(origen),
         "-filter_complex", filtro, "-map", "[v]", *audio, "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
         "-movflags", "+faststart", "-t", f"{dur:.2f}", str(destino)])
    return destino


def fondo_de_clips(clips, destino, dur, tramo=3.2):
    """Une pedazos de varios clips (sin audio) en un video 16:9 que dura `dur`."""
    destino = Path(destino)
    if not clips:
        run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i",
             f"gradients=s=1920x1080:c0=0x2a0845:c1=0xff2e88:c2=0x1b9aaa:speed=0.008:d={dur + 1:.2f}:r={FPS}",
             "-t", f"{dur + 0.5:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(destino)])
        return destino
    largos = [(c, duracion(c)) for c in clips]
    piezas, t, i, k = [], 0.0, 0, 0
    while t < dur + 0.5 and k < 200:
        c, d = largos[i % len(largos)]
        vuelta = i // len(largos)
        ini = min(max(0.0, d * 0.15 + vuelta * tramo), max(0.0, d - tramo - 0.1))
        piezas.append((c, ini, min(tramo, d)))
        t += min(tramo, d)
        i += 1
        k += 1
    ins, flt = [], ""
    for j, (c, ini, largo) in enumerate(piezas):
        ins += ["-ss", f"{ini:.2f}", "-t", f"{largo:.2f}", "-i", str(c)]
        flt += (f"[{j}:v]scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,setsar=1,"
                f"fps={FPS},format=yuv420p[p{j}];")
    flt += "".join(f"[p{j}]" for j in range(len(piezas))) + f"concat=n={len(piezas)}:v=1:a=0[v]"
    run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", flt, "-map", "[v]", "-t", f"{dur + 0.3:.2f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", str(destino)])
    return destino


def render_narrado(fondo, voz_wav, destino, carpeta, gancho, palabras, usuario, credito="", musica=None,
                   musica_vol=0.08, zoom=1.0):
    """Video de novedades: fondo de gameplay (sin audio), voz en off y subtítulos palabra por palabra."""
    carpeta = Path(carpeta)
    dur = duracion(voz_wav) + 0.4
    ancho, alto = info_video(fondo)
    _, h, y = caja_video(ancho, alto, zoom)
    ass = armar_ass(carpeta / "textos.ass", dur, gancho, credito, usuario, palabras, None, y, h, 2.6)
    filtro, _, _ = _filtro_vertical(ancho, alto, zoom, dur, ass)
    ins = ["-stream_loop", "-1", "-i", str(fondo), "-i", str(voz_wav)]
    if musica and Path(musica).exists():
        ins += ["-stream_loop", "-1", "-i", str(musica)]
        filtro += (f";[1:a]aresample=44100,apad=pad_dur=0.4[voz];[2:a]volume={musica_vol},aresample=44100[mus];"
                   f"[voz][mus]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5[a]")
    else:
        filtro += ";[1:a]aresample=44100,apad=pad_dur=0.4,loudnorm=I=-14:TP=-1.5[a]"
    run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", filtro, "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "160k",
         "-t", f"{dur:.2f}", "-movflags", "+faststart", str(destino)])
    return destino


# ------------------------------------------------------------------ cuadros y portada
def cuadros(video, carpeta, n=4, ancho=640):
    """Saca n fotogramas parejos (para que la IA "vea" el clip y para la portada)."""
    d = duracion(video)
    out = []
    for i in range(n):
        t = d * (i + 0.5) / n
        p = Path(carpeta) / f"cuadro{i}.jpg"
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1",
             "-vf", f"scale={ancho}:-2", "-q:v", "4", str(p)])
        out.append(p)
    return out


def portada(video, destino, segundo, gancho):
    """Portada vertical: el fotograma elegido de fondo y el gancho bien grande."""
    tmp = Path(destino).with_suffix(".frame.jpg")
    d = duracion(video)
    seg = min(max(0.0, float(segundo or d * 0.4)), max(0.0, d - 0.1))
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{seg:.2f}", "-i", str(video), "-frames:v", "1", "-q:v", "2",
         str(tmp)])
    img = Image.open(tmp).convert("RGB").resize((W, H))
    capa = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dib = ImageDraw.Draw(capa)
    for yy in range(0, 760):  # degradé oscuro arriba para que se lea el texto
        a = int(200 * (1 - yy / 760))
        dib.line([(0, yy), (W, yy)], fill=(0, 0, 0, a))
    img = Image.alpha_composite(img.convert("RGBA"), capa)
    dib = ImageDraw.Draw(img)
    texto = (gancho or "").upper()
    tam = 150
    while tam > 70:
        f = pil_fuente(tam)
        lineas = _partir(dib, texto, f, W - 120)
        if len(lineas) <= 3:
            break
        tam -= 8
    y = 170
    for i, ln in enumerate(lineas[:3]):
        ancho = dib.textlength(ln, font=f)
        color = (255, 215, 0) if i == 0 else (255, 255, 255)
        dib.text(((W - ancho) / 2, y), ln, font=f, fill=color, stroke_width=10, stroke_fill=(0, 0, 0))
        y += int(tam * 1.12)
    img.convert("RGB").save(destino, quality=90)
    tmp.unlink(missing_ok=True)
    return destino


def _partir(dib, texto, f, max_w):
    out, cur = [], ""
    for p in texto.split():
        prueba = (cur + " " + p).strip()
        if dib.textlength(prueba, font=f) <= max_w:
            cur = prueba
        else:
            if cur:
                out.append(cur)
            cur = p
    if cur:
        out.append(cur)
    return out


def a_gif(video, destino, desde=0.0, segundos=6.0, ancho=360):
    """GIF cortito para mandarte de muestra."""
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{desde:.2f}", "-t", f"{segundos:.2f}", "-i", str(video),
         "-vf", f"fps=12,scale={ancho}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96[p];[b][p]paletteuse",
         str(destino)])
    return destino
