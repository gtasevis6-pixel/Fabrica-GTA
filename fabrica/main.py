"""Fábrica GTA: comandos que usa GitHub Actions.

  toca       ¿hay un turno pendiente ahora? (deja si=true/false y el número de turno)
  generar    arma el video del turno (clip o novedad) y lo deja en out/sitio
  online     espera a que el video esté en la página pública (Instagram lo baja de ahí)
  listo      te manda el mail para revisarlo
  esperar    espera los minutos de aprobación mirando si usaste «Revisar video»
  publicar   lo sube a las redes y guarda el historial
  resumen    muestra el resultado en la ejecución (modo prueba, sin publicar)
  revisar    lo usa el formulario «Revisar video»
  vigia      busca campañas de clipping nuevas de GTA y te avisa
"""
import argparse
import html
import json
import os
import re
import shutil
import sys
import time
import traceback
from datetime import timedelta
from pathlib import Path

from . import util

OUT = util.RAIZ / "out"
SITIO = OUT / "sitio"


# ------------------------------------------------------------------ turnos
def _turnos(cfg):
    return cfg.get("turnos") or [{"hora": "13:30", "tipo": "clip"}, {"hora": "18:30", "tipo": "novedad"},
                                 {"hora": "22:00", "tipo": "clip"}]


def _hora(hoy, txt):
    h, m = (int(x) for x in str(txt).split(":")[:2])
    return hoy.replace(hour=h, minute=m, second=0, microsecond=0)


def _historial():
    return util.leer_json("data/historial.json", []) or []


def _hecho(fecha, turno):
    return any(x.get("fecha") == fecha and int(x.get("turno", 0)) == int(turno) for x in _historial())


def _turno_pendiente(cfg, momento=None):
    """Devuelve (fecha, turno) del primer turno cuya ventana está abierta y que todavía no salió.
    Mira también los turnos de ayer, por si uno de la noche se corre pasada la medianoche."""
    ahora = momento or util.ahora()
    antes = timedelta(minutes=int(cfg.get("minutos_antes", 20)))
    ventana = timedelta(hours=float(cfg.get("ventana_horas", 4)))
    for dia in (ahora - timedelta(days=1), ahora):
        fecha = dia.strftime("%Y-%m-%d")
        for i, t in enumerate(_turnos(cfg), 1):
            inicio = _hora(dia, t["hora"])
            if inicio - antes <= ahora <= inicio + ventana and not _hecho(fecha, i):
                return fecha, i
    return None


def _salida(**kw):
    destino = os.getenv("GITHUB_OUTPUT")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            for k, v in kw.items():
                f.write(f"{k}={v}\n")


def _resumen_md(texto):
    destino = os.getenv("GITHUB_STEP_SUMMARY")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            f.write(texto + "\n")


def toca():
    cfg = util.config()
    manual = os.getenv("TURNO_MANUAL", "").strip()
    if os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch":
        pend = _turno_pendiente(cfg)
        turno = int(manual) if manual.isdigit() else (pend[1] if pend else 1)
        fecha = pend[0] if pend and not manual.isdigit() else util.ahora().strftime("%Y-%m-%d")
        util.log("Corrida manual · turno", turno)
        return _salida(si="true", turno=turno, fecha=fecha)
    if not cfg.get("automatico", True):
        util.log("¿Toca? no: config.json → automatico está en false (solo corridas manuales)")
        return _salida(si="false", turno=0, fecha="")
    pend = _turno_pendiente(cfg)
    util.log("¿Toca?", f"sí, turno {pend[1]} del {pend[0]}" if pend else "no")
    _salida(si="true" if pend else "false", turno=pend[1] if pend else 0, fecha=pend[0] if pend else "")


# ------------------------------------------------------------------ generar
def _usados():
    u = util.leer_json("data/usados.json", {}) or {}
    return set(u.get("clips", [])), set(u.get("links", []))


def _titulos_previos():
    return [x.get("titulo", "") for x in _historial()[-40:]]


