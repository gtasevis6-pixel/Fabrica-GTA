"""Arma los dos tipos de video:
  - clip:     el mejor clip viral de las últimas horas, editado en vertical con gancho, crédito y subtítulos
  - novedad:  una noticia (o una guía/truco) con voz en off sobre gameplay de clips del día

Cada video pasa por el revisor (una IA aparte que no lo hizo) antes de quedar listo."""
import base64
import os
import re
from pathlib import Path

from . import edicion, fuentes, ia, util


class SinMaterial(RuntimeError):
    """No hubo nada publicable (ni clips ni noticias que sirvan)."""


# ------------------------------------------------------------------ utilidades
def _reglas():
    return ia.prompt("reglas.md")


def _imagen(p):
    return {"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(Path(p).read_bytes()).decode()}}


_whisper = None  # el modelo se carga una sola vez por ejecución


def _audio_16k(wav):
    """Lee el WAV mono de 16 kHz que arma ffmpeg y lo pasa a números (sin depender de PyAV)."""
    import wave
    import numpy as np
    with wave.open(str(wav), "rb") as w:
        datos = w.readframes(w.getnframes())
    return np.frombuffer(datos, dtype=np.int16).astype(np.float32) / 32768.0


def transcribir(video, cfg):
    """Lo que se escucha en el clip, con tiempo de cada palabra (faster-whisper, gratis, en GitHub)."""
    global _whisper
    try:
        from faster_whisper import WhisperModel
    except Exception:  # noqa
        util.log("faster-whisper no está instalado: sigo sin subtítulos")
        return [], ""
    try:
        wav = Path(video).with_suffix(".16k.wav")
        edicion.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
                     "-c:a", "pcm_s16le", str(wav)])
        audio = _audio_16k(wav)
        if len(audio) < 16000 * 0.5:
            return [], ""
        if _whisper is None:
            _whisper = WhisperModel(cfg.get("whisper_modelo", "base"), device="cpu", compute_type="int8")
        # se le pasa el audio ya leído: así no usa PyAV (cuyas versiones nuevas rompen faster-whisper)
        segs, info = _whisper.transcribe(audio, word_timestamps=True, vad_filter=True, beam_size=1,
                                         condition_on_previous_text=False)
        palabras = [[float(w.start), float(w.end), w.word.strip()] for s in segs for w in (s.words or [])
                    if w.word.strip()]
        return palabras, getattr(info, "language", "") or ""
    except Exception as e:  # noqa
        util.log("No pude transcribir:", e)
        return [], ""


def _texto_con_tiempos(palabras, cada=4.0):
    """Transcripción compacta: [0.0] texto ... [4.1] texto ..."""
    if not palabras:
        return "(no se escucha voz)"
    out, marca = [], -cada
    for p in palabras:
        if p[0] - marca >= cada:
            out.append(f"\n[{p[0]:.1f}]")
            marca = p[0]
        out.append(p[2])
    return " ".join(out).strip()[:2500]


def _caption_final(cfg, caption, hashtags, credito_linea):
    tags = " ".join(h if h.startswith("#") else "#" + h for h in (hashtags or [])[:5])
    for fija in cfg.get("hashtags_fijos", []):
        if fija.lower() not in tags.lower():
            tags += " " + fija
    partes = [caption.strip(), credito_linea, cfg.get("firma", ""), tags.strip()]
    return "\n\n".join(p for p in partes if p)


