"""Voz de respaldo (Microsoft Edge, gratis) y utilidades de texto para la voz.
La voz principal es la de Gemini (ver voz.py); esto se usa solo si Gemini falla."""
import asyncio
import os
import re
import subprocess
import time

from . import util

PAD = 0.06       # respiro entre escenas (seg)
COLA = 0.10      # silencio que queda después de la última palabra
TTS_ENGINE = os.getenv("TTS_ENGINE", "edge")


def _cfg(k, defecto):
    try:
        return util.config().get(k) or defecto
    except Exception:  # noqa
        return defecto


VOICE = os.getenv("TTS_VOICE") or _cfg("voz", "es-MX-JorgeNeural")
RATE = _cfg("voz_velocidad", "+12%")
MAX_PAUSA = float(_cfg("voz_pausa_maxima", 0.28))


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("Falló " + " ".join(cmd[:4]) + ": " + r.stderr[-800:])
    return r.stdout


def duration(path):
    return float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                      "-of", "default=nw=1:nk=1", str(path)]).strip())


# Ojo: lo que devuelve texto_voz también se usa como subtítulo, así que acá solo van cambios que se lean bien.
_PRONUNCIA = {"R*": "Rockstar"}


def texto_voz(t):
    """Ajustes para que la voz lea natural (siglas y puntos suspensivos)."""
    t = re.sub(r"\.{2,}|…", ",", t or "")
    for sigla, dicha in _PRONUNCIA.items():
        t = t.replace(sigla, dicha)
    return re.sub(r"\s+", " ", t).strip()


async def tts_edge(text, mp3_path):
    import edge_tts
    try:
        comm = edge_tts.Communicate(text, VOICE, rate=RATE, boundary="WordBoundary")
    except TypeError:
        comm = edge_tts.Communicate(text, VOICE, rate=RATE)
    words = []
    with open(mp3_path, "wb") as f:
        async for ch in comm.stream():
            if ch["type"] == "audio":
                f.write(ch["data"])
            elif ch["type"] == "WordBoundary":
                s = ch["offset"] / 1e7
                words.append([s, s + ch["duration"] / 1e7, ch["text"]])
    return words


def tts_silent(text, mp3_path):
    """Solo para pruebas sin internet: audio mudo con tiempos estimados."""
    toks = text.split() or ["…"]
    dur = max(1.5, len(toks) * 0.36)
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{dur:.2f}",
         "-c:a", "libmp3lame", "-b:a", "64k", str(mp3_path)])
    step = dur / len(toks)
    return [[i * step, (i + 1) * step, t] for i, t in enumerate(toks)]


def synth(text, mp3_path):
    if TTS_ENGINE == "silent":
        return tts_silent(text, mp3_path)
    last = None
    for attempt in range(4):
        try:
            words = asyncio.run(tts_edge(text, mp3_path))
            if mp3_path.exists() and mp3_path.stat().st_size > 1000:
                return words
        except Exception as e:  # noqa
            last = e
            util.log(f"[tts] intento {attempt + 1}: {e}")
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"La voz de Microsoft tampoco anduvo: {last}")


def align_words(text, words, dur):
    toks = text.split()
    if words and len(words) == len(toks):
        return [[w[0], w[1], t] for w, t in zip(words, toks)]
    if words:
        return words
    step = dur / max(1, len(toks))
    return [[i * step, (i + 1) * step, t] for i, t in enumerate(toks)]


def compactar(mp3_path, words, wav_path):
    """Saca los silencios de más que mete la voz y corre los tiempos de las palabras."""
    dur = duration(mp3_path)
    words = sorted([w for w in words if w[1] > w[0] or w[2]], key=lambda w: w[0])
    cortes = []
    if words:
        inicio = max(0.0, words[0][0] - 0.04)
        if inicio > 0.02:
            cortes.append((0.0, inicio))
        for a, b in zip(words, words[1:]):
            if b[0] - a[1] > MAX_PAUSA:
                cortes.append((a[1] + MAX_PAUSA / 2, b[0] - MAX_PAUSA / 2))
        fin = min(dur, words[-1][1] + COLA)
        if dur - fin > 0.02:
            cortes.append((fin, dur + 1))
    filtro = "aresample=44100"
    if cortes:
        expr = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in cortes)
        filtro += f",asetnsamples=n=64:p=0,aselect='not({expr})',asetpts=N/SR/TB"
    run(["ffmpeg", "-y", "-v", "error", "-i", str(mp3_path), "-af", filtro, "-ac", "1", "-c:a", "pcm_s16le",
         str(wav_path)])

    def corrido(t):
        return t - sum(min(b, t) - a for a, b in cortes if t > a)

    return [[corrido(w[0]), corrido(w[1]), w[2]] for w in words], duration(wav_path)