def generar(turno, tipo_forzado="", otro=False):
    from . import produccion
    cfg = util.config()
    turno = int(turno or 1)
    tipo = tipo_forzado or (_turnos(cfg)[turno - 1] if turno <= len(_turnos(cfg)) else {"tipo": "clip"})["tipo"]
    previo = util.leer_json("out/publicacion.json", {}) or {}
    excluir = set(previo.get("excluir", []))
    if otro and previo.get("clip"):
        excluir.add(previo["clip"]["id"])
    if otro and previo.get("links"):
        excluir.update(previo["links"])
    carpeta = OUT / "trabajo"
    shutil.rmtree(carpeta, ignore_errors=True)
    clips_usados, links_usados = _usados()
    orden = [tipo] + [t for t in ("clip", "novedad") if t != tipo]
    resultado, errores = None, []
    for t in orden:
        try:
            if t == "clip":
                resultado = produccion.producir_clip(cfg, carpeta, clips_usados, excluir)
            else:
                modo = "guia" if t == "guia" else "novedad"
                resultado = produccion.producir_novedad(cfg, carpeta, links_usados | excluir, _titulos_previos(), modo)
            break
        except produccion.SinMaterial as e:
            errores.append(f"{t}: {e}")
            util.avisar(f"Sin material para «{t}»", str(e))
        except Exception as e:  # noqa
            errores.append(f"{t}: {type(e).__name__}: {util.ocultar(e)[:300]}")
            util.avisar_error(f"generar {t}", e)
            traceback.print_exc()
    fecha = os.getenv("FECHA_TURNO") or util.ahora().strftime("%Y-%m-%d")
    if not resultado and otro and previo.get("archivos"):
        # pediste otro pero no hubo alternativa: queda el que ya estaba listo
        util.avisar("No encontré otro", "Sale el video que ya te había mandado. " + " | ".join(errores))
        return
    shutil.rmtree(SITIO, ignore_errors=True)
    SITIO.mkdir(parents=True, exist_ok=True)
    if not resultado:
        util.guardar_json("out/publicacion.json", {"nada": True, "fecha": fecha, "turno": turno, "errores": errores})
        (SITIO / "index.html").write_text("<p>Hoy no hubo video en este turno.</p>", encoding="utf-8")
        util.log("No hubo video:", " | ".join(errores))
        return
    sello = util.ahora().strftime("%H%M%S")
    nombre_v, nombre_p = f"video-{sello}.mp4", f"portada-{sello}.jpg"
    shutil.copy(resultado["video"], SITIO / nombre_v)
    shutil.copy(resultado["portada"], SITIO / nombre_p)
    (SITIO / "index.html").write_text(
        f'<meta charset="utf-8"><title>{html.escape(resultado["titulo"])}</title>'
        f'<video src="{nombre_v}" controls playsinline style="max-height:90vh"></video>'
        f'<p>{html.escape(resultado["caption"]).replace(chr(10), "<br>")}</p>', encoding="utf-8")
    p = {**{k: v for k, v in resultado.items() if k not in ("video", "portada")},
         "fecha": fecha, "turno": turno, "archivos": {"video": nombre_v, "portada": nombre_p},
         "local": {"video": str(SITIO / nombre_v), "portada": str(SITIO / nombre_p)},
         "excluir": sorted(excluir), "version": previo.get("version", 0) + 1 if otro else 1,
         "creado": util.datetime.now(util.ZoneInfo("UTC")).isoformat()}
    util.guardar_json("out/publicacion.json", p)
    util.log("Listo:", p["tipo"], "·", p["titulo"])


# ------------------------------------------------------------------ online / listo / esperar
def online(base_url):
    p = util.leer_json("out/publicacion.json", {}) or {}
    if p.get("nada"):
        return
    url = base_url.rstrip("/") + "/" + p["archivos"]["video"]
    for _ in range(40):
        try:
            r = util.pedir("HEAD", url, intentos=1, timeout=30)
            if r is not None and r.status_code == 200:
                util.log("Online:", url)
                return
        except Exception:  # noqa
            pass
        time.sleep(10)
    raise RuntimeError("El video no apareció online: " + url)


