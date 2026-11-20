"""Gravador de tela do ClipJota PC.

Grava a tela inteira (ou uma janela) com o som do computador e salva em partes de 10 minutos
na pasta de videos do ClipJota. Depois acha os melhores momentos (ate 45s) em todas as partes.
"""
import glob
import os
import subprocess
import sys
import threading
import time

PARTE_SEG = 600          # cada arquivo tem 10 minutos
TAXA = 48000

_G = {"proc": None, "inicio": 0.0, "prefixo": "", "pasta": "", "audio": False, "erro": "", "parar": None,
      "thread": None, "aviso": ""}


def janelas():
    """titulos das janelas abertas (pra gravar so a janela da live)"""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    out = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(h, _):
        if u32.IsWindowVisible(h) and not u32.IsIconic(h):
            n = u32.GetWindowTextLengthW(h)
            if n:
                b = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(h, b, n + 1)
                t = b.value.strip()
                if t and t not in ("Program Manager",) and "ClipJota" not in t:
                    out.append(t)
        return True
    u32.EnumWindows(cb, 0)
    return sorted(set(out))[:40]


def _som_do_pc():
    """microfone 'loopback' = o que esta tocando no computador (WASAPI)"""
    try:
        import soundcard as sc
        alto = sc.default_speaker()
        return sc.get_microphone(alto.name, include_loopback=True)
    except Exception as e:
        _G["aviso"] = f"sem som do computador ({type(e).__name__}); gravando só a imagem"
        return None


def _manda_audio(mic, proc, parar):
    import numpy as np
    try:
        with mic.recorder(samplerate=TAXA, channels=2, blocksize=1024) as rec:
            while not parar.is_set() and proc.poll() is None:
                bloco = rec.record(numframes=TAXA // 10)            # 0,1 s
                proc.stdin.write(np.ascontiguousarray(bloco, dtype=np.float32).tobytes())
    except Exception as e:
        _G["erro"] = f"som parou: {e}"
    finally:
        try:
            proc.stdin.close()      # fim do audio -> o ffmpeg fecha o arquivo direitinho (-shortest)
        except Exception:
            pass


def iniciar(pasta, janela="", altura=1080, fps=30):
    if _G["proc"] and _G["proc"].poll() is None:
        return {"erro": "já está gravando"}
    os.makedirs(pasta, exist_ok=True)
    prefixo = "live_" + time.strftime("%d%m_%H%M")
    _G.update(prefixo=prefixo, pasta=pasta, erro="", aviso="", inicio=time.time())
    alvo = f"title={janela}" if janela else "desktop"
    mic = _som_do_pc()
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "gdigrab", "-framerate", str(fps), "-draw_mouse", "0", "-i", alvo]
    if mic is not None:
        cmd += ["-f", "f32le", "-ar", str(TAXA), "-ac", "2", "-i", "pipe:0"]
    filtro = "crop=trunc(iw/2)*2:trunc(ih/2)*2" + (",scale=-2:720" if altura == 720 else "") + ",format=yuv420p"
    cmd += ["-vf", filtro,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-g", str(fps * 2)]
    if mic is not None:
        cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += ["-f", "segment", "-segment_time", str(PARTE_SEG), "-reset_timestamps", "1",
            "-segment_format_options", "movflags=+frag_keyframe+empty_moov+default_base_moof",
            os.path.join(pasta, prefixo + "_parte%02d.mp4")]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _G["proc"] = proc
    _G["audio"] = mic is not None
    parar = threading.Event()
    _G["parar"] = parar
    if mic is not None:
        t = threading.Thread(target=_manda_audio, args=(mic, proc, parar), daemon=True)
        t.start(); _G["thread"] = t
    time.sleep(1.5)
    if proc.poll() is not None:
        err = (proc.stderr.read() or b"").decode("utf-8", "ignore")[-300:]
        _G["proc"] = None
        return {"erro": "não consegui gravar: " + (err or "ffmpeg fechou")}
    return estado()


def parar():
    p = _G["proc"]
    if not p:
        return estado()
    if _G["parar"]:
        _G["parar"].set()
    if not _G["audio"]:
        try:
            p.stdin.write(b"q"); p.stdin.flush()   # sem audio: 'q' fecha o ffmpeg
        except Exception:
            pass
    try:
        p.wait(timeout=15)
    except Exception:
        p.kill()
    _G["proc"] = None
    return estado()


def partes(prefixo=None):
    prefixo = prefixo or _G["prefixo"]
    if not prefixo:
        return []
    fs = sorted(glob.glob(os.path.join(_G["pasta"], prefixo + "_parte*.mp4")))
    return [{"nome": os.path.basename(f), "mb": round(os.path.getsize(f) / 1e6, 1)} for f in fs]


def estado():
    gravando = bool(_G["proc"] and _G["proc"].poll() is None)
    return {"gravando": gravando, "segundos": int(time.time() - _G["inicio"]) if gravando else 0,
            "partes": partes(), "audio": _G["audio"], "aviso": _G["aviso"], "erro": _G["erro"],
            "prefixo": _G["prefixo"]}


def analisar(sugerir, max_seg=45, por_parte=6):
    """melhores momentos de todas as partes da ultima gravacao (cada um com ate max_seg segundos)"""
    res = []
    for p in partes():
        caminho = os.path.join(_G["pasta"], p["nome"])
        for m in sugerir(caminho, float(max_seg), por_parte):
            m["video"] = p["nome"]
            res.append(m)
    res.sort(key=lambda m: -m["nota"])
    return res[:15]
