"""Reintentar publicación: vuelve a subir a Instagram y Facebook los videos que fallaron ahí.

Los videos de cada corrida quedan guardados 1 día en la corrida misma de GitHub (el artifact «github-pages»).
`preparar` busca en el historial lo que falló (últimos 2 días), baja el video de su corrida y lo deja en
out/reintento/ para que el workflow lo ponga online; `publicar` lo sube solo en las redes donde falló.
"""
import html
import io
import json
import os
import re
import tarfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from . import util

REDES_REINTENTABLES = ("instagram_reel", "facebook")
SALIDA = util.RAIZ / "out" / "reintento"
API = "https://api.github.com/repos/"


def _gh(ruta, **kw):
    token = util.secreto("GITHUB_TOKEN")
    repo = os.getenv("GITHUB_REPOSITORY", "")
    if not token or not repo:
        raise RuntimeError("Este comando corre solo en GitHub Actions (falta GITHUB_TOKEN o GITHUB_REPOSITORY)")
    h = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    return util.pedir("GET", ruta if ruta.startswith("http") else API + repo + ruta, headers=h, **kw)


def pendientes(historial, cfg, hoy=None, dias=2):
    """Entradas del historial con Instagram o Facebook en ERROR, de los últimos `dias` días."""
    hoy = hoy or util.ahora()
    desde = (hoy - timedelta(days=dias)).strftime("%Y-%m-%d")
    activas = {k for k, v in (cfg.get("publicar") or {}).items() if v}
    out = []
    for i, x in enumerate(historial):
        if x.get("fecha", "") < desde or x.get("tipo") in ("nada", None):
            continue
        res = x.get("resultados") or {}
        fallas = [k for k in REDES_REINTENTABLES if k in activas and str(res.get(k, "")).startswith("ERROR")]
        if fallas:
            out.append((i, x, fallas))
    return out


def _sitio_de_artifact(art):
    """Baja un artifact de Pages y devuelve {nombre: bytes} de su contenido."""
    r = _gh(art["archive_download_url"], timeout=300)
    if r is None or r.status_code != 200:
        raise RuntimeError(f"no pude bajar el artifact {art.get('name')}: {getattr(r, 'status_code', '?')}")
    archivos = {}
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for n in z.namelist():
            if n.endswith(".tar"):
                with tarfile.open(fileobj=io.BytesIO(z.read(n))) as t:
                    for m in t.getmembers():
                        if m.isfile():
                            archivos[Path(m.name).name] = t.extractfile(m).read()
    return archivos


def _titulo_y_texto(index_html):
    t = re.search(r"<title>(.*?)</title>", index_html, re.S)
    p = re.search(r"<p>(.*?)</p>", index_html, re.S)
    titulo = html.unescape(t.group(1)).strip() if t else ""
    texto = html.unescape(re.sub(r"<br\s*/?>", "\n", p.group(1))).strip() if p else ""
    return titulo, texto


def _corridas(fecha):
    """Corridas de «Fábrica GTA» alrededor de esa fecha que todavía tienen archivos."""
    d = datetime.strptime(fecha, "%Y-%m-%d")
    rango = f"{(d - timedelta(days=1)):%Y-%m-%d}..{(d + timedelta(days=2)):%Y-%m-%d}"
    r = _gh("/actions/workflows/diario.yml/runs", params={"created": rango, "per_page": 100})
    if r is None or r.status_code != 200:
        raise RuntimeError("no pude listar las corridas: " + str(getattr(r, "status_code", "?")))
    return [c for c in r.json().get("workflow_runs", []) if c.get("status") == "completed"]


def _buscar_video(entrada, cache):
    """Encuentra en las corridas el video publicado de esa entrada (por número de corrida o por título)."""
    corridas = [{"id": entrada["run"]}] if entrada.get("run") else _corridas(entrada["fecha"])
    for c in corridas:
        if c["id"] not in cache:
            r = _gh(f"/actions/runs/{c['id']}/artifacts")
            arts = [a for a in (r.json().get("artifacts", []) if r is not None and r.status_code == 200 else [])
                    if a.get("name", "").startswith("github-pages") and not a.get("expired")]
            cache[c["id"]] = []
            # primero la última versión (si pediste «otro», la que salió es la más nueva)
            for a in sorted(arts, key=lambda a: a["name"], reverse=True):
                try:
                    cache[c["id"]].append(_sitio_de_artifact(a))
                except Exception as e:  # noqa
                    util.log("No pude abrir", a.get("name"), "de la corrida", c["id"], ":", e)
        for sitio in cache[c["id"]]:
            idx = sitio.get("index.html", b"").decode("utf-8", "ignore")
            titulo, texto = _titulo_y_texto(idx)
            video = next((n for n in sitio if n.startswith("video-") and n.endswith(".mp4")), None)
            if not video:
                continue
            if entrada.get("run") or titulo.strip() == str(entrada.get("titulo", "")).strip():
                portada = next((n for n in sitio if n.startswith("portada-")), None)
                return sitio, video, portada, texto
    return None


