#!/usr/bin/env python3
"""PAINEL do editor (estilo CapCut) - abre no navegador do celular.

  python ~/editor_memes/painel.py
  depois abra  http://localhost:8080  no Chrome do celular
"""
import os, sys, re, json, glob, time, threading, subprocess, uuid, urllib.parse, mimetypes, shutil
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

PASTA = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PASTA)
import editar as E  # noqa: E402

VIDEOS = os.environ.get("PAINEL_VIDEOS", E.DOWNLOAD)
SAIDA = os.environ.get("PAINEL_SAIDA", E.SAIDA_PADRAO)
TMP = os.path.join(PASTA, ".painel_tmp")
os.makedirs(TMP, exist_ok=True)
PORTA = int(os.environ.get("PORTA", "8080"))
EXT = (".mp4", ".mov", ".webm", ".mkv", ".m4v", ".MP4", ".MOV")

# nome bonito de cada canal (todos que o editor conhece)
EXTRA = {"jotaexplica": "Jota Explica", "elisjusti": "Elis Justi", "memeverse": "MemeVerse"}
def canais():
    nomes = dict(E.NOMES_CANAL); nomes.update(EXTRA)
    ids = set(nomes) | {os.path.splitext(f)[0] for f in os.listdir(E.LOGOS) if not f.endswith("_wide.png")}
    out = []
    for c in sorted(ids, key=lambda x: nomes.get(x, x).lower().lstrip("@")):
        if c == "elisjusti":
            continue  # a Elis entra como logo extra no Jota Explica
        tipo = ("fofoca" if c in E.CANAIS_FOFOCA else "filme" if c in E.CANAIS_FILME
                else "meia tela" if c in E.HANDLES or c in ("cyberdefend", "silencio", "qgclipes") else "meme")
        out.append({"id": c, "nome": nomes.get(c, c), "tipo": tipo,
                    "logo": f"/logo?f={c}.png" if os.path.exists(os.path.join(E.LOGOS, c + ".png")) else ""})
    return out

def lista_videos():
    vs = [f for f in glob.glob(os.path.join(VIDEOS, "*")) if f.endswith(EXT)]
    vs.sort(key=os.path.getmtime, reverse=True)
    return [{"nome": os.path.basename(v), "mb": round(os.path.getsize(v) / 1e6, 1),
             "quando": time.strftime("%d/%m %H:%M", time.localtime(os.path.getmtime(v)))} for v in vs[:60]]

AUD_EXT = (".mp3", ".m4a", ".wav", ".aac", ".ogg", ".opus", ".flac", ".MP3", ".M4A")
MUSICAS = os.path.join(PASTA, "musicas")  # musicas enviadas pelo botao "Escolher do celular"
os.makedirs(MUSICAS, exist_ok=True)
def pastas_audio():
    sh = os.path.dirname(VIDEOS)
    return {"editor": MUSICAS, "download": VIDEOS, "music": os.path.join(sh, "Music"),
            "gravacoes": os.path.join(sh, "Recordings"),
            "whatsapp": os.path.join(sh, "Android/media/com.whatsapp/WhatsApp/Media/WhatsApp Audio")}

def lista_audios():
    out = []
    for chave, pasta in pastas_audio().items():
        if not os.path.isdir(pasta):
            continue
        for raiz, _, arqs in os.walk(pasta):
            if raiz.count(os.sep) - pasta.count(os.sep) > 2:
                continue
            for a in arqs:
                if a.endswith(AUD_EXT):
                    f = os.path.join(raiz, a)
                    out.append((os.path.getmtime(f), {"nome": os.path.relpath(f, pasta), "pasta": chave,
                                                      "mb": round(os.path.getsize(f) / 1e6, 1)}))
    out.sort(key=lambda x: x[0], reverse=True)
    return [x[1] for x in out[:150]]

def caminho_audio(nome, pasta):
    base = pastas_audio().get(pasta, VIDEOS)
    c = os.path.normpath(os.path.join(base, nome))
    return c if c.startswith(os.path.normpath(base)) else os.path.join(base, os.path.basename(nome))

# filtros da aba FILTROS (aplicados so no video, antes do template)
FILTROS = {
    "aprimorar": ("Aprimorar", "hqdn3d=1.5:1.2:4:3"),
    "nitidez": ("Qualidade 4K", "cas=0.6,unsharp=3:3:0.45:3:3:0"),
    "vivido": ("Vívido", "vibrance=intensity=0.12,eq=contrast=1.07:saturation=1.03"),
    "brilho": ("Mais brilho", "eq=brightness=0.05:gamma=1.06"),
    "contraste": ("Mais contraste", "eq=contrast=1.18"),
    "quente": ("Quente", "colorbalance=rs=0.06:gs=0.02:bs=-0.06:rm=0.04:bm=-0.04"),
    "frio": ("Frio", "colorbalance=rs=-0.05:bs=0.07:bm=0.04"),
    "cinema": ("Cinema", "colorbalance=rs=-0.04:bs=0.06:rh=0.06:bh=-0.04,eq=contrast=1.08:saturation=0.92"),
    "pb": ("Preto e branco", "hue=s=0,eq=contrast=1.12"),
    "vintage": ("Vintage", "curves=preset=vintage"),
    "vinheta": ("Vinheta", "vignette=PI/4.5"),
    "granulado": ("Granulado", "noise=alls=9:allf=t"),
}

POSTS = os.path.join(PASTA, "postagens.json")   # legenda de postagem de cada video pronto

def ler_posts():
    try:
        with open(POSTS, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def guardar_post(arquivo, texto):
    if not texto:
        return
    d = ler_posts()
    d[os.path.basename(arquivo)] = texto
    if len(d) > 200:   # guarda so os mais recentes
        d = dict(list(d.items())[-200:])
    tmp = POSTS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, POSTS)

def lista_saida():
    vs = [f for f in glob.glob(os.path.join(SAIDA, "*.mp4"))]
    vs.sort(key=os.path.getmtime, reverse=True)
    return [os.path.basename(v) for v in vs[:30]]

def duracao(caminho):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", caminho],
                           capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return 0.0

# ------------------------------------------------------------------ renderizacoes
JOBS = {}

def montar_args(p, saida, previa=False, video=None):
    v = video or os.path.join(VIDEOS, os.path.basename(p["video"]))
    if not os.path.exists(v):
        raise ValueError("Video nao encontrado: " + p["video"])
    canal = p["canal"]
    fofoca = canal in E.CANAIS_FOFOCA and p.get("modelo") in (None, "", "fofoca")
    args = [sys.executable, "-u", os.path.join(PASTA, "editar.py"), v, canal, p.get("headline", "")]
    if p.get("modelo"):
        args += ["--modelo", p["modelo"]]
    ini, fim = (0, 0) if video else (float(p.get("inicio") or 0), float(p.get("fim") or 0))
    if ini > 0:
        args += ["--inicio", f"{ini:.2f}"]
    if fim > 0:
        args += ["--fim", f"{fim:.2f}"]
    for c in p.get("cards", []):
        if c.get("texto"):
            args += ["--card", f'{c["texto"]}@{float(c["t0"]):.1f}-{float(c["t1"]):.1f}']
    for f in p.get("fotos", []):
        if f.get("nome"):
            args += ["--foto", f'{f["nome"]}@{float(f["t0"]):.1f}-{float(f["t1"]):.1f}']
    txt = {"fonte": "--fonte", "rodape": "--rodape", "selo": "--selo", "parte": "--parte", "logo_extra": "--logo-extra"}
    for k, flag in txt.items():
        if p.get(k):
            args += [flag, str(p[k])]
    if p.get("legenda_cor"):
        args += ["--legenda-cor", str(p["legenda_cor"]).lstrip("#")]
    if p.get("legenda") is False:
        args += ["--sem-legenda"]
    elif p.get("legenda") and not fofoca:
        args += ["--legenda"]
    args += ["--sem-aprimorar"]  # os filtros agora vem da aba FILTROS
    if p.get("velocidade_fixa"):
        args += ["--velocidade", "1.0"]
    if p.get("sem_unico"):
        args += ["--sem-unico"]
    if p.get("espelhar"):
        args += ["--espelhar"]
    if p.get("fade"):
        args += ["--fade"]
    corte_t, corte_b = int(p.get("cortar_topo") or 0), int(p.get("cortar_baixo") or 0)
    if corte_t or corte_b or p.get("sem_corte_auto"):
        args += ["--sem-corte-auto"]
    if corte_t:
        args += ["--cortar-topo", str(corte_t)]
    if corte_b:
        args += ["--cortar-baixo", str(corte_b)]
    if p.get("enquadrar") not in (None, ""):
        args += ["--enquadrar", str(p["enquadrar"])]
    if previa:
        args += ["--previa"]
    args += ["--saida", saida]
    return args

