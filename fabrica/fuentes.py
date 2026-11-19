"""De dónde salen los clips y las noticias.

- Twitch (API oficial y gratuita): los clips más vistos de GTA de las últimas horas, filtrados por idioma.
- Kick (experimental): sus clips más vistos de GTA. Kick no tiene API pública para esto y a veces bloquea
  los servidores de GitHub; si falla, se sigue con Twitch sin cortar nada.
- Noticias: Google Noticias en español, RockstarINTEL y el subreddit de GTA 6 (por RSS).

X, TikTok e Instagram no tienen una forma gratuita y permitida de buscar y bajar videos de otros,
así que no se usan como fuente de clips."""
import html
import re
import subprocess
import xml.etree.ElementTree as ET
from datetime import timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote_plus

from . import util

HELIX = "https://api.twitch.tv/helix/"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0 Safari/537.36"}


# ------------------------------------------------------------------ Twitch
_token = None


def _twitch_headers():
    global _token
    cid, cs = util.secreto("TWITCH_CLIENT_ID"), util.secreto("TWITCH_CLIENT_SECRET")
    if not (cid and cs):
        raise RuntimeError("faltan los secretos TWITCH_CLIENT_ID y TWITCH_CLIENT_SECRET (ver README)")
    if not _token:
        r = util.pedir("POST", "https://id.twitch.tv/oauth2/token",
                       params={"client_id": cid, "client_secret": cs, "grant_type": "client_credentials"})
        if r is None or r.status_code != 200:
            raise RuntimeError("Twitch no dio acceso: " + util.ocultar(getattr(r, "text", ""))[:200])
        _token = r.json()["access_token"]
    return {"Client-Id": cid, "Authorization": f"Bearer {_token}"}


def _twitch_juego(nombre):
    r = util.pedir("GET", HELIX + "games", headers=_twitch_headers(), params={"name": nombre})
    datos = (r.json().get("data") if r is not None and r.status_code == 200 else None) or []
    return datos[0]["id"] if datos else None


def twitch_clips(cfg, horas=None):
    """Clips de los juegos de config.json → fuentes.twitch.juegos, de las últimas `horas`, más vistos primero."""
    f = (cfg.get("fuentes") or {}).get("twitch") or {}
    horas = horas or f.get("horas", 24)
    hasta = util.datetime.now(util.ZoneInfo("UTC"))
    desde = hasta - timedelta(hours=horas)
    salida = []
    for juego in f.get("juegos", ["Grand Theft Auto VI"]):
        gid = _twitch_juego(juego)
        if not gid:
            util.log("Twitch no encontró el juego:", juego)
            continue
        cursor = None
        for _ in range(int(f.get("paginas", 3))):
            params = {"game_id": gid, "first": 100, "started_at": desde.strftime("%Y-%m-%dT%H:%M:%SZ"),
                      "ended_at": hasta.strftime("%Y-%m-%dT%H:%M:%SZ")}
            if cursor:
                params["after"] = cursor
            r = util.pedir("GET", HELIX + "clips", headers=_twitch_headers(), params=params)
            if r is None or r.status_code != 200:
                util.log("Twitch no devolvió clips:", getattr(r, "status_code", "?"))
                break
            j = r.json()
            for c in j.get("data", []):
                salida.append({
                    "plataforma": "twitch", "id": "tw-" + c["id"], "url": c["url"], "titulo": c.get("title", ""),
                    "canal": c.get("broadcaster_name", ""), "canal_url": "https://twitch.tv/" +
                    (c.get("broadcaster_name", "") or "").lower().replace(" ", ""),
                    "vistas": int(c.get("view_count", 0)), "duracion": float(c.get("duration", 0)),
                    "idioma": (c.get("language") or "").lower(), "juego": juego, "creado": c.get("created_at", ""),
                    "miniatura": c.get("thumbnail_url", "")})
            cursor = (j.get("pagination") or {}).get("cursor")
            if not cursor:
                break
        if salida:
            break  # si el primer juego (GTA VI) ya tiene clips, no hace falta el de respaldo
    util.log(f"Twitch: {len(salida)} clips en las últimas {horas} h")
    return salida