def listo(base_url):
    from . import publicar as pub
    from . import revision
    e = html.escape
    cfg = util.config()
    p = util.leer_json("out/publicacion.json", {}) or {}
    if p.get("nada"):
        try:
            pub.mail("Turno sin video", "<p>Este turno no salió video:</p><ul>" +
                     "".join(f"<li>{e(x)}</li>" for x in p.get("errores", [])) + "</ul>")
        except Exception as ex:  # noqa
            util.log("No pude mandar el mail:", ex)
        return
    base = base_url.rstrip("/") + "/"
    minutos = int(cfg.get("minutos_aprobacion", 5))
    origen = ""
    if p.get("clip"):
        c = p["clip"]
        origen = (f'<p>Clip original: <a href="{e(c["url"])}">{e(c["canal"])}</a> ({c["vistas"]} vistas en '
                  f'{e(c["plataforma"])})</p>')
    elif p.get("links"):
        origen = "<p>Fuente: " + " · ".join(f'<a href="{e(l)}">{e(l[:60])}</a>' for l in p["links"]) + "</p>"
    rev = ("<p style='color:#a60'>El revisor marcó: " + e("; ".join(p.get("revisor") or [])) + "</p>"
           if p.get("revisor") else "")
    cuerpo = (f'<h2>{e(p["titulo"])}</h2>'
              f'<p><b>Se publica solo en {minutos} minutos</b> si no hacés nada.</p>'
              f'<p><a href="{base}{p["archivos"]["video"]}">▶️ Ver el video</a> · '
              f'<a href="{base}{p["archivos"]["portada"]}">Portada</a></p>{origen}{rev}'
              f'<p>¿Algo no te gusta? Entrá a <a href="{revision.link_formulario()}">Revisar video</a> → '
              f'<b>Run workflow</b> y elegí <b>Publicar ya</b>, <b>No publicar</b> u '
              f'<b>Otro clip / otro tema</b>.</p>'
              f'<p><b>Texto:</b><br>{e(p["caption"]).replace(chr(10), "<br>")}</p>')
    try:
        pub.mail(f'[GTA] Revisá en {minutos} min: {p["titulo"]}', cuerpo)
    except Exception as ex:  # noqa
        util.log("No pude mandar el mail:", ex)
    util.guardar_json("out/mail.json", {"enviado": util.datetime.now(util.ZoneInfo("UTC")).isoformat()})


def esperar(ultima=False):
    from . import revision
    cfg = util.config()
    p = util.leer_json("out/publicacion.json", {}) or {}
    decision = "publicar"
    if not p.get("nada") and os.getenv("GITHUB_EVENT_NAME") == "schedule":
        minutos = float(cfg.get("minutos_aprobacion", 5))
        desde = p.get("creado", "")
        fin = time.time() + minutos * 60
        util.avisar("Esperando tu revisión", f"Se publica solo en {minutos:.0f} minutos si no usás «Revisar video».")
        while time.time() < fin:
            pedidos = revision.nuevos(revision.leer_remotos(), p.get("fecha", ""), p.get("turno", 1), desde)
            if pedidos:
                decision = pedidos[-1].get("accion", "publicar")
                if decision == "otro" and ultima:
                    util.avisar("Ya se cambió una vez", "Sale esta versión.")
                    decision = "publicar"
                break
            time.sleep(20)
    if p.get("nada"):
        decision = "nada"
    util.log("Decisión:", decision)
    util.guardar_json("out/decision.json", {"decision": decision})
    _salida(decision=decision)


