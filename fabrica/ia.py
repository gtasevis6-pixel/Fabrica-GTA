"""Llamadas a Gemini (clave gratuita de Google AI Studio). Devuelve siempre JSON."""
import json
import re
import time

from . import util

API = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿️]")


def _prompt(nombre):
    return (util.RAIZ / "prompts" / nombre).read_text(encoding="utf-8")


def _json_de(texto):
    t = re.sub(r"```(?:json)?", "", texto or "").strip()
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b < 0:
        raise ValueError("La IA no devolvió JSON: " + t[:200])
    return json.loads(t[a:b + 1])


LISTA = "https://generativelanguage.googleapis.com/v1beta/models"
_DESCARTAR = ("image", "tts", "audio", "live", "embed", "native", "exp", "computer", "robotics", "vision", "omni")
# Motivos por los que Google bloquea el pedido por su contenido (no tiene sentido probar otro modelo)
BLOQUEOS = ("PROHIBITED_CONTENT", "SAFETY", "BLOCKLIST", "SPII", "OTHER", "IMAGE_SAFETY", "RECITATION")
_SEGURIDAD = [{"category": c, "threshold": "BLOCK_ONLY_HIGH"} for c in
              ("HARM_CATEGORY_HARASSMENT", "HARM_CATEGORY_HATE_SPEECH", "HARM_CATEGORY_SEXUALLY_EXPLICIT",
               "HARM_CATEGORY_DANGEROUS_CONTENT")]


class Bloqueado(RuntimeError):
    """Google rechazó el pedido por su contenido (pasa con el pedido, no con el modelo)."""
_modelo_ok = None  # el primer modelo que anduvo en esta ejecución se reusa


def _version(nombre):
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", nombre)
    return float(m.group(1)) if m else 0.0


def _descubrir(clave):
    """Pide a Google la lista de modelos vigentes y ordena los Flash del más nuevo al más viejo.
    Así, cuando Google retire un modelo, la fábrica encuentra sola el reemplazo."""
    try:
        r = util.pedir("GET", LISTA, headers={"x-goog-api-key": clave}, params={"pageSize": 1000}, timeout=60)
        modelos = r.json().get("models", []) if r is not None and r.status_code == 200 else []
    except Exception as e:  # noqa
        util.log("No pude listar los modelos de Gemini:", util.ocultar(str(e)))
        return []
    nombres = []
    for m in modelos:
        n = m.get("name", "").split("/")[-1]
        if ("generateContent" in m.get("supportedGenerationMethods", []) and "flash" in n
                and not any(x in n for x in _DESCARTAR)):
            nombres.append(n)
    # primero Flash común, después Lite; dentro de cada grupo, estable antes que preview y versión más nueva primero
    nombres.sort(key=lambda n: ("lite" in n, "preview" in n, -_version(n), n))
    return nombres


def _cuerpo(sistema, usuario, temperatura, modelo, con_pensamiento, con_seguridad=True):
    gen = {"responseMimeType": "application/json", "maxOutputTokens": 32768}
    moderno = "latest" in modelo or _version(modelo) >= 3
    if moderno:
        # Gemini 3+: Google recomienda temperatura 1.0 y, si no se aclara, piensa "a fondo" y gasta
        # todo el cupo de salida pensando. Con nivel bajo alcanza para guiones cortos.
        if con_pensamiento:
            gen["thinkingConfig"] = {"thinkingLevel": util.config().get("gemini_pensamiento", "low")}
    else:
        gen["temperature"] = temperatura
    cuerpo = {
        "systemInstruction": {"parts": [{"text": sistema}]},
        # usuario puede ser texto o una lista de partes (texto + imágenes)
        "contents": [{"role": "user", "parts": usuario if isinstance(usuario, list) else [{"text": usuario}]}],
        "generationConfig": gen,
    }
    if con_seguridad:
        cuerpo["safetySettings"] = _SEGURIDAD
    return cuerpo


def _mensaje(r):
    try:
        return r.json()["error"]["message"][:220]
    except Exception:  # noqa
        return (getattr(r, "text", "") or "")[:220]