def revisar(cfg, tipo, video, portada_p, textos, carpeta, extra=""):
    """La «regla del revisor»: una IA aparte mira el video terminado y dice sí o no."""
    if not cfg.get("revisor", True):
        return {"aprobado": True, "fallas": []}
    rev = Path(carpeta) / "revision"
    rev.mkdir(parents=True, exist_ok=True)
    cuadros = edicion.cuadros(video, rev, n=4, ancho=480)
    partes = [{"text": f"TIPO: {tipo}\n{textos}\n{extra}\nFOTOGRAMAS DEL VIDEO TERMINADO:"}]
    partes += [_imagen(c) for c in cuadros]
    partes += [{"text": "PORTADA:"}, _imagen(portada_p)]
    try:
        r = ia.gemini(_reglas() + "\n\n" + ia.prompt("revisor.md"), partes, temperatura=0.2)
    except Exception as e:  # noqa
        util.avisar("El revisor no respondió", f"Sigo sin revisión automática: {util.ocultar(e)[:200]}")
        return {"aprobado": True, "fallas": ["(revisor sin respuesta)"]}
    util.log("Revisor:", "aprobado" if r.get("aprobado") else "rechazado", "·", "; ".join(r.get("fallas") or []))
    return r


# ------------------------------------------------------------------ CLIP
def producir_clip(cfg, carpeta, usados, excluir=()):
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    c = cfg.get("clips") or {}
    lista = [x for x in fuentes.candidatos(cfg, set(usados) | set(excluir)) if x["id"] not in excluir]
    if not lista:
        # si en las últimas horas no hay nada, amplío la ventana una vez
        lista = [x for x in fuentes.candidatos(cfg, set(usados) | set(excluir), horas=72)]
    if not lista:
        raise SinMaterial("No encontré clips nuevos de GTA en Twitch/Kick.")
    a_revisar = int(c.get("candidatos_a_revisar", 5))
    intentos_render = int(c.get("intentos", 3))
    descartados = set()
    for vuelta in range(intentos_render):
        tanda = [x for x in lista if x["id"] not in descartados][:a_revisar]
        if not tanda:
            break
        bajados = []
        for i, x in enumerate(tanda):
            try:
                ruta = fuentes.bajar(x, carpeta / "clips" / f"{re.sub(r'[^a-zA-Z0-9-]', '', x['id'])}.mp4")
            except Exception as e:  # noqa
                util.log("No bajó:", x["url"], util.ocultar(e)[:150])
                descartados.add(x["id"])
                continue
            palabras, idioma = transcribir(ruta, cfg)
            x = {**x, "archivo": str(ruta), "palabras": palabras, "idioma_oido": idioma}
            bajados.append(x)
        if not bajados:
            continue
        # el editor (IA) mira todos y elige uno
        partes = [{"text": "CLIPS CANDIDATOS:"}]
        for n, x in enumerate(bajados):
            partes.append({"text": (f"\n--- CLIP {n} ---\nplataforma: {x['plataforma']} · streamer: {x['canal']} · "
                                    f"vistas: {x['vistas']} · duración: {x['duracion']:.0f} s · idioma: "
                                    f"{x['idioma'] or x['idioma_oido']}\ntítulo original: {x['titulo']}\n"
                                    f"transcripción:\n{_texto_con_tiempos(x['palabras'])}\nfotogramas:")})
            for f in edicion.cuadros(x["archivo"], carpeta / "clips", n=3, ancho=480):
                partes.append(_imagen(f))
                Path(f).replace(Path(f).with_name(f"c{n}_{Path(f).name}"))
        try:
            ed = ia.gemini(_reglas() + "\n\n" + ia.prompt("editor_clip.md"), partes, temperatura=0.7)
        except Exception as e:  # noqa
            util.avisar("El editor no respondió", util.ocultar(e)[:300])
            ed = {"elegido": 0, "gancho": bajados[0]["titulo"][:40], "titulo": bajados[0]["titulo"][:70],
                  "caption": bajados[0]["titulo"], "hashtags": ["#GTA6"]}
        for d in ed.get("descartados") or []:
            try:
                descartados.add(bajados[int(d.get("clip"))]["id"])
            except Exception:  # noqa
                pass
        k = int(ed.get("elegido", -1) if ed.get("elegido") is not None else -1)
        if k < 0 or k >= len(bajados):
            descartados.update(x["id"] for x in bajados)
            continue
        x = bajados[k]
        descartados.add(x["id"])
        hecho = _render_y_revisar(cfg, carpeta, x, ed)
        if hecho:
            return hecho
    raise SinMaterial("Ningún clip pasó la revisión hoy.")