# ------------------------------------------------------------------ publicar
def _registrar(p, res):
    u = util.leer_json("data/usados.json", {}) or {}
    clips = u.get("clips", [])
    links = u.get("links", [])
    if p.get("clip"):
        clips.append(p["clip"]["id"])
    clips += p.get("fondos", [])[:1]   # el fondo se puede repetir, pero no siempre el mismo
    links += p.get("links", [])
    u["clips"], u["links"] = clips[-600:], links[-300:]
    util.guardar_json("data/usados.json", u)
    h = _historial()
    h.append({"fecha": p["fecha"], "turno": p["turno"], "tipo": p["tipo"], "titulo": p["titulo"],
              "clip": (p.get("clip") or {}).get("url", ""), "streamer": (p.get("clip") or {}).get("canal", ""),
              "links": p.get("links", []), "resultados": res,
              "hora": util.ahora().strftime("%H:%M")})
    util.guardar_json("data/historial.json", h[-500:])
    carpeta = util.RAIZ / "publicaciones"
    carpeta.mkdir(exist_ok=True)
    (carpeta / f"{p['fecha']}-t{p['turno']}.md").write_text(
        f"# {p['titulo']}\n\n- Tipo: {p['tipo']}\n- Hora: {util.ahora():%H:%M}\n"
        + (f"- Clip: {p['clip']['url']} ({p['clip']['canal']})\n" if p.get("clip") else "")
        + "".join(f"- Fuente: {l}\n" for l in p.get("links", []))
        + "\n## Resultados\n" + "".join(f"- {k}: {v}\n" for k, v in res.items())
        + f"\n## Texto\n\n{p['caption']}\n", encoding="utf-8")


def _slug(t):
    import unicodedata
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:60] or "video"


def _nota_blog(p, res):
    """Deja en notas/ una nota en Markdown por cada video publicado, con los datos arriba (front matter).
    Es el formato que leen Jekyll, Hugo o Astro: el día que armemos el blog, ya tiene todo el archivo."""
    yt = res.get("youtube", "")
    yt_url = f"https://www.youtube.com/shorts/{yt}" if yt and not yt.startswith("ERROR") else ""
    clip = p.get("clip") or {}
    datos = {
        "title": p["titulo"], "date": util.ahora().isoformat(timespec="minutes"), "tipo": p["tipo"],
        "tags": [h.lstrip("#") for h in p.get("hashtags", [])], "gancho": p.get("gancho", ""),
        "youtube": yt_url, "instagram_id": res.get("instagram_reel", "") if not str(
            res.get("instagram_reel", "")).startswith("ERROR") else "",
        "fuentes": p.get("links", []), "fuente_nombre": p.get("fuente_nombre", ""),
        "clip_url": clip.get("url", ""), "streamer": clip.get("canal", ""), "streamer_url": clip.get("canal_url", ""),
    }
    cabeza = "---\n" + "".join(f"{k}: {json.dumps(v, ensure_ascii=False)}\n" for k, v in datos.items()
                               if v not in ("", [], None)) + "---\n\n"
    if p.get("nota_blog"):
        cuerpo = p["nota_blog"]
    elif clip:
        cuerpo = (f"{p.get('caption', '').split(chr(10))[0]}\n\nClip de [{clip.get('canal')}]({clip.get('canal_url')})"
                  f" · [ver el original]({clip.get('url')}).")
    else:
        cuerpo = p.get("guion", "")
    if p.get("guion") and p.get("tipo") != "clip":
        cuerpo += "\n\n<!-- guion del video: " + p["guion"].replace("--", "—") + " -->"
    carpeta = util.RAIZ / "notas"
    carpeta.mkdir(exist_ok=True)
    (carpeta / f"{p['fecha']}-t{p['turno']}-{_slug(p['titulo'])}.md").write_text(cabeza + cuerpo + "\n",
                                                                               encoding="utf-8")