def preparar():
    cfg = util.config()
    h = util.leer_json("data/historial.json", []) or []
    lista = pendientes(h, cfg)
    SALIDA.mkdir(parents=True, exist_ok=True)
    plan, sin_video, cache = [], [], {}
    for i, x, fallas in lista:
        try:
            hallado = _buscar_video(x, cache)
        except Exception as e:  # noqa
            hallado = None
            util.log("Error buscando el video de", x.get("titulo"), ":", util.ocultar(e))
        if not hallado:
            sin_video.append(x.get("titulo", "?"))
            continue
        sitio, video, portada, texto = hallado
        pre = f"r{len(plan) + 1}-"
        (SALIDA / (pre + video)).write_bytes(sitio[video])
        if portada:
            (SALIDA / (pre + portada)).write_bytes(sitio[portada])
        plan.append({"indice": i, "titulo": x.get("titulo", ""), "redes": fallas, "texto": texto,
                     "video": pre + video, "portada": (pre + portada) if portada else ""})
    (SALIDA / "index.html").write_text("<p>Reintento de publicación.</p>", encoding="utf-8")
    util.guardar_json("out/reintento.json", {"plan": plan, "sin_video": sin_video})
    util.log(f"Para reintentar: {len(plan)} video(s); sin archivo (más de 1 día): {len(sin_video)}")
    destino = os.getenv("GITHUB_OUTPUT")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            f.write(f"hay={'true' if plan else 'false'}\n")
    if not lista:
        util.log("No hay nada que reintentar: todo lo de los últimos 2 días salió en Instagram y Facebook.")


def publicar(base_url, simulado=False):
    from . import publicar as pub
    d = util.leer_json("out/reintento.json", {}) or {}
    h = util.leer_json("data/historial.json", []) or []
    base = base_url.rstrip("/") + "/"
    filas = []
    for item in d.get("plan", []):
        x = h[item["indice"]]
        res = x.setdefault("resultados", {})
        texto, titulo = item["texto"] or x.get("titulo", ""), x.get("titulo", "")
        for red in item["redes"]:
            try:
                if red == "instagram_reel":
                    v = pub.instagram_reel(base + item["video"], (base + item["portada"]) if item["portada"] else "",
                                           texto)
                else:
                    v = pub.facebook_reel(str(SALIDA / item["video"]), texto, titulo)
                res[red] = str(v)
                filas.append(f"✅ {titulo} → {red}")
            except Exception as e:  # noqa
                res[red] = "ERROR: " + util.ocultar(e)[:300]
                filas.append(f"❌ {titulo} → {red}: {util.ocultar(e)[:150]}")
        x.setdefault("reintentos", []).append(util.ahora().strftime("%Y-%m-%d %H:%M"))
    util.guardar_json("data/historial.json", h)
    faltan = d.get("sin_video", [])
    md = "## Reintento de publicación\n\n" + ("".join(f"- {f}\n" for f in filas) or "- Nada para reintentar.\n")
    if faltan:
        md += ("\nNo se pudieron rescatar (GitHub guarda los videos 1 día): " + ", ".join(faltan) + "\n")
    destino = os.getenv("GITHUB_STEP_SUMMARY")
    if destino:
        with open(destino, "a", encoding="utf-8") as f:
            f.write(md)
    util.log(md)
    try:
        pub.mail("Reintento de publicación", "<p>" + "<br>".join(html.escape(f) for f in filas or ["Nada para reintentar."])
                 + "</p>" + (f"<p>Sin archivo: {html.escape(', '.join(faltan))}</p>" if faltan else ""))
    except Exception as e:  # noqa
        util.log("No pude mandar el mail:", e)


def online(base_url):
    d = util.leer_json("out/reintento.json", {}) or {}
    import time
    for item in d.get("plan", []):
        url = base_url.rstrip("/") + "/" + item["video"]
        for _ in range(40):
            r = None
            try:
                r = util.pedir("HEAD", url, intentos=1, timeout=30)
            except Exception:  # noqa
                pass
            if r is not None and r.status_code == 200:
                break
            time.sleep(10)
        else:
            raise RuntimeError("El video no apareció online: " + url)
