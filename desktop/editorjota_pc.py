"""Editor Jota para computador (Windows). Abre o mesmo painel do celular em uma janela."""
import os, shutil, socket, sys, tempfile, threading, time, warnings

warnings.simplefilter("ignore", ResourceWarning)
PORTA = int(os.environ.get("EDITOR_PORTA", "8091"))

if False:  # noqa: SIM108 -- so pro empacotador (PyInstaller) incluir o que o editor usa
    import argparse, array, base64, glob, hashlib, io, json, math, mimetypes, random, re, runpy, struct  # noqa
    import subprocess, unicodedata, uuid, wave, webbrowser, urllib.parse, urllib.request  # noqa
    import http.server, socketserver, collections, datetime, statistics, zipfile, ctypes  # noqa
    import numpy, cv2  # noqa
    from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageEnhance, ImageFilter, ImageStat, ImageOps  # noqa


def curto(p):
    """caminho curto do Windows (sem espacos), pra nao quebrar os filtros do ffmpeg"""
    if os.name != "nt":
        return p
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.GetShortPathNameW(p, buf, 1024):
            return buf.value
    except Exception:  # noqa: BLE001
        pass
    return p


def pastas():
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        return dict(editor=os.path.join(base, "editor"), bin=os.path.join(base, "bin"))
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return dict(editor=os.path.join(raiz, "editor"), bin=os.path.join(raiz, "desktop", "bin"))


def preparar():
    P = pastas()
    local = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".local", "share")
    dados = os.path.join(local, "EditorJota")
    os.makedirs(dados, exist_ok=True)
    # o editor guarda perfis, fotos e posts na propria pasta: copia pra pasta do usuario
    # (so os arquivos do programa sao atualizados; o que voce criou fica)
    editor = os.path.join(dados, "editor")
    marca = os.path.join(editor, ".versao")
    origem = str(int(os.path.getmtime(os.path.join(P["editor"], "editar.py"))))
    if not os.path.exists(marca) or open(marca).read() != origem:
        shutil.copytree(P["editor"], editor, dirs_exist_ok=True)
        with open(marca, "w") as f:
            f.write(origem)
    tmp = os.path.join(dados, "tmp"); os.makedirs(tmp, exist_ok=True)
    voz = os.path.join(dados, "whisper"); os.makedirs(os.path.join(voz, "models"), exist_ok=True)
    for exe in ("whisper-cli.exe",):   # o editar.py procura o whisper na pasta dele
        o = os.path.join(P["bin"], exe)
        if os.path.exists(o) and not os.path.exists(os.path.join(voz, exe)):
            shutil.copy2(o, voz)
    for dll in os.listdir(P["bin"]) if os.path.isdir(P["bin"]) else []:
        if dll.lower().endswith(".dll") and ("whisper" in dll.lower() or "ggml" in dll.lower()):
            if not os.path.exists(os.path.join(voz, dll)):
                shutil.copy2(os.path.join(P["bin"], dll), voz)
    casa = os.path.expanduser("~")
    entrada = os.path.join(casa, "Downloads")
    saida = os.path.join(casa, "Videos", "Editor Jota")
    os.makedirs(entrada, exist_ok=True); os.makedirs(saida, exist_ok=True)
    tmp_c, bin_c = curto(tmp), curto(P["bin"])
    os.environ.update(EDITOR_JOTA_PC="1", EDITOR_DOWNLOAD=entrada, EDITOR_SAIDA=saida,
                      EDITOR_WHISPER_DIR=curto(voz), TMPDIR=tmp_c, TEMP=tmp_c, TMP=tmp_c,
                      PAINEL_VIDEOS=entrada, PAINEL_SAIDA=saida, PORTA=str(PORTA))
    os.environ["PATH"] = bin_c + os.pathsep + os.environ.get("PATH", "")
    tempfile.tempdir = tmp_c
    sys.path.insert(0, curto(editor))
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    return P


def porta_ocupada():
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORTA)) == 0


def ligar():
    preparar()
    import motor_pc
    motor_pc.instalar()
    sys.argv = ["painel.py", "--sem-abrir"]
    import painel
    painel.PORTA = PORTA
    threading.Thread(target=painel.main, daemon=True).start()
    for _ in range(150):
        if porta_ocupada():
            return True
        time.sleep(0.1)
    return False


def abrir_janela(url):
    """abre o editor como janela de app (Edge ou Chrome em modo aplicativo, sem barra de endereco)"""
    perfil = os.path.join(os.environ.get("LOCALAPPDATA", tempfile.gettempdir()), "EditorJota", "janela")
    cands = []
    for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""), os.environ.get("LOCALAPPDATA", "")):
        cands += [os.path.join(base, "Microsoft", "Edge", "Application", "msedge.exe"),
                  os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")]
    for exe in cands:
        if exe and os.path.exists(exe):
            import subprocess
            p = subprocess.Popen([exe, f"--app={url}", f"--user-data-dir={perfil}", "--window-size=1180,920",
                                  "--no-first-run", "--disable-features=Translate"])
            t0 = time.time()
            p.wait()
            if time.time() - t0 > 8:
                os._exit(0)
            return
    import webbrowser
    webbrowser.open(url)


def main():
    url = f"http://127.0.0.1:{PORTA}/"
    if not porta_ocupada() and not ligar():
        print("Nao consegui ligar o editor.")
        sys.exit(1)
    if "--sem-janela" in sys.argv:
        print("Editor Jota rodando em", url, flush=True)
        while True:
            time.sleep(3600)
    abrir_janela(url)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