def publicar(base_url, simulado=False):
    from . import publicar as pub
    cfg = util.config()
    p = util.leer_json("out/publicacion.json", {}) or {}
    d = (util.leer_json("out/decision.json", {}) or {}).get("decision", "publicar")
    if p.get("nada"):
        util.log("No hay video en este turno.")
        h = _historial()
        h.append({"fecha": p.get("fecha"), "turno": p.get("turno"), "tipo": "nada", "titulo": "",
                  "errores": p.get("errores", [])})
        util.guardar_json("data/historial.json", h[-500:])
        return
    if d == "cancelar":
        util.log("Pediste no publicar este video.")
        h = _historial()
        h.append({"fecha": p["fecha"], "turno": p["turno"], "tipo": p["tipo"], "titulo": p["titulo"],
                  "resultados": {"todas": "cancelado por vos"}})
        util.guardar_json("data/historial.json", h[-500:])
        if p.get("clip"):
            u = util.leer_json("data/usados.json", {}) or {}
            u["clips"] = (u.get("clips", []) + [p["clip"]["id"]])[-600:]
            util.guardar_json("data/usados.json", u)
        return
    base = base_url.rstrip("/") + "/"
    video_url, portada_url = base + p["archivos"]["video"], base + p["archivos"]["portada"]
    video_local = p["local"]["video"]
    redes = cfg.get("publicar") or {}
    res = {}

    def intentar(nombre, fn):
        if not redes.get(nombre):
            return
        try:
            res[nombre] = str(fn())
            util.log("Publicado en", nombre, res[nombre])
        except Exception as e:  # noqa
            res[nombre] = "ERROR: " + util.ocultar(e)[:300]
            util.avisar_error(f"publicar en {nombre}", e)

    titulo = re.sub(r"\s+", " ", p["titulo"]).strip()[:90]
    tags_yt = [h.lstrip("#") for h in p.get("hashtags", [])] + ["GTA 6", "GTA VI", "Grand Theft Auto VI"]
    intentar("youtube", lambda: pub.youtube(video_local, f"{titulo} #GTA6", p["caption"], tags_yt,
                                            cfg.get("youtube_privacidad", "public")))
    intentar("instagram_reel", lambda: pub.instagram_reel(video_url, portada_url, p["caption"]))
    intentar("facebook", lambda: pub.facebook_reel(video_local, p["caption"], titulo))
    intentar("tiktok", lambda: pub.tiktok(video_local, p["caption"], cfg.get("tiktok_privacidad", "SELF_ONLY")))
    if not res:
        res["redes"] = "ninguna activada en config.json → publicar"
    _registrar(p, res)
    salio = any(k in redes and not str(v).startswith("ERROR") for k, v in res.items())
    try:
        if salio:
            _nota_blog(p, res)
        else:
            util.log("No salió en ninguna red: no guardo nota para el blog.")
    except Exception as e:  # noqa
        util.log("No pude guardar la nota para el blog:", e)
    lineas = "".join(f"<li><b>{html.escape(k)}</b>: {html.escape(v)}</li>" for k, v in res.items())
    try:
        pub.mail(f"[GTA] Publicado: {p['titulo']}", f"<h3>{html.escape(p['titulo'])}</h3><ul>{lineas}</ul>"
                 f'<p><a href="{video_url}">Ver el video</a></p>')
    except Exception as ex:  # noqa
        util.log("No pude mandar el mail:", ex)
    _resumen_md(f"## ✅ Publicado: {p['titulo']}\n\n" + "".join(f"- **{k}**: {v}\n" for k, v in res.items()))


def resumen(base_url):
    p = util.leer_json("out/publicacion.json", {}) or {}
    if p.get("nada"):
        _resumen_md("## Sin video en este turno\n\n" + "".join(f"- {x}\n" for x in p.get("errores", [])))
        return
    base = base_url.rstrip("/") + "/"
    md = (f"## 🎬 {p['titulo']} (prueba, no se publicó)\n\n"
          f"**[▶️ Ver el video]({base}{p['archivos']['video']})** · [Portada]({base}{p['archivos']['portada']})\n\n"
          f"![portada]({base}{p['archivos']['portada']})\n\n"
          f"- Tipo: {p['tipo']}\n")
    if p.get("clip"):
        md += f"- Clip: [{p['clip']['canal']}]({p['clip']['url']}) · {p['clip']['vistas']} vistas\n"
        md += f"- Por qué este: {p.get('por_que', '')}\n"
    for l in p.get("links", []):
        md += f"- Fuente: {l}\n"
    if p.get("revisor"):
        md += f"- Revisor: {'; '.join(p['revisor'])}\n"
    md += f"\n**Texto:**\n\n```\n{p['caption']}\n```\n"
    _resumen_md(md)