# ------------------------------------------------------------------ Kick (experimental)
def kick_clips(cfg):
    f = (cfg.get("fuentes") or {}).get("kick") or {}
    if not f.get("activo"):
        return []
    salida = []
    for slug in f.get("categorias", ["grand-theft-auto-vi"]):
        for url in (f"https://kick.com/api/v2/categories/{slug}/clips?sort=view&time=day",
                    f"https://kick.com/api/v2/clips?category={slug}&sort=view&time=day"):
            try:
                r = util.pedir("GET", url, intentos=1, headers={**UA, "Accept": "application/json"}, timeout=30)
                if r is None or r.status_code != 200:
                    continue
                datos = r.json()
            except Exception:  # noqa
                continue
            lista = datos.get("clips") if isinstance(datos, dict) else datos
            for c in lista or []:
                if not isinstance(c, dict):
                    continue
                canal = ((c.get("channel") or {}).get("username") or (c.get("channel") or {}).get("slug") or "")
                cid = str(c.get("id") or "")
                if not cid or not canal:
                    continue
                salida.append({
                    "plataforma": "kick", "id": "kk-" + cid, "url": f"https://kick.com/{canal}?clip={cid}",
                    "video_url": c.get("clip_url") or c.get("video_url") or "", "titulo": c.get("title", ""),
                    "canal": canal, "canal_url": f"https://kick.com/{canal}",
                    "vistas": int(c.get("view_count") or c.get("views") or 0),
                    "duracion": float(c.get("duration") or 0), "idioma": (c.get("language") or "").lower(),
                    "juego": slug, "creado": c.get("created_at", "")})
            if salida:
                break
    util.log(f"Kick: {len(salida)} clips" + ("" if salida else " (Kick no respondió o bloqueó a GitHub)"))
    return salida


# ------------------------------------------------------------------ elegir candidatos
def candidatos(cfg, usados, horas=None):
    """Junta Twitch y Kick, saca los ya usados y los de canales bloqueados, y ordena:
    primero los streamers con campaña de clipping activa, después idioma preferido y vistas."""
    c = cfg.get("clips") or {}
    idiomas = [x.lower() for x in c.get("idiomas", ["es"])]
    otros = bool(c.get("aceptar_otros_idiomas", True))
    bloqueados = {x.lower() for x in c.get("canales_bloqueados", [])}
    campana = {x.lower() for x in c.get("streamers_con_campana", [])}
    dmin, dmax = float(c.get("duracion_min", 8)), float(c.get("duracion_max", 60))
    vmin = int(c.get("vistas_minimas", 50))
    todos = []
    for fn in (twitch_clips, kick_clips):
        try:
            todos += fn(cfg) if fn is kick_clips else fn(cfg, horas)
        except Exception as e:  # noqa
            util.avisar(f"Fuente {fn.__name__}", util.ocultar(e))
    vistos, out = set(), []
    for x in todos:
        if x["id"] in usados or x["id"] in vistos or x["canal"].lower() in bloqueados:
            continue
        if not (dmin <= x["duracion"] <= dmax) or x["vistas"] < vmin:
            continue
        if x["idioma"] not in idiomas and not otros:
            continue
        vistos.add(x["id"])
        out.append(x)

    def orden(x):
        return (x["canal"].lower() not in campana, x["idioma"] not in idiomas, -x["vistas"])
    out.sort(key=orden)
    return out


# ------------------------------------------------------------------ bajar un clip
def _twitch_mp4(clip):
    """Respaldo si yt-dlp falla: pide a Twitch el link directo del clip (el mismo que usa su web)."""
    slug = clip["url"].rstrip("/").split("/")[-1].split("?")[0]
    cuerpo = [{"operationName": "VideoAccessToken_Clip", "variables": {"slug": slug},
               "extensions": {"persistedQuery": {"version": 1, "sha256Hash":
                              "36b89d2507fce29e5ca551df756d27c1cfe079e2609642b4390aa4c35796eb11"}}}]
    r = util.pedir("POST", "https://gql.twitch.tv/gql", intentos=2, timeout=30, json=cuerpo,
                   headers={"Client-ID": "kimne78kx3ncx6brgo4mv6wki5h1ko", **UA})
    datos = (r.json() if r is not None and r.status_code == 200 else [{}])
    c = ((datos[0] if isinstance(datos, list) else datos).get("data") or {}).get("clip") or {}
    tok = c.get("playbackAccessToken") or {}
    calidades = sorted(c.get("videoQualities") or [], key=lambda q: -int(float(q.get("quality") or 0)))
    if not (tok and calidades):
        return ""
    return calidades[0]["sourceURL"] + f"?sig={tok['signature']}&token={quote_plus(tok['value'])}"