def _render_y_revisar(cfg, carpeta, x, ed):
    c = cfg.get("clips") or {}
    plataforma = {"twitch": "twitch.tv", "kick": "kick.com"}.get(x["plataforma"], x["plataforma"])
    credito = f"CLIP: {plataforma}/{x['canal']}"
    es_espanol = (x["idioma"] or x["idioma_oido"] or "").startswith("es")
    frases = None if es_espanol else [f for f in (ed.get("subtitulos") or []) if isinstance(f, list) and len(f) == 3]
    palabras = x["palabras"] if es_espanol else None
    for vuelta in range(2):
        video = carpeta / "video.mp4"
        edicion.render_clip(x["archivo"], video, carpeta, ed.get("gancho", ""), credito, cfg.get("usuario", ""),
                            palabras=palabras, frases=frases, recorte=ed.get("recorte"), zoom=c.get("zoom", 1.0))
        portada_p = carpeta / "portada.jpg"
        ini = float((ed.get("recorte") or [0])[0] or 0)
        edicion.portada(x["archivo"], portada_p, float(ed.get("portada_seg") or ini + 2), ed.get("gancho", ""))
        textos = (f"GANCHO: {ed.get('gancho')}\nTÍTULO: {ed.get('titulo')}\nCAPTION: {ed.get('caption')}\n"
                  f"STREAMER: {x['canal']} ({x['plataforma']})\nLO QUE SE DICE: {_texto_con_tiempos(x['palabras'])}")
        r = revisar(cfg, "clip", video, portada_p, textos, carpeta)
        if r.get("aprobado"):
            break
        if r.get("solo_texto") and vuelta == 0 and r.get("arreglos"):
            ed = {**ed, **{k: v for k, v in (r.get("arreglos") or {}).items() if v}}
            continue
        return None
    else:
        return None
    linea = f"🎥 Clip de {x['canal']}: {x['canal_url']}"
    return {
        "tipo": "clip", "titulo": ed.get("titulo") or ed.get("gancho"), "gancho": ed.get("gancho", ""),
        "caption": _caption_final(cfg, ed.get("caption", ""), ed.get("hashtags"), linea),
        "hashtags": ed.get("hashtags") or ["#GTA6"], "video": str(carpeta / "video.mp4"),
        "portada": str(carpeta / "portada.jpg"), "clip": {k: x[k] for k in ("id", "url", "canal", "canal_url",
                                                                            "plataforma", "vistas", "titulo")},
        "por_que": ed.get("por_que", ""), "revisor": r.get("fallas") or [],
        "guion": " ".join(p[2] for p in x["palabras"])[:1500]}