# ------------------------------------------------------------------ formulario
def revisar():
    from . import revision
    try:
        x = revision.registrar(os.getenv("ACCION", ""), os.getenv("TURNO_PEDIDO", ""))
    except ValueError as e:
        _resumen_md(f"❌ {e}")
        sys.exit(1)
    msg = {"publicar": "Listo: se publica en menos de un minuto.",
           "cancelar": "Listo: este video no se publica.",
           "otro": "Listo: la fábrica busca otro clip (u otro tema) y te manda la versión nueva por mail."}[x["accion"]]
    util.log(msg)
    _resumen_md(f"## Revisar video\n\n{msg}")


# ------------------------------------------------------------------ vigía de campañas
def vigia():
    """Busca campañas de clipping de GTA en tableros públicos y te avisa por mail si aparece una nueva.
    Es experimental: si los sitios cambian o piden iniciar sesión, solo deja un aviso."""
    from . import fuentes, publicar as pub
    cfg = util.config()
    v = cfg.get("vigia_campanas") or {}
    if not v.get("activo", True):
        return
    vistos = set(util.leer_json("data/campanas.json", []) or [])
    nuevos = []
    for url in v.get("paginas", ["https://contentrewards.com/c/discover", "https://gtaviclipper.com/board"]):
        try:
            r = util.pedir("GET", url, intentos=1, headers=fuentes.UA, timeout=40)
            if r is None or r.status_code != 200:
                util.log("Vigía: no pude leer", url, getattr(r, "status_code", "?"))
                continue
            texto = re.sub(r"<[^>]+>", "\n", r.text)
            texto = html.unescape(texto)
        except Exception as e:  # noqa
            util.log("Vigía: error en", url, e)
            continue
        for linea in {l.strip() for l in texto.splitlines()}:
            if 6 <= len(linea) <= 120 and re.search(r"\bGTA\b|Grand Theft|Leonida|Vice City", linea, re.I) \
                    and re.search(r"campa|clip|\$|reward", linea, re.I):
                clave = re.sub(r"\W+", "", linea.lower())
                if clave not in vistos:
                    vistos.add(clave)
                    nuevos.append((linea, url))
    util.guardar_json("data/campanas.json", sorted(vistos)[-800:])
    if nuevos:
        util.log("Vigía: campañas o menciones nuevas:", len(nuevos))
        cuerpo = "<p>Apareció algo nuevo sobre campañas de clipping de GTA. Revisalo antes de que se agote:</p><ul>" + \
                 "".join(f'<li>{html.escape(l)} — <a href="{u}">{u}</a></li>' for l, u in nuevos[:20]) + "</ul>"
        try:
            pub.mail("[GTA] Posible campaña de clipping nueva", cuerpo)
        except Exception as ex:  # noqa
            util.log("No pude mandar el mail:", ex)


# ------------------------------------------------------------------ entrada
def principal():
    ap = argparse.ArgumentParser()
    ap.add_argument("comando")
    ap.add_argument("--base-url", default="")
    ap.add_argument("--turno", default=os.getenv("TURNO", "1"))
    ap.add_argument("--tipo", default=os.getenv("TIPO", ""))
    ap.add_argument("--otro", action="store_true")
    ap.add_argument("--ultima", action="store_true")
    a = ap.parse_args()
    try:
        if a.comando == "toca":
            toca()
        elif a.comando == "generar":
            generar(a.turno, a.tipo, a.otro)
        elif a.comando == "online":
            online(a.base_url)
        elif a.comando == "listo":
            listo(a.base_url)
        elif a.comando == "esperar":
            esperar(a.ultima)
        elif a.comando == "publicar":
            publicar(a.base_url)
        elif a.comando == "resumen":
            resumen(a.base_url)
        elif a.comando == "revisar":
            revisar()
        elif a.comando == "vigia":
            vigia()
        else:
            raise SystemExit(f"Comando desconocido: {a.comando}")
    except SystemExit:
        raise
    except Exception as e:  # noqa
        util.avisar_error(a.comando, e)
        raise


if __name__ == "__main__":
    principal()
