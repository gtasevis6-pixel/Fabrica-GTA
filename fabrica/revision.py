"""Tu control antes de publicar. Cada video te llega por mail y espera unos minutos (config.json →
minutos_aprobacion). En ese rato podés entrar al formulario «Revisar video» de GitHub Actions y elegir:
publicar ya, no publicar, u otro (cambia de clip o de tema). Si no hacés nada, se publica solo."""
import json
import os
import subprocess

from . import util

ARCHIVO = "data/pedidos.json"
ACCIONES = {"Publicar ya": "publicar", "No publicar": "cancelar", "Otro clip / otro tema": "otro"}


def ahora_utc():
    return util.datetime.now(util.ZoneInfo("UTC")).isoformat()


def leer_remotos():
    """Los pedidos más nuevos del repo (recién bajados de la rama principal)."""
    try:
        subprocess.run(["git", "fetch", "-q", "origin", "main"], capture_output=True, timeout=60)
        r = subprocess.run(["git", "show", f"origin/main:{ARCHIVO}"], capture_output=True, text=True, timeout=30)
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout)
    except Exception as e:  # noqa
        util.log("No pude leer los pedidos:", util.ocultar(e))
    return util.leer_json(ARCHIVO, []) or []


def nuevos(pedidos, fecha, turno, desde):
    out = []
    for x in pedidos:
        if x.get("fecha") != fecha or x.get("creado", "") <= desde:
            continue
        if str(x.get("turno", "auto")) not in ("auto", str(turno)):
            continue
        out.append(x)
    return sorted(out, key=lambda x: x.get("creado", ""))


def registrar(accion_texto, turno_texto):
    accion = ACCIONES.get(accion_texto, "")
    if not accion:
        raise ValueError(f"Acción desconocida: {accion_texto}")
    turno = turno_texto if str(turno_texto).isdigit() else "auto"
    pedido = {"id": os.getenv("GITHUB_RUN_ID", "local"), "creado": ahora_utc(),
              "fecha": util.ahora().strftime("%Y-%m-%d"), "turno": turno, "accion": accion}
    lista = (util.leer_json(ARCHIVO, []) or []) + [pedido]
    util.guardar_json(ARCHIVO, lista[-80:])
    return pedido


def link_formulario():
    repo = os.getenv("GITHUB_REPOSITORY", "")
    return f"https://github.com/{repo}/actions/workflows/revisar.yml" if repo else ""