# ------------------------------------------------------------------ NOVEDAD
def producir_novedad(cfg, carpeta, usados, titulos_previos, modo="novedad"):
    from . import voz
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    guion = None
    for m in ([modo, "guia"] if modo == "novedad" else [modo, "novedad"]):
        material = [n for n in fuentes.noticias(cfg, m) if n["link"] not in usados]
        if not material:
            continue
        txt = "\n\n".join(f"[{i}] {n['titulo']} — {n['fuente']} — {n['fecha'][:16]}\n{n['link']}\n{n['resumen']}"
                          for i, n in enumerate(material[:25]))
        pedido = (f"MODO: {m.upper()}\n\nYA PUBLICAMOS (no repetir):\n- " + "\n- ".join(titulos_previos[-25:] or ["(nada)"])
                  + f"\n\nMATERIAL:\n{txt}")
        g = ia.gemini(_reglas() + "\n\n" + ia.prompt("novedad.md"), pedido, temperatura=0.8)
        if g.get("modo") != "nada" and g.get("escenas"):
            guion = g
            guion["_material"] = txt
            break
    if not guion:
        raise SinMaterial("No hubo noticias ni guías nuevas que valgan la pena.")
    escenas = [str(e).strip() for e in guion["escenas"] if str(e).strip()][:9]
    wav, palabras, _, motor = voz.sintetizar(escenas, carpeta / "voz", cfg)
    dur = edicion.duracion(wav) + 0.5
    # fondo: gameplay de clips del día, sin su audio
    fondos, canales = [], []
    try:
        for x in fuentes.candidatos({**cfg, "clips": {**(cfg.get("clips") or {}), "aceptar_otros_idiomas": True}},
                                    set())[:8]:
            try:
                fondos.append(fuentes.bajar(x, carpeta / "fondos" / f"{len(fondos)}.mp4"))
                canales.append(x)
            except Exception:  # noqa
                continue
            if len(fondos) >= 4:
                break
    except Exception as e:  # noqa
        util.avisar("Fondo de gameplay", util.ocultar(e)[:200])
    fondo = edicion.fondo_de_clips(fondos, carpeta / "fondo.mp4", dur)
    credito = "GAMEPLAY: " + " · ".join(dict.fromkeys(x["canal"] for x in canales[:3])) if canales else ""
    musica = util.RAIZ / cfg.get("musica", "assets/music.mp3")
    video = carpeta / "video.mp4"
    pal = [[p[0], p[1], p[2]] for p in palabras]
    gancho = guion.get("gancho", "")
    for vuelta in range(2):
        edicion.render_narrado(fondo, wav, video, carpeta, gancho, pal, cfg.get("usuario", ""), credito,
                               musica, float(cfg.get("musica_volumen", 0.08)), (cfg.get("clips") or {}).get("zoom", 1.0))
        portada_p = carpeta / "portada.jpg"
        edicion.portada(fondo, portada_p, 1.0, gancho)
        textos = (f"GANCHO: {gancho}\nTÍTULO: {guion.get('titulo')}\nCAPTION: {guion.get('caption')}\n"
                  f"LO QUE SE DICE: {' '.join(escenas)}")
        r = revisar(cfg, guion.get("modo", "novedad"), video, portada_p, textos, carpeta,
                    extra="MATERIAL:\n" + guion["_material"][:6000])
        if r.get("aprobado"):
            break
        if r.get("solo_texto") and vuelta == 0 and r.get("arreglos"):
            arr = r.get("arreglos") or {}
            gancho = arr.get("gancho") or gancho
            guion.update({k: v for k, v in arr.items() if v and k in ("titulo", "caption")})
            continue
        raise SinMaterial("El revisor rechazó la novedad: " + "; ".join(r.get("fallas") or []))
    fuente = guion.get("fuente_nombre", "")
    links = [l for l in guion.get("links") or [] if str(l).startswith("http")][:2]
    visible = [l for l in links if "news.google." not in l]   # los links de Google Noticias son larguísimos
    linea = ("📰 Fuente: " + fuente + (" · " + visible[0] if visible else "")).strip(" ·") if (fuente or visible) else ""
    if canales:
        linea += ("\n" if linea else "") + "🎥 Gameplay: " + " · ".join(
            dict.fromkeys(x["canal_url"] for x in canales[:3]))
    return {
        "tipo": guion.get("modo", "novedad"), "titulo": guion.get("titulo") or gancho, "gancho": gancho,
        "caption": _caption_final(cfg, guion.get("caption", ""), guion.get("hashtags"), linea),
        "hashtags": guion.get("hashtags") or ["#GTA6"], "video": str(video), "portada": str(carpeta / "portada.jpg"),
        "links": links, "noticia": guion.get("noticia", ""), "voz": motor, "revisor": r.get("fallas") or [],
        "fondos": [x["id"] for x in canales], "guion": " ".join(escenas),
        "nota_blog": str(guion.get("nota_blog") or "").strip(), "fuente_nombre": fuente}