def bajar(clip, destino):
    """Baja el clip con yt-dlp (lo mantiene la comunidad y entiende Twitch y Kick).
    Para Twitch, si yt-dlp falla, prueba con el link directo."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    fuentes = [clip.get("video_url")] if clip.get("video_url") else []
    fuentes.append(clip["url"])
    if clip.get("plataforma") == "twitch":
        fuentes.append("twitch-directo")
    error = ""
    for url in fuentes:
        if url == "twitch-directo":
            try:
                url = _twitch_mp4(clip)
            except Exception as e:  # noqa
                error = str(e)
                url = ""
            if not url:
                continue
        if ".mp4" in url.split("?")[0] or ".m3u8" in url:
            cmd = ["ffmpeg", "-y", "-v", "error", "-i", url, "-c", "copy", str(destino)]
        else:
            cmd = ["yt-dlp", "-q", "--no-warnings", "--no-playlist", "-f", "best[ext=mp4]/best",
                   "--merge-output-format", "mp4", "-o", str(destino), url]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=240)
        except Exception as e:  # noqa
            error = str(e)
            continue
        if r.returncode == 0 and destino.exists() and destino.stat().st_size > 50_000:
            return destino
        error = (r.stderr or "")[-300:]
    raise RuntimeError(f"No pude bajar {clip['url']}: {error}")


# ------------------------------------------------------------------ noticias
def _rss(url, fuente, limite=15):
    try:
        r = util.pedir("GET", url, intentos=2, headers=UA, timeout=40)
        if r is None or r.status_code != 200:
            return []
        raiz = ET.fromstring(r.content)
    except Exception as e:  # noqa
        util.log("RSS no leído:", fuente, util.ocultar(e)[:120])
        return []
    ns = {"a": "http://www.w3.org/2005/Atom"}
    items = raiz.findall(".//item") or raiz.findall(".//a:entry", ns)
    out = []
    for it in items[:limite]:
        def t(tag):
            x = it.find(tag) if not tag.startswith("a:") else it.find(tag, ns)
            return (x.text or "").strip() if x is not None and x.text else ""
        titulo = t("title") or t("a:title")
        link = t("link")
        if not link:
            le = it.find("a:link", ns)
            link = le.get("href", "") if le is not None else ""
        fecha_txt = t("pubDate") or t("a:updated") or t("a:published")
        try:
            fecha = parsedate_to_datetime(fecha_txt) if "," in fecha_txt else util.datetime.fromisoformat(
                fecha_txt.replace("Z", "+00:00"))
        except Exception:  # noqa
            fecha = None
        resumen = re.sub(r"<[^>]+>", " ", html.unescape(t("description") or t("a:content") or t("a:summary")))
        resumen = re.sub(r"\s+", " ", resumen).strip()[:600]
        if titulo and link:
            out.append({"fuente": fuente, "titulo": html.unescape(titulo), "link": link,
                        "fecha": fecha.isoformat() if fecha else "", "resumen": resumen})
    return out


def noticias(cfg, modo="novedad", horas=48):
    """Noticias recientes de GTA 6. modo «guia» busca guías, trucos y secretos en vez de novedades."""
    n = cfg.get("noticias") or {}
    busquedas = n.get("busquedas_guia" if modo == "guia" else "busquedas", ["GTA 6"])
    items = []
    for q in busquedas:
        url = f"https://news.google.com/rss/search?q={quote_plus(q)}+when:3d&hl=es-419&gl=AR&ceid=AR:es-419"
        items += _rss(url, "Google Noticias")
    for f in n.get("rss", []):
        items += _rss(f["url"], f["nombre"])
    limite = util.datetime.now(util.ZoneInfo("UTC")) - timedelta(hours=horas)
    vistos, out = set(), []
    for x in items:
        clave = re.sub(r"\W+", "", x["titulo"].lower())[:60]
        if clave in vistos:
            continue
        vistos.add(clave)
        if x["fecha"]:
            try:
                if util.datetime.fromisoformat(x["fecha"]) < limite:
                    continue
            except Exception:  # noqa
                pass
        out.append(x)
    util.log(f"Noticias ({modo}): {len(out)} de las últimas {horas} h")
    return out