def _stream(j, args, dur, base, peso):
    """roda um processo e atualiza progresso de base ate base+peso"""
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=PASTA)
    j["proc"] = proc
    buf = b""
    while True:
        ch = proc.stdout.read(256)
        if not ch:
            break
        buf += ch
        partes = re.split(rb"[\r\n]", buf)
        buf = partes[-1]
        for ln in partes[:-1]:
            s = ln.decode("utf-8", "replace").strip()
            if not s:
                continue
            m = re.search(r"time=(\d+):(\d+):([\d.]+)", s)
            if m and dur > 0:
                t = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
                j["progresso"] = max(j["progresso"], min(99, base + int(min(1, t / dur) * peso)))
                continue
            if s.startswith(("frame=", "size=")):
                continue
            j["log"].append(s)
            j["log"] = j["log"][-40:]
            if "Renderizando" in s:
                j["etapa"] = "Renderizando"
            elif "Legenda" in s or "Transcrevendo" in s:
                j["etapa"] = "Legenda"
            elif "Cortando" in s:
                j["etapa"] = "Cortando o trecho"
    proc.wait()
    return proc.returncode

def tem_audio(c):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                        "-of", "csv=p=0", c], capture_output=True, text=True)
    return bool(r.stdout.strip())

def executar(jid):
    j = JOBS[jid]; p = j["p"]; previa = j["previa"]
    j["status"], j["etapa"] = "rodando", "Preparando"
    try:
        src = os.path.join(VIDEOS, os.path.basename(p["video"]))
        ini, fim = float(p.get("inicio") or 0), float(p.get("fim") or 0)
        total = duracao(src)
        fim = fim if fim > ini else total
        if previa:
            fim = min(fim, ini + 8)
        dur = max(0.5, fim - ini)
        filtros = [FILTROS[f][1] for f in FILTROS if f in (p.get("filtros") or [])]
        video = None
        base = 0
        # 1) filtros + corte do trecho
        if filtros:
            j["etapa"] = "Aplicando filtros"
            video = os.path.join(TMP, f"pre_{jid}.mp4")
            cmd = ["ffmpeg", "-v", "error", "-stats", "-y", "-ss", f"{ini:.2f}", "-i", src, "-t", f"{dur:.2f}",
                   "-vf", ",".join(filtros) + ",format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
                   "-crf", "16", "-c:a", "aac", "-b:a", "192k", video]
            if _stream(j, cmd, dur, 0, 30) != 0 or j["status"] == "erro":
                raise RuntimeError("falhou nos filtros")
            base = 30
        elif previa:
            video = None
        # 2) editor (template, cards, legenda...)
        musica = p.get("musica") or {}
        com_musica = bool(musica.get("nome")) and not previa
        saida_ed = os.path.join(TMP, f"ed_{jid}.mp4") if com_musica else (
            j["arquivo"] if not previa else os.path.join(TMP, f"p_{jid}.mp4"))
        args = montar_args(p, saida_ed, previa, video)
        j["etapa"] = "Montando o vídeo"
        rc = _stream(j, args, dur, base, (60 if com_musica else 100) - base)
        if rc != 0 or j["status"] == "erro":
            raise RuntimeError("falhou no editor")
        # 3) musica
        if com_musica:
            j["etapa"] = "Colocando a música"
            mus = caminho_audio(musica["nome"], musica.get("pasta"))
            d2 = duracao(saida_ed)
            vm = float(musica.get("vol", 35)) / 100; vo = float(musica.get("vol_orig", 100)) / 100
            m0 = float(musica.get("inicio") or 0)
            fm = (f"[1:a]aresample=48000,volume={vm:.2f},afade=t=in:d=0.6,"
                  f"afade=t=out:st={max(0, d2 - 1.5):.2f}:d=1.5[m];")
            if tem_audio(saida_ed) and vo > 0:
                fo = f"[0:a]aresample=48000,volume={vo:.2f},asplit[o][sc];"
                if musica.get("abaixar", True):
                    fm += "[m][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=350[md];"
                    mix = "[o][md]amix=inputs=2:duration=first:normalize=0"
                else:
                    fo = f"[0:a]aresample=48000,volume={vo:.2f}[o];"
                    mix = "[o][m]amix=inputs=2:duration=first:normalize=0"
                fc = fo + fm + mix + ",alimiter=limit=0.95,loudnorm=I=-14:TP=-1.5[a]"
            else:
                fc = fm + "[m]atrim=0:" + f"{d2:.2f}" + ",loudnorm=I=-14:TP=-1.5[a]"
            cmd = ["ffmpeg", "-v", "error", "-stats", "-y", "-i", saida_ed, "-ss", f"{m0:.2f}", "-stream_loop", "-1",
                   "-i", mus, "-filter_complex", fc, "-map", "0:v", "-map", "[a]", "-c:v", "copy",
                   "-c:a", "aac", "-b:a", "192k", "-t", f"{d2:.2f}", "-movflags", "+faststart", j["arquivo"]]
            if _stream(j, cmd, d2, 60, 39) != 0:
                raise RuntimeError("falhou na musica")
        if os.path.exists(j["arquivo"]):
            if not previa:
                j["etapa"] = "Conferindo qualidade"
                qc = conferir(j["arquivo"])
                if qc.get("lufs") is not None and not (-17 <= qc["lufs"] <= -11) and tem_audio(j["arquivo"]):
                    j["etapa"] = "Ajustando o volume"
                    tmpv = j["arquivo"] + ".tmp.mp4"
                    r = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", j["arquivo"], "-c:v", "copy",
                                        "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac",
                                        "-b:a", "192k", "-movflags", "+faststart", tmpv], capture_output=True)
                    if r.returncode == 0:
                        os.replace(tmpv, j["arquivo"])
                        qc = conferir(j["arquivo"]); qc["corrigido"] = True
                j["qc"] = qc
            j["status"], j["progresso"], j["etapa"] = "pronto", 100, "Pronto"
            if not previa and shutil.which("termux-media-scan"):
                subprocess.run(["termux-media-scan", j["arquivo"]], capture_output=True)
        else:
            raise RuntimeError("arquivo nao foi criado")
    except Exception as e:  # noqa: BLE001
        if j["status"] != "cancelado":
            j["status"] = "erro"
        j["log"].append(str(e))
    finally:
        for f in glob.glob(os.path.join(TMP, f"pre_{jid}.mp4")) + glob.glob(os.path.join(TMP, f"ed_{jid}.mp4")):
            try: os.remove(f)
            except OSError: pass

def conferir(arq):
    """controle de qualidade (skill viral-cuts-studio): duracao, volume, tela preta"""
    qc = {"dur": round(duracao(arq), 1)}
    try:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-i", arq, "-vf", "blackdetect=d=0.4:pix_th=0.08",
                            "-af", "ebur128", "-f", "null", "-"], capture_output=True, text=True, timeout=240)
        m = re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)
        qc["lufs"] = float(m[-1]) if m else None
        qc["preto"] = len(re.findall(r"black_start", r.stderr))
    except Exception:  # noqa: BLE001
        pass
    avisos = []
    if qc.get("lufs") is not None and not (-17 <= qc["lufs"] <= -11):
        avisos.append("volume fora do padrão (" + str(qc["lufs"]) + " LUFS)")
    if qc.get("preto"):
        avisos.append(f'{qc["preto"]} trecho(s) de tela preta')
    if qc["dur"] and qc["dur"] < 5:
        avisos.append("vídeo muito curto")
    qc["ok"] = not avisos
    qc["avisos"] = avisos
    return qc