def _gemini_una_vuelta(sistema, usuario, temperatura=0.9):
    global _modelo_ok
    clave = util.secreto("GEMINI_API_KEY")
    if not clave:
        raise RuntimeError("Falta el secreto GEMINI_API_KEY (Settings → Secrets and variables → Actions)")
    # primero el que anduvo en esta ejecución; si no, el último que anduvo en otra (queda en data/estado.json)
    guardado = (util.leer_json("data/estado.json", {}) or {}).get("gemini_modelo_ok", "")
    preferidos = ([_modelo_ok] if _modelo_ok else []) + ([guardado] if guardado else []) + \
        util.config().get("gemini_modelos", ["gemini-flash-latest"])
    espera_max = int(util.config().get("gemini_timeout", 60))
    probados, errores, descubiertos, bloqueos = set(), [], False, 0
    cola = list(preferidos)
    while cola or not descubiertos:
        if not cola:
            descubiertos = True
            cola = [m for m in _descubrir(clave) if m not in probados][:5]
            if cola:
                util.log("Busco modelos vigentes de Gemini:", ", ".join(cola))
            continue
        modelo = cola.pop(0)
        if modelo in probados:
            continue
        probados.add(modelo)
        texto, fin = "", ""
        # Si el modelo no acepta algún ajuste (pensamiento o filtros), pruebo sin él.
        for ajustes in ((True, True), (False, True), (False, False)):
            inicio = time.time()
            try:
                # un solo intento por modelo: si no contesta a tiempo, se pasa enseguida al siguiente
                r = util.pedir("POST", API.format(modelo=modelo), headers={"x-goog-api-key": clave},
                               json=_cuerpo(sistema, usuario, temperatura, modelo, *ajustes),
                               intentos=1, espera=10, timeout=espera_max)
            except Exception as e:  # noqa  (Google no contestó a tiempo: paso al modelo siguiente)
                r = None
                util.log(f"Gemini: {modelo} no respondió en {time.time() - inicio:.0f} s, pruebo el siguiente")
                errores.append(f"{modelo}: no respondió ({type(e).__name__})")
                break
            if r is not None and r.status_code == 400 and any(x in _mensaje(r).lower() for x in ("think", "safety")):
                continue
            break
        if r is None:
            continue
        if r.status_code != 200:
            util.log(f"Gemini: {modelo} contestó {r.status_code}: {_mensaje(r)[:120]}")
            errores.append(f"{modelo}: {getattr(r, 'status_code', '?')} {_mensaje(r)}")
            continue
        datos = r.json()
        cand = (datos.get("candidates") or [{}])[0]
        en_pedido = (datos.get("promptFeedback") or {}).get("blockReason", "")
        fin = cand.get("finishReason", "") or en_pedido
        donde = "en lo que le mandamos" if en_pedido and not datos.get("candidates") else "en lo que la IA escribió"
        partes = (cand.get("content") or {}).get("parts", [])
        texto = "".join(p.get("text", "") for p in partes if not p.get("thought"))
        try:
            resultado = _json_de(texto)
            if _modelo_ok != modelo:
                util.log("Modelo de Gemini usado:", modelo)
                try:
                    estado = util.leer_json("data/estado.json", {}) or {}
                    if estado.get("gemini_modelo_ok") != modelo:
                        estado["gemini_modelo_ok"] = modelo
                        util.guardar_json("data/estado.json", estado)
                except Exception:  # noqa
                    pass
            _modelo_ok = modelo
            return resultado
        except Exception as e:  # noqa
            errores.append(f"{modelo}: respuesta sin JSON (motivo: {fin or 'desconocido'}) {str(e)[:80]}")
            if fin in BLOQUEOS:
                bloqueos += 1
                if bloqueos >= 2:  # dos modelos distintos lo rechazan: es el contenido del pedido
                    raise Bloqueado(f"Google bloqueó el pedido por su contenido ({fin}, {donde})")
    raise RuntimeError("Gemini falló con todos los modelos: " + " | ".join(errores))


def prompt(nombre):
    return _prompt(nombre)



def gemini(sistema, usuario, temperatura=0.9):
    """Pide a Gemini. Si todos los modelos están saturados (pasa en días de mucha demanda, como el lanzamiento),
    espera y prueba otra vuelta (config gemini_vueltas, por defecto 3; gemini_espera_vuelta, 60 s)."""
    cfg = util.config()
    vueltas = max(1, int(cfg.get("gemini_vueltas", 3)))
    for n in range(1, vueltas + 1):
        try:
            return _gemini_una_vuelta(sistema, usuario, temperatura)
        except RuntimeError as e:
            texto = str(e)
            saturado = any(x in texto for x in ("503", "429", "no respondió", "high demand", "overloaded",
                                                "UNAVAILABLE", "RESOURCE_EXHAUSTED"))
            if not saturado or n == vueltas or "Falta el secreto" in texto:
                raise
            espera = int(cfg.get("gemini_espera_vuelta", 60)) * n
            util.log(f"Gemini saturado en todos los modelos (vuelta {n} de {vueltas}): espero {espera} s")
            time.sleep(espera)