def sugerir(video, janela=30.0, n=4):
    """acha os trechos com mais energia (fala forte, risada, acao) - pra achar o gancho"""
    import numpy as np
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-vn", "-ac", "1", "-ar", "4000", "-f", "s16le", "-"],
                       capture_output=True, timeout=600)
    x = np.frombuffer(r.stdout, np.int16).astype(np.float32) / 32768
    if len(x) < 4000 * 5:
        return []
    seg = np.sqrt(np.mean(x[: len(x) // 4000 * 4000].reshape(-1, 4000) ** 2, axis=1))
    var = np.abs(np.diff(seg, prepend=seg[0]))
    score = seg / (seg.mean() + 1e-6) + 1.5 * var / (var.mean() + 1e-6)
    w = int(max(5, min(janela, len(seg) - 1)))
    sc = np.convolve(score, np.ones(w), "valid") / w
    out, usados = [], []
    for i in np.argsort(-sc):
        if all(abs(i - u) >= w for u in usados):
            usados.append(int(i))
            pico = int(i + np.argmax(score[i:i + w]))
            out.append({"inicio": float(i), "fim": float(i + w), "pico": float(pico),
                        "nota": int(min(99, 50 + 20 * (sc[i] - sc.mean()) / (sc.std() + 1e-6)))})
        if len(out) >= n:
            break
    return sorted(out, key=lambda o: -o["nota"])

FILA = []
FILA_LOCK = threading.Lock()
def trabalhador():
    while True:
        jid = None
        with FILA_LOCK:
            for x in FILA:
                if JOBS.get(x, {}).get("status") == "na fila":
                    jid = x; break
        if jid:
            executar(jid)
        else:
            time.sleep(0.8)

def novo_job(p, previa=False):
    jid = uuid.uuid4().hex[:8]
    if previa:
        arquivo = os.path.join(TMP, f"p_{jid}_previa.jpg")
        nome = "prévia"
    else:
        os.makedirs(SAIDA, exist_ok=True)
        nome = re.sub(r"[^a-zA-Z0-9_]+", "_", (p.get("nome_saida") or "").strip())[:40]
        nome = nome or f'{p["canal"]}_{time.strftime("%d%m_%H%M%S")}_{jid[:3]}'
        arquivo = os.path.join(SAIDA, nome + ".mp4")
    montar_args(p, "x.mp4")  # valida (video existe etc.)
    if not previa:
        guardar_post(arquivo, (p.get("post_legenda") or "").strip())
    JOBS[jid] = {"status": "na fila", "progresso": 0, "etapa": "Na fila", "log": [], "arquivo": arquivo,
                 "previa": previa, "p": p, "nome": nome, "headline": (p.get("headline") or "")[:70],
                 "canal": p.get("canal"), "criado": time.time()}
    if previa:
        threading.Thread(target=executar, args=(jid,), daemon=True).start()
    else:
        with FILA_LOCK:
            FILA.append(jid)
    return jid

def info_job(jid):
    j = JOBS[jid]
    d = {k: v for k, v in j.items() if k not in ("proc", "p")}
    d["id"] = jid
    d["url"] = ("/tmp?f=" if j["previa"] else "/saida?f=") + urllib.parse.quote(os.path.basename(j["arquivo"]))
    return d

def comando_termux(args):
    """mesma edicao em forma de comando, pra copiar e usar no Termux"""
    def q(x):
        return x if re.fullmatch(r"[\w./@:-]+", x) else '"' + x.replace('"', '\\"').replace("$", "\\$") + '"'
    a = list(args[3:])
    a[0] = a[0].replace(os.path.expanduser("~"), "~")
    a[0] = a[0] if " " not in a[0] else q(a[0])
    if "--saida" in a:
        i = a.index("--saida"); del a[i:i + 2]
    if "--previa" in a:
        a.remove("--previa")
    return "python ~/editor_memes/editar.py " + " ".join([a[0]] + [q(x) for x in a[1:]])

# ------------------------------------------------------------------ servidor
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers(); self.wfile.write(b)

    def _arquivo(self, caminho, baixar=False):
        if not os.path.isfile(caminho):
            self.send_error(404); return
        tam = os.path.getsize(caminho)
        tipo = mimetypes.guess_type(caminho)[0] or "application/octet-stream"
        rng = self.headers.get("Range")
        ini, fim = 0, tam - 1
        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)", rng)
            if m:
                if m.group(1):
                    ini = int(m.group(1))
                    fim = int(m.group(2)) if m.group(2) else tam - 1
                elif m.group(2):
                    ini = tam - int(m.group(2))
            fim = min(fim, tam - 1)
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {ini}-{fim}/{tam}")
        else:
            self.send_response(200)
        self.send_header("Content-Type", tipo)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(fim - ini + 1))
        self.send_header("Cache-Control", "no-cache")
        if baixar:
            self.send_header("Content-Disposition",
                             "attachment; filename*=UTF-8''" + urllib.parse.quote(os.path.basename(caminho)))
        self.end_headers()
        try:
            with open(caminho, "rb") as f:
                f.seek(ini); falta = fim - ini + 1
                while falta > 0:
                    pedaco = f.read(min(1 << 20, falta))
                    if not pedaco:
                        break
                    self.wfile.write(pedaco); falta -= len(pedaco)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        nome = os.path.basename(q.get("f", ""))
        if u.path == "/":
            b = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers(); self.wfile.write(b)
        elif u.path == "/api/tudo":
            fotos = sorted(os.path.splitext(f)[0] for f in os.listdir(os.path.join(PASTA, "fotos"))) \
                if os.path.isdir(os.path.join(PASTA, "fotos")) else []
            self._json({"videos": lista_videos(), "canais": canais(), "fotos": fotos, "audios": lista_audios(),
                        "filtros": [{"id": k, "nome": v[0]} for k, v in FILTROS.items()],
                        "prontos": lista_saida(), "pasta": VIDEOS,
                        "saida_real": os.path.realpath(SAIDA), "posts": ler_posts()})
        elif u.path == "/api/job":
            if q.get("id", "") not in JOBS:
                return self._json({"status": "erro", "log": ["job nao existe"]}, 404)
            self._json(info_job(q["id"]))
        elif u.path == "/api/sugerir":
            try:
                self._json(sugerir(os.path.join(VIDEOS, nome), float(q.get("dur", 30))))
            except Exception as e:  # noqa: BLE001
                self._json({"erro": str(e)}, 400)
        elif u.path == "/api/fila":
            with FILA_LOCK:
                self._json([info_job(x) for x in FILA if x in JOBS])
        elif u.path == "/audio":
            self._arquivo(caminho_audio(q.get("f", ""), q.get("p", "")))
        elif u.path == "/video":
            self._arquivo(os.path.join(VIDEOS, nome))
        elif u.path == "/saida":
            self._arquivo(os.path.join(SAIDA, nome), baixar=q.get("baixar") == "1")
        elif u.path == "/tmp":
            self._arquivo(os.path.join(TMP, nome))
        elif u.path == "/logo":
            self._arquivo(os.path.join(E.LOGOS, nome))
        elif u.path == "/foto":
            self._arquivo(os.path.join(PASTA, "fotos", nome + ".jpg"))
        else:
            self.send_error(404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/upload":  # recebe a musica escolhida no celular
            q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
            nome = re.sub(r'[\\/:*?"<>|]+', "_", os.path.basename(q.get("nome", "musica.mp3")))
            tam = int(self.headers.get("Content-Length", 0))
            with open(os.path.join(MUSICAS, nome), "wb") as f:
                while tam > 0:
                    b = self.rfile.read(min(1 << 20, tam))
                    if not b:
                        break
                    f.write(b); tam -= len(b)
            return self._json({"nome": nome, "pasta": "editor"})
        try:
            p = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if u.path == "/api/render":
                return self._json({"id": novo_job(p)})
            if u.path == "/api/previa":
                return self._json({"id": novo_job(p, previa=True)})
            if u.path == "/api/parar":
                j = JOBS.get(p.get("id", ""))
                if j:
                    if j["status"] == "rodando" and j.get("proc"):
                        j["status"] = "cancelado"; j["proc"].kill()
                    elif j["status"] == "na fila":
                        j["status"] = "cancelado"
                    j["log"].append("Cancelado")
                return self._json({"ok": True})
            if u.path == "/api/remover":
                with FILA_LOCK:
                    if p.get("id") in FILA and JOBS[p["id"]]["status"] != "rodando":
                        FILA.remove(p["id"])
                    if p.get("limpar"):
                        for x in list(FILA):
                            if JOBS[x]["status"] in ("pronto", "erro", "cancelado"):
                                FILA.remove(x)
                return self._json({"ok": True})
            if u.path == "/api/comando":
                return self._json({"cmd": comando_termux(montar_args(p, "x.mp4"))})
        except Exception as e:  # noqa: BLE001
            return self._json({"erro": str(e)}, 400)
        self.send_error(404)


HTML = r"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<title>Editor Jota</title>
<style>
:root{--bg:#0d0d10;--p:#17171c;--p2:#22222a;--t:#f2f2f5;--m:#8b8b96;--a:#ffc400;--ok:#2ecc71;--er:#ff4d4d}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--t);font:15px/1.35 system-ui,-apple-system,Roboto,sans-serif;padding-bottom:96px}
header{position:sticky;top:0;z-index:5;background:var(--bg);display:flex;align-items:center;gap:10px;padding:12px 14px;border-bottom:1px solid #222}
header b{font-size:18px}header span{color:var(--m);font-size:12px;margin-left:auto}
.wrap{max-width:560px;margin:0 auto;padding:10px 12px}
.card{background:var(--p);border-radius:14px;padding:12px;margin:10px 0}
h3{margin:0 0 10px;font-size:13px;color:var(--m);text-transform:uppercase;letter-spacing:.06em}
video{width:100%;max-height:44vh;background:#000;border-radius:10px;display:block}
.row{display:flex;gap:8px;align-items:center}.row>*{flex:1}
button{border:0;border-radius:10px;padding:11px 10px;background:var(--p2);color:var(--t);font-size:14px;font-weight:600}
button.pri{background:var(--a);color:#111}button.sm{padding:7px 9px;font-size:13px;flex:0 0 auto}
button:active{transform:scale(.97)}
input,select,textarea{width:100%;background:var(--p2);color:var(--t);border:1px solid #2c2c36;border-radius:10px;padding:10px;font-size:15px}
textarea{min-height:64px;resize:vertical;font-family:inherit}
label{display:block;font-size:12px;color:var(--m);margin:8px 0 4px}
.chips{display:flex;gap:8px;overflow-x:auto;padding-bottom:4px;scrollbar-width:none}
.chip{flex:0 0 auto;display:flex;flex-direction:column;align-items:center;gap:4px;width:74px;padding:6px 2px;border-radius:12px;background:var(--p2);border:2px solid transparent;font-size:11px;text-align:center}
.chip img{width:46px;height:46px;border-radius:50%;object-fit:cover;background:#333}
.chip.on{border-color:var(--a)}.chip small{color:var(--m);font-size:10px}
.vids{max-height:220px;overflow:auto}
.vid{display:flex;justify-content:space-between;padding:9px 8px;border-radius:8px;font-size:14px}.vid.on{background:#2b2610;color:var(--a)}
.vid small{color:var(--m)}
.tl{position:relative;height:46px;background:#000;border-radius:8px;margin:10px 0 4px;overflow:hidden;touch-action:none}
.tl .sel{position:absolute;top:0;bottom:0;background:rgba(255,196,0,.22);border-left:3px solid var(--a);border-right:3px solid var(--a)}
.tl .cab{position:absolute;top:0;bottom:0;width:2px;background:#fff}
.tl .mk{position:absolute;top:30px;height:10px;border-radius:3px}
.tl .mk.c{background:#2ecc71}.tl .mk.f{background:#4da3ff}
.tempo{display:flex;justify-content:space-between;font-size:12px;color:var(--m)}
.it{display:flex;gap:6px;align-items:center;margin:6px 0}.it input{padding:8px}.it .n{flex:0 0 64px}
.tog{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #24242c}
.tog:last-child{border:0}.tog small{display:block;color:var(--m);font-size:11px}
.sw{position:relative;width:46px;height:26px;flex:0 0 auto}.sw input{display:none}
.sw i{position:absolute;inset:0;background:#3a3a44;border-radius:20px;transition:.2s}
.sw i:after{content:"";position:absolute;width:20px;height:20px;left:3px;top:3px;background:#fff;border-radius:50%;transition:.2s}
.sw input:checked+i{background:var(--a)}.sw input:checked+i:after{left:23px}
.bar{position:fixed;left:0;right:0;bottom:0;background:rgba(13,13,16,.96);border-top:1px solid #222;padding:10px 12px;display:flex;gap:8px;z-index:9}
.bar button{flex:1;padding:14px}
.prog{height:8px;background:#2a2a33;border-radius:8px;overflow:hidden;margin:8px 0}.prog i{display:block;height:100%;background:var(--a);width:0;transition:width .4s}
pre{white-space:pre-wrap;font-size:11px;color:var(--m);max-height:120px;overflow:auto;margin:6px 0 0}
.hide{display:none}.hint{font-size:12px;color:var(--m);margin-top:6px}
.fotos{display:flex;gap:6px;overflow-x:auto}.fotos img{width:54px;height:80px;object-fit:cover;border-radius:8px;border:2px solid transparent}.fotos img.on{border-color:var(--a)}
.prontos a{display:block;color:var(--t);padding:8px;border-radius:8px;background:var(--p2);margin:5px 0;text-decoration:none;font-size:13px}
.pronto{background:var(--p2);border-radius:10px;padding:8px;margin:6px 0}.pronto a{background:none;margin:0;padding:2px 0}
.redes{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}.redes button{flex:1;min-width:70px;padding:8px 6px;font-size:13px;border-radius:8px}
details summary{cursor:pointer;color:var(--m);font-size:13px;padding:4px 0}
#toast{position:fixed;left:50%;bottom:90px;transform:translateX(-50%);background:#333;padding:10px 16px;border-radius:20px;font-size:14px;opacity:0;transition:.3s;z-index:20}

.tabs{position:sticky;top:49px;z-index:6;background:var(--bg);display:flex;gap:4px;padding:6px 8px;border-bottom:1px solid #222;overflow-x:auto}
.tabs button{flex:1 0 auto;padding:9px 10px;font-size:13px;background:transparent;color:var(--m)}
.tabs button.on{background:var(--p2);color:var(--a)}
.tabs .badge{background:var(--a);color:#111;border-radius:10px;padding:0 6px;margin-left:4px;font-size:11px}
.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:8px}
.fb{padding:12px 6px;border-radius:12px;background:var(--p2);text-align:center;font-size:13px;border:2px solid transparent}
.fb.on{border-color:var(--a);color:var(--a)}
.aud{display:flex;justify-content:space-between;padding:9px 8px;border-radius:8px;font-size:14px}.aud.on{background:#2b2610;color:var(--a)}
.aud small{color:var(--m)}
input[type=range]{padding:0;accent-color:var(--a)}
.fj{background:var(--p2);border-radius:12px;padding:10px;margin:8px 0}
.fj .t{display:flex;justify-content:space-between;gap:8px;font-size:13px}.fj .t b{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.st{font-size:11px;padding:2px 8px;border-radius:10px;background:#333;white-space:nowrap}
.st.pronto{background:#1f5f35}.st.erro,.st.cancelado{background:#6b1f1f}.st.rodando{background:#6b5300}
video.esp{transform:scaleX(-1)}
</style></head><body>
<header><b>🎬 Editor Jota</b><span id="pasta"></span></header>
<div class="tabs">
 <button class="on" data-t="editar" onclick="aba('editar')">✂️ Editar</button>
 <button data-t="filtros" onclick="aba('filtros')">🎨 Filtros<span class="badge hide" id="bF"></span></button>
 <button data-t="audio" onclick="aba('audio')">🎵 Áudio<span class="badge hide" id="bA">1</span></button>
 <button data-t="espelhar" onclick="aba('espelhar')">🪞 Espelhar<span class="badge hide" id="bE">ON</span></button>
 <button data-t="fila" onclick="aba('fila')">📋 Fila<span class="badge hide" id="bQ"></span></button>
</div>
<div class="wrap">

<!-- ================= EDITAR ================= -->
<section data-s="editar">
<div class="card"><h3>1 · Vídeo</h3>
 <div class="vids" id="vids"></div>
 <div class="row" style="margin-top:8px"><button class="sm" onclick="carregar()">↻ Atualizar lista</button></div>
</div>
<div class="card"><h3>2 · Trecho</h3>
 <video id="v" controls playsinline preload="metadata"></video>
 <div class="tl" id="tl"><div class="sel" id="sel"></div><div class="cab" id="cab"></div></div>
 <div class="tempo"><span id="tIni">início 0:00</span><span id="tDur"></span><span id="tFim">fim —</span></div>
 <div class="row" style="margin-top:8px"><button onclick="marcar('inicio')">⟦ Início aqui</button><button onclick="marcar('fim')">Fim aqui ⟧</button></div>
 <div class="row" style="margin-top:8px">
  <div><label>Início (seg ou 1:23)</label><input id="inicio" placeholder="0" oninput="desenhar()"></div>
  <div><label>Fim</label><input id="fim" placeholder="até o final" oninput="desenhar()"></div></div>
 <div class="row" style="margin-top:8px"><button class="sm" onclick="tocarTrecho()">▶ Ver trecho</button><button class="sm" onclick="limparTrecho()">Vídeo inteiro</button></div>
 <div class="row" style="margin-top:10px"><button class="pri" onclick="sugerirG()">⭐ Achar os momentos fortes</button>
 <select id="durSug" style="flex:0 0 92px"><option value="15">15s</option><option value="20">20s</option><option value="30" selected>30s</option><option value="45">45s</option></select></div>
 <div id="sug"></div>
</div>
<div class="card"><h3>3 · Canal</h3><div class="chips" id="canais"></div><div class="hint" id="tipoCanal"></div></div>
<div class="card"><h3>4 · Textos</h3>
 <label>Headline — <b>*palavra*</b> fica colorida · <b>|</b> pula linha</label>
 <textarea id="headline" placeholder="ELE ACHOU QUE TINHA VENCIDO… | ATÉ *ISSO* ACONTECER 💀"></textarea>
 <div id="boxFonte"><label>Fonte (embaixo do vídeo)</label><input id="fonte" placeholder="vídeo do YouTube / podcast…"></div>
 <div id="boxRodape"><label>Rodapé</label><input id="rodape" placeholder="Segue a Jota TV pra mais 🔥"></div>
 <div id="boxParte"><label>Parte (série)</label><input id="parte" placeholder="ex: 3"></div>
 <div id="boxSelo"><label>Selo (padrão do canal)</label><input id="selo" placeholder="FOFOCA / CARROS / HISTÓRIA…"></div>
</div>
<div class="card" id="boxCards"><h3>5 · Cards</h3><div id="cards"></div>
 <button class="sm" onclick="addCard()">＋ Card no tempo atual</button>
 <div class="hint">O tempo do card conta a partir do início do trecho.</div></div>
<div class="card" id="boxFotos"><h3>6 · Foto</h3><div class="fotos" id="fotos"></div>
 <div class="it"><input class="n" id="fotoT0" value="0.3"><span>até</span><input class="n" id="fotoT1" value="3.5"><button class="sm" onclick="tirarFoto()">Sem foto</button></div>
 <label>Logo extra (campanha)</label>
 <select id="logo_extra"><option value="">Nenhum</option><option value="elisjusti">Elis Justi</option></select></div>
<div class="card"><h3>7 · Ajustes</h3>
 <div class="tog"><div>Legenda automática<small>Salto de Cor pelo whisper</small></div><label class="sw"><input type="checkbox" id="legenda" checked><i></i></label></div>
 <div id="boxCor"><label>Cor da palavra falada na legenda</label><div class="chips" id="cores"></div></div>
 <div class="tog"><div>Velocidade original<small>não acelera a voz (campanhas)</small></div><label class="sw"><input type="checkbox" id="velocidade_fixa"><i></i></label></div>
 <div class="tog"><div>Fade no final</div><label class="sw"><input type="checkbox" id="fade"><i></i></label></div>
 <div class="tog"><div>Desligar anti-duplicidade</div><label class="sw"><input type="checkbox" id="sem_unico"><i></i></label></div>
 <details><summary>Avançado</summary>
  <div class="row"><div><label>Cortar topo (px)</label><input id="cortar_topo" inputmode="numeric" placeholder="0"></div>
  <div><label>Cortar baixo (px)</label><input id="cortar_baixo" inputmode="numeric" placeholder="0"></div></div>
  <div class="row"><div><label>Enquadrar (0 topo · 0.5 meio)</label><input id="enquadrar" placeholder="auto"></div>
  <div><label>Modelo</label><select id="modelo"><option value="">Padrão do canal</option><option>fofoca</option><option>filme</option><option>meiatela</option><option>padrao</option></select></div></div>
  <label>Nome do arquivo final</label><input id="nome_saida" placeholder="automático">
 </details></div>
<div class="card"><h3>8 · Campanha e postagem</h3>
 <select id="campanha"><option value="">Sem campanha</option><option value="elis">Elis Justi</option><option value="ciate">GBCiate</option><option value="cacheta">Cacheta League</option></select>
 <div id="regras" class="hint"></div>
 <label>Legenda pra postar</label><textarea id="post" style="min-height:110px"></textarea>
 <button class="sm" onclick="navigator.clipboard.writeText($('post').value).then(()=>toast('Legenda copiada'))">📋 Copiar legenda</button>
</div>
<div class="card hide" id="boxPrevia"><h3 id="pvTit">Prévia</h3><div class="prog"><i id="pvPg"></i></div>
 <img id="imgPrevia" class="hide" style="width:100%;border-radius:10px"><pre id="pvLog"></pre></div>
<div class="card"><h3>Comando do Termux</h3><pre id="cmd" style="color:#ddd">—</pre>
 <button class="sm" onclick="copiarCmd()">📋 Copiar comando</button>
 <div class="hint">Filtros e música só funcionam pelo painel.</div></div>
</section>

<!-- ================= FILTROS ================= -->
<section data-s="filtros" class="hide">
<div class="card"><h3>Filtros do vídeo</h3>
 <div class="grid" id="gFiltros"></div>
 <div class="hint">Toque pra ligar/desligar. Vale só pro vídeo — o template não muda. Use 👁 Prévia pra ver antes.</div>
 <div class="row" style="margin-top:10px"><button class="sm" onclick="presetF(['aprimorar','nitidez','vivido'])">⭐ Padrão Jota</button>
 <button class="sm" onclick="presetF(['aprimorar','nitidez','cinema','vinheta'])">🎬 Filme</button>
 <button class="sm" onclick="presetF([])">Nenhum</button></div>
</div></section>

<!-- ================= AUDIO ================= -->
<section data-s="audio" class="hide">
<div class="card"><h3>Música de fundo</h3>
 <input type="file" id="upAud" accept="audio/*,.mp3,.m4a,.wav,.aac,.ogg,.opus" class="hide" onchange="enviarAudio(this)">
 <button class="pri" style="width:100%;margin-bottom:10px" onclick="$('upAud').click()">📂 Escolher música do celular</button>
 <div class="prog hide" id="upPg"><i></i></div>
 <label>Ou escolha uma da lista</label>
 <div class="vids" id="auds"></div>
 <div class="row" style="margin-top:8px"><button class="sm" onclick="carregar()">↻ Atualizar</button><button class="sm" onclick="semMusica()">Sem música</button></div>
 <div class="hint">A lista mostra músicas da Download, Music, Gravações, WhatsApp e as que você já escolheu.</div>
</div>
<div class="card" id="boxMus"><h3 id="musNome">Nenhuma música</h3>
 <audio id="au" controls style="width:100%"></audio>
 <div class="row" style="margin-top:8px"><div><label>Começar a música em (seg)</label><input id="musIni" placeholder="0"></div>
 <button class="sm" style="margin-top:22px" onclick="$('musIni').value=$('au').currentTime.toFixed(1);salvarA()">Daqui ⟦</button></div>
 <label>Volume da música: <b id="vmT">35%</b></label><input type="range" id="musVol" min="0" max="100" value="35">
 <label>Volume do áudio original: <b id="voT">100%</b></label><input type="range" id="musOrig" min="0" max="150" value="100">
 <div class="tog"><div>Abaixar a música quando falam<small>a voz fica na frente</small></div><label class="sw"><input type="checkbox" id="musAbaixar" checked><i></i></label></div>
 <div class="hint">Original em 0% = só a música. Músicas famosas podem ser silenciadas pelas redes.</div>
</div></section>

<!-- ================= ESPELHAR ================= -->
<section data-s="espelhar" class="hide">
<div class="card"><h3>Espelhar imagem</h3>
 <div class="tog"><div>Espelhar o vídeo<small>inverte esquerda ↔ direita</small></div><label class="sw"><input type="checkbox" id="espelhar"><i></i></label></div>
 <video id="v2" muted playsinline style="margin-top:10px"></video>
 <div class="hint">⚠️ Texto que aparece dentro da cena fica ao contrário. Nos vídeos da campanha da Elis o editor não espelha (regra dela).</div>
</div></section>

<!-- ================= FILA ================= -->
<section data-s="fila" class="hide">
<div class="card"><h3>Fila de vídeos</h3>
 <div id="fila"><div class="hint">Nada na fila. Monte um corte em ✂️ Editar e toque em ➕ Fila.</div></div>
 <div class="row"><button class="sm" onclick="limparFila()">🧹 Limpar concluídos</button></div>
 <div class="hint">Os vídeos são feitos um depois do outro. Pode continuar montando outros cortes enquanto isso. Deixe o Termux aberto.</div>
</div>
<div class="card"><h3>Prontos (Memes_Prontos)</h3><div class="hint">Toque na rede pra abrir o app dela com o vídeo. A legenda já vai copiada: é só colar.</div><div class="prontos" id="prontos"></div></div>
</section>
</div>

<div class="bar"><button onclick="previa()">👁 Prévia</button><button onclick="enfileirar(false)">➕ Fila</button><button class="pri" onclick="enfileirar(true)">⚡ Gerar</button></div>
<div id="toast"></div>

<script>
const $=id=>document.getElementById(id);let D={},S={video:'',canal:'',cards:[],foto:'',filtros:['aprimorar','nitidez','vivido'],musica:null},pvJob=null,tq=null;
const v=$('v');
function toast(t){const e=$('toast');e.textContent=t;e.style.opacity=1;setTimeout(()=>e.style.opacity=0,2200)}
function seg(x){x=String(x||'').trim().replace(',','.');if(!x)return 0;return x.split(':').reverse().reduce((a,p,i)=>a+parseFloat(p||0)*60**i,0)}
function fmt(s){s=Math.max(0,s||0);const m=Math.floor(s/60);return m+':'+String((s%60).toFixed(1)).padStart(4,'0')}
function aba(t){document.querySelectorAll('section').forEach(e=>e.classList.toggle('hide',e.dataset.s!=t));
 document.querySelectorAll('.tabs button').forEach(e=>e.classList.toggle('on',e.dataset.t==t));window.scrollTo(0,0);if(t=='fila')verFila();
 if(t=='espelhar'&&v.src){$('v2').src=v.src;$('v2').currentTime=v.currentTime||1}}
function salvar(){const st={canal:S.canal,foto:S.foto,filtros:S.filtros,musica:S.musica,cor:S.cor,campanha:$('campanha').value};['headline','fonte','rodape','parte','selo','logo_extra'].forEach(k=>st[k]=$(k).value);try{localStorage.ed2=JSON.stringify(st)}catch(e){}}
async function carregar(){
 D=await (await fetch('/api/tudo')).json();$('pasta').textContent=D.pasta.split('/').slice(-1)[0];
 $('vids').innerHTML=D.videos.map(x=>`<div class="vid${x.nome==S.video?' on':''}" onclick="escolher('${encodeURIComponent(x.nome)}')"><span>${x.nome}</span><small>${x.mb} MB · ${x.quando}</small></div>`).join('')||'<div class="hint">Nenhum vídeo na pasta Download.</div>';
 $('canais').innerHTML=D.canais.map(c=>`<div class="chip${c.id==S.canal?' on':''}" onclick="canal('${c.id}')">${c.logo?`<img src="${c.logo}">`:'<img>'}<span>${c.nome}</span><small>${c.tipo}</small></div>`).join('');
 $('fotos').innerHTML=D.fotos.map(f=>`<img src="/foto?f=${f}" class="${f==S.foto?'on':''}" onclick="foto('${f}')">`).join('');
 $('prontos').innerHTML=D.prontos.map(n=>`<a href="/saida?f=${encodeURIComponent(n)}" target="_blank">🎬 ${n}</a>`).join('')||'<div class="hint">Nada ainda.</div>';
 rFiltros();rAudios();ajustarCanal();cmd()}
function escolher(n){S.video=decodeURIComponent(n);v.src='/video?f='+n;$('inicio').value='';$('fim').value='';carregar();salvar()}
function canal(id){S.canal=id;carregar();salvar()}
function tipo(){const c=(D.canais||[]).find(c=>c.id==S.canal);const m=$('modelo').value;return m?(m=='padrao'?'meme':m=='meiatela'?'meia tela':m):(c?c.tipo:'')}
function ajustarCanal(){const t=tipo(),ff=t=='fofoca';
 ['boxFonte','boxSelo','boxCards','boxFotos'].forEach(i=>$(i).classList.toggle('hide',!ff));
 ['boxRodape','boxParte'].forEach(i=>$(i).classList.toggle('hide',ff));$('tipoCanal').textContent=S.canal?('Modelo: '+t):'Escolha o canal'}
function marcar(k){$(k).value=v.currentTime.toFixed(1);desenhar();cmd()}
function limparTrecho(){$('inicio').value='';$('fim').value='';desenhar();cmd()}
function tocarTrecho(){v.currentTime=seg($('inicio').value);v.play()}
function desenhar(){const d=v.duration||0;if(!d)return;const a=seg($('inicio').value),b=seg($('fim').value)||d;
 $('sel').style.left=(a/d*100)+'%';$('sel').style.width=((b-a)/d*100)+'%';
 $('tIni').textContent='início '+fmt(a);$('tFim').textContent='fim '+fmt(b);$('tDur').textContent='trecho '+fmt(b-a);
 document.querySelectorAll('.tl .mk').forEach(e=>e.remove());S.cards.forEach(c=>mk('c',a+ +c.t0,a+ +c.t1,d));
 if(S.foto&&tipo()=='fofoca')mk('f',a+seg($('fotoT0').value),a+seg($('fotoT1').value),d)}
function mk(cl,x,y,d){const e=document.createElement('div');e.className='mk '+cl;e.style.left=(x/d*100)+'%';e.style.width=Math.max(1,(y-x)/d*100)+'%';$('tl').appendChild(e)}
v.addEventListener('timeupdate',()=>{if(v.duration)$('cab').style.left=(v.currentTime/v.duration*100)+'%';const b=seg($('fim').value);if(b&&v.currentTime>b&&!v.paused)v.pause()});
v.addEventListener('loadedmetadata',desenhar);
$('tl').addEventListener('pointerdown',e=>{const r=$('tl').getBoundingClientRect();if(v.duration)v.currentTime=(e.clientX-r.left)/r.width*v.duration});
function addCard(){const t=Math.max(0,v.currentTime-seg($('inicio').value));S.cards.push({texto:'',t0:t.toFixed(1),t1:(t+3).toFixed(1)});rCards()}
function rCards(){$('cards').innerHTML=S.cards.map((c,i)=>`<div class="it"><input placeholder="TEXTO 🔥" value="${c.texto.replace(/"/g,'&quot;')}" oninput="S.cards[${i}].texto=this.value;cmd()"><input class="n" value="${c.t0}" oninput="S.cards[${i}].t0=this.value;desenhar();cmd()"><input class="n" value="${c.t1}" oninput="S.cards[${i}].t1=this.value;desenhar();cmd()"><button class="sm" onclick="S.cards.splice(${i},1);rCards()">✕</button></div>`).join('');desenhar();cmd()}
function foto(f){S.foto=f;carregar();salvar()}function tirarFoto(){S.foto='';carregar();salvar()}
/* momentos fortes */
async function sugerirG(){if(!S.video){toast('Escolha um vídeo');return}$('sug').innerHTML='<div class="hint">Analisando o áudio… (vídeo longo demora um pouco)</div>';
 const r=await (await fetch('/api/sugerir?f='+encodeURIComponent(S.video)+'&dur='+$('durSug').value)).json();
 if(r.erro||!r.length){$('sug').innerHTML='<div class="hint">Não achei trechos.</div>';return}
 $('sug').innerHTML=r.map((o,i)=>`<div class="fj" onclick="usarSug(${o.inicio},${o.fim},${o.pico})"><div class="t"><b>${i?'':'🔥 '}${fmt(o.inicio)} → ${fmt(o.fim)}</b><span class="st pronto">força ${o.nota}</span></div><div class="hint">pico em ${fmt(o.pico)} · toque pra usar</div></div>`).join('')}
function usarSug(a,b,p){$('inicio').value=a.toFixed(1);$('fim').value=b.toFixed(1);v.currentTime=p;desenhar();cmd();toast('Trecho marcado')}
/* cores da legenda */
const CORES=[['','Padrão'],['ffd400','Amarelo'],['39ff14','Verde'],['00e5ff','Azul'],['a855ff','Roxo'],['ff3b3b','Vermelho'],['ff4fd8','Rosa'],['ffffff','Branco']];
function rCores(){$('cores').innerHTML=CORES.map(c=>`<div class="chip${(S.cor||'')==c[0]?' on':''}" style="width:64px" onclick="S.cor='${c[0]}';rCores();cmd();salvar()"><span style="display:block;width:30px;height:30px;border-radius:50%;background:${c[0]?'#'+c[0]:'linear-gradient(45deg,#ffc400,#a855ff)'}"></span><span>${c[1]}</span></div>`).join('')}
/* campanhas */
const CAMP={elis:{nome:'Elis Justi',tags:'#elisjusti #viewzbrazil #sertanejo #cowgirl',marca:'Instagram/YouTube: @elisjusti · TikTok: @elisjustioficial',regra:'Logo dela no vídeo todo, sem acelerar a voz, sem espelhar, nome ELIS JUSTI na headline.',proib:[]},
 ciate:{nome:'GBCiate',tags:'#gbciate #710fest #viewzbrazil #carros',marca:'Instagram: @gbciate @710_fest · TikTok/YouTube: @gbciate',regra:'Conteúdo dos últimos 15 dias, só trechos que favorecem a imagem dele. Mínimo 1.000 views pra contar.',proib:[]},
 cacheta:{nome:'Cacheta League',tags:'#cacheta #truco #poker #esportedamente',marca:'Marque o creator e o perfil oficial do Cacheta League.',regra:'Nada de dinheiro, valores, Pix ou estética de cassino.',proib:['aposta','apostar','bet','cassino','sorte','jogador','usuário','usuario','tigrinho','green','r$','pix','dinheiro','prêmio','premio','renda extra']}};
function campanha(){const c=CAMP[$('campanha').value];if(!c){$('regras').innerHTML='';return}
 if($('campanha').value=='elis'){$('logo_extra').value='elisjusti';$('velocidade_fixa').checked=true;if($('espelhar').checked){$('espelhar').checked=false;$('espelhar').dispatchEvent(new Event('change'))}}
 const ruins=proibidas();$('regras').innerHTML=`<b>${c.nome}:</b> ${c.regra}<br>📌 ${c.marca}<br>🏷️ ${c.tags}`+(ruins.length?`<br><b style="color:var(--er)">⚠️ Palavra proibida: ${ruins.join(', ')}</b>`:'');
 const h=$('headline').value.replace(/[*|]/g,' ').replace(/\s+/g,' ').trim();const m=c.marca.match(/@[\w.]+/g)||[];
 if(!$('post').dataset.editado)$('post').value=(h?h.charAt(0)+h.slice(1).toLowerCase()+'\n\n':'')+'Comenta o que você achou 👇\n'+m.join(' ')+'\n\n'+c.tags;cmd()}
function proibidas(){const c=CAMP[$('campanha').value];if(!c)return[];const t=(dados_txt()).toLowerCase();return c.proib.filter(w=>new RegExp('(^|[^a-zà-ú])'+w.replace('$','\\$')+'([^a-zà-ú]|$)').test(t))}
function dados_txt(){return [$('headline').value,$('fonte').value,$('selo').value,$('post').value,...S.cards.map(c=>c.texto)].join(' ')}
$('campanha').addEventListener('change',()=>{$('post').dataset.editado='';campanha();salvar()});$('post').addEventListener('input',()=>{$('post').dataset.editado='1';campanha()});
/* filtros */
function rFiltros(){$('gFiltros').innerHTML=(D.filtros||[]).map(f=>`<div class="fb${S.filtros.includes(f.id)?' on':''}" onclick="togF('${f.id}')">${f.nome}</div>`).join('');
 const n=S.filtros.length;$('bF').textContent=n;$('bF').classList.toggle('hide',!n)}
function togF(id){const i=S.filtros.indexOf(id);i<0?S.filtros.push(id):S.filtros.splice(i,1);rFiltros();salvar()}
function presetF(l){S.filtros=[...l];rFiltros();salvar()}
/* audio */
function rAudios(){$('auds').innerHTML=(D.audios||[]).map(a=>`<div class="aud${S.musica&&S.musica.nome==a.nome?' on':''}" onclick="escAudio('${encodeURIComponent(a.nome)}','${a.pasta}')"><span>🎵 ${a.nome.split('/').pop()}</span><small>${{editor:'escolhida',download:'Download',music:'Music',gravacoes:'Gravações',whatsapp:'WhatsApp'}[a.pasta]||''} · ${a.mb} MB</small></div>`).join('')||'<div class="hint">Nenhum áudio na pasta Download.</div>';
 $('bA').classList.toggle('hide',!S.musica);$('musNome').textContent=S.musica?('🎵 '+S.musica.nome.split('/').pop()):'Nenhuma música';$('boxMus').classList.toggle('hide',!S.musica)}
function escAudio(n,p){n=decodeURIComponent(n);S.musica={nome:n,pasta:p};$('au').src='/audio?f='+encodeURIComponent(n)+'&p='+p;salvarA();rAudios()}
function enviarAudio(inp){const f=inp.files[0];if(!f)return;const x=new XMLHttpRequest();$('upPg').classList.remove('hide');
 x.upload.onprogress=e=>{if(e.lengthComputable)$('upPg').firstElementChild.style.width=(e.loaded/e.total*100)+'%'};
 x.onload=async()=>{$('upPg').classList.add('hide');const r=JSON.parse(x.responseText);await carregar();escAudio(encodeURIComponent(r.nome),r.pasta);toast('Música pronta ✔');inp.value=''};
 x.onerror=()=>toast('Erro ao carregar a música');x.open('POST','/api/upload?nome='+encodeURIComponent(f.name));x.send(f)}
function semMusica(){S.musica=null;$('au').removeAttribute('src');salvar();rAudios()}
function salvarA(){if(S.musica){S.musica.inicio=seg($('musIni').value);S.musica.vol=+$('musVol').value;S.musica.vol_orig=+$('musOrig').value;S.musica.abaixar=$('musAbaixar').checked}
 $('vmT').textContent=$('musVol').value+'%';$('voT').textContent=$('musOrig').value+'%';salvar()}
['musIni','musVol','musOrig','musAbaixar'].forEach(i=>$(i).addEventListener('input',salvarA));$('musAbaixar').addEventListener('change',salvarA);
/* espelhar */
$('espelhar').addEventListener('change',()=>{const on=$('espelhar').checked;$('v2').classList.toggle('esp',on);v.classList.toggle('esp',on);$('bE').classList.toggle('hide',!on);cmd()});
/* dados + comando */
function dados(){const p={video:S.video,canal:S.canal,cards:S.cards.filter(c=>c.texto),filtros:S.filtros,musica:S.musica,post_legenda:$('post').value};
 ['headline','fonte','rodape','parte','selo','logo_extra','cortar_topo','cortar_baixo','enquadrar','modelo','nome_saida'].forEach(k=>p[k]=$(k).value.trim());
 if(tipo()!='fofoca'){p.fonte='';p.selo='';p.cards=[];p.logo_extra=''}else{p.rodape='';p.parte=''}
 p.inicio=seg($('inicio').value);p.fim=seg($('fim').value);
 ['legenda','velocidade_fixa','fade','sem_unico','espelhar'].forEach(k=>p[k]=$(k).checked);p.legenda_cor=S.cor||'';
 p.fotos=(S.foto&&tipo()=='fofoca')?[{nome:S.foto,t0:seg($('fotoT0').value),t1:seg($('fotoT1').value)}]:[];return p}
let tc=null;function cmd(){clearTimeout(tc);tc=setTimeout(async()=>{if(!S.video||!S.canal){$('cmd').textContent='Escolha o vídeo e o canal';return}
 const r=await (await fetch('/api/comando',{method:'POST',body:JSON.stringify(dados())})).json();$('cmd').textContent=r.cmd||r.erro},300)}
document.addEventListener('input',e=>{if(e.target.closest('section[data-s=editar]')){ajustarCanal();cmd();salvar();if(e.target.id!='post'&&$('campanha').value)campanha()}});
$('modelo').addEventListener('change',()=>{ajustarCanal();cmd()});
function copiarCmd(){navigator.clipboard.writeText($('cmd').textContent).then(()=>toast('Comando copiado'))}
function ok(){const r=proibidas();if(r.length){toast('Palavra proibida pela campanha: '+r.join(', '));return 0}if(!S.video){toast('Escolha um vídeo');aba('editar');return 0}if(!S.canal){toast('Escolha o canal');aba('editar');return 0}return 1}
/* previa */
async function previa(){if(!ok())return;const r=await (await fetch('/api/previa',{method:'POST',body:JSON.stringify(dados())})).json();if(r.erro){toast(r.erro);return}
 pvJob=r.id;aba('editar');$('boxPrevia').classList.remove('hide');$('imgPrevia').classList.add('hide');$('pvTit').textContent='Gerando prévia…';$('pvPg').style.width='0';
 $('boxPrevia').scrollIntoView({behavior:'smooth'});const t=setInterval(async()=>{const j=await (await fetch('/api/job?id='+pvJob)).json();
  $('pvPg').style.width=j.progresso+'%';$('pvLog').textContent=(j.log||[]).slice(-4).join('\n');if(j.status=='rodando'||j.status=='na fila')return;clearInterval(t);
  if(j.status=='pronto'){$('pvTit').textContent='Prévia ✔';$('imgPrevia').src=j.url+'&t='+Date.now();$('imgPrevia').classList.remove('hide')}else $('pvTit').textContent='Prévia deu erro ✖'},1000)}
/* fila */
async function enfileirar(ir){if(!ok())return;const r=await (await fetch('/api/render',{method:'POST',body:JSON.stringify(dados())})).json();if(r.erro){toast(r.erro);return}
 toast('Adicionado à fila ✔');if(ir)aba('fila');verFila()}
const ST={'na fila':'na fila','rodando':'fazendo','pronto':'pronto','erro':'erro','cancelado':'cancelado'};
async function verFila(){clearTimeout(tq);const L=await (await fetch('/api/fila')).json();
 const pend=L.filter(j=>j.status=='na fila'||j.status=='rodando').length;$('bQ').textContent=pend;$('bQ').classList.toggle('hide',!pend);
 $('fila').innerHTML=L.length?L.map((j,i)=>`<div class="fj"><div class="t"><b>${i+1}. ${j.headline||j.nome}</b><span class="st ${j.status}">${ST[j.status]||j.status}</span></div>
 <div class="hint">${j.canal} · ${j.nome}.mp4 ${j.status=='rodando'?'· '+j.etapa:''}</div>
 ${j.status=='rodando'?`<div class="prog"><i style="width:${j.progresso}%"></i></div>`:''}
 ${j.status=='erro'?`<pre>${(j.log||[]).slice(-4).join('\n')}</pre>`:''}
 ${j.qc?`<div class="hint">${j.qc.ok?'✅ Qualidade ok'+(j.qc.corrigido?' (volume ajustado)':''):'⚠️ '+j.qc.avisos.join(' · ')} · ${j.qc.dur}s${j.qc.lufs!=null?' · '+j.qc.lufs+' LUFS':''}</div>`:''}
 <div class="row" style="margin-top:6px">${j.status=='pronto'?`<a href="${j.url}" target="_blank"><button class="sm">▶ Ver</button></a><a href="${j.url}&baixar=1"><button class="sm">⬇ Baixar</button></a>`:''}
 ${j.status=='rodando'||j.status=='na fila'?`<button class="sm" onclick="pararJ('${j.id}')">✕ Cancelar</button>`:`<button class="sm" onclick="remover('${j.id}')">Remover</button>`}</div></div>`).join(''):'<div class="hint">Nada na fila.</div>';
 if(pend){tq=setTimeout(verFila,1500)}else if(L.some(j=>j.status=='pronto'))carregarProntos()}
let PRONTOS={};
async function carregarProntos(){const d=await (await fetch('/api/tudo')).json();PRONTOS={pasta:d.saida_real,posts:d.posts||{}};
 $('prontos').innerHTML=d.prontos.map((n,i)=>`<div class="pronto"><a href="/saida?f=${encodeURIComponent(n)}" target="_blank">🎬 ${n}</a>
 <div class="redes"><button class="sm" onclick="postar(${i},'tiktok')">TikTok</button><button class="sm" onclick="postar(${i},'instagram')">Instagram</button>
 <button class="sm" onclick="postar(${i},'youtube')">YouTube</button><button class="sm" onclick="postar(${i},'facebook')">Facebook</button></div></div>`).join('');
 PRONTOS.lista=d.prontos}
/* postar: abre o app da rede com o video e deixa a legenda copiada */
function legendaRede(txt,rede){if(rede!='tiktok')return txt;let n=0;   // TikTok: no maximo 5 hashtags
 return txt.replace(/#[\wÀ-ú]+/g,t=>++n<=5?t:'').replace(/[ \t]+\n/g,'\n').replace(/ {2,}/g,' ').trim()}
function postar(i,rede){const n=PRONTOS.lista[i];let txt=PRONTOS.posts[n]||$('post').value||'';txt=legendaRede(txt,rede);
 if(!window.Android||!Android.postar){navigator.clipboard&&navigator.clipboard.writeText(txt);toast('Postar direto só funciona pelo app Editor Jota. Legenda copiada.');return}
 const r=Android.postar(PRONTOS.pasta+'/'+n,rede,txt);toast(r||('Legenda copiada! Cole no '+({tiktok:'TikTok',instagram:'Instagram',youtube:'YouTube',facebook:'Facebook'}[rede])))}
async function pararJ(id){await fetch('/api/parar',{method:'POST',body:JSON.stringify({id})});verFila()}
async function remover(id){await fetch('/api/remover',{method:'POST',body:JSON.stringify({id})});verFila()}
async function limparFila(){await fetch('/api/remover',{method:'POST',body:JSON.stringify({limpar:1})});verFila()}
try{const st=JSON.parse(localStorage.ed2||'{}');['headline','fonte','rodape','parte','selo','logo_extra'].forEach(k=>{if(st[k])$(k).value=st[k]});
 if(st.canal)S.canal=st.canal;if(st.foto)S.foto=st.foto;if(st.cor)S.cor=st.cor;if(st.campanha)$('campanha').value=st.campanha;if(st.filtros)S.filtros=st.filtros;if(st.musica){S.musica=st.musica;$('musIni').value=st.musica.inicio||'';$('musVol').value=st.musica.vol??35;$('musOrig').value=st.musica.vol_orig??100;$('musAbaixar').checked=st.musica.abaixar!==false;$('au').src='/audio?f='+encodeURIComponent(st.musica.nome)+'&p='+st.musica.pasta}}catch(e){}
rCores();salvarA();carregar().then(()=>campanha()).then(()=>{if(D.videos[0])escolher(encodeURIComponent(D.videos[0].nome));if(location.hash)aba(location.hash.slice(1))});verFila();
</script></body></html>"""


def main():
    import socket
    with socket.socket() as t:
        if t.connect_ex(("127.0.0.1", PORTA)) == 0:
            print(f"O painel ja esta rodando em http://localhost:{PORTA}")
            if "--sem-abrir" not in sys.argv and shutil.which("termux-open-url"):
                subprocess.run(["termux-open-url", f"http://localhost:{PORTA}"], capture_output=True)
            return
    threading.Thread(target=trabalhador, daemon=True).start()
    srv = ThreadingHTTPServer(("127.0.0.1", PORTA), H)
    url = f"http://localhost:{PORTA}"
    print(f"\n  Painel do editor rodando!\n  Abra no navegador do celular: {url}\n  (Para fechar: CTRL + C)\n")
    if "--sem-abrir" not in sys.argv and shutil.which("termux-open-url"):
        subprocess.run(["termux-open-url", url], capture_output=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nPainel fechado.")


if __name__ == "__main__":
    main()
