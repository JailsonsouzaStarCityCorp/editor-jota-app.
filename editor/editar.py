#!/usr/bin/env python3
"""
editar.py - coloca um meme no seu template, com headline, corte automatico e zoom leve.

Uso:
  python editar.py VIDEO TEMPLATE "HEADLINE"

  VIDEO     caminho do .mp4, ou a palavra  ultimo  (pega o video mais novo da pasta Download)
  TEMPLATE  memudobr | jota | memeclaude | jotinha | driverush
  HEADLINE  o texto de cima. Use  |  para pular para um novo bloco.
            Ex: "O ponto fecha as 8h. | Eu as 7:55 ainda a 3 bairros:"

Opcoes:
  --zoom 0.06          intensidade do zoom (0 desliga). Padrao 0.06 = 6%
  --intervalo 2        segundos de cada zoom. Padrao 2
  --cortar-topo N      corta N pixels a mais do topo da cena (para tirar texto em cima do video)
  --cortar-baixo N     idem, embaixo
  --sem-corte-auto     usa o video inteiro, sem detectar a cena
  --saida ARQUIVO.mp4  nome do arquivo final
  --previa             gera so uma imagem de previa (rapido), sem renderizar o video
"""
import argparse, glob, json, os, random, re, subprocess, sys, tempfile

try:
    from PIL import Image, ImageDraw, ImageFont, ImageChops
except ImportError:
    sys.exit("Falta o Pillow. Rode:  pip install pillow")

PASTA = os.path.dirname(os.path.abspath(__file__))
FONTES = os.path.join(PASTA, "fontes")
TEMPLATES = os.path.join(PASTA, "templates")

W, H = 1080, 1920
# area do video no template (x1, y1, x2, y2)
AREA = (0, 690, 1080, 1560)
PAD = 14  # margem extra para o movimento do quadro
IDIOMA = "pt"
CANAIS_FILME = {"thejota", "neoronios", "nexora", "mentalista", "driverush", "zenthaku"}
# area da headline
TXT_Y1, TXT_Y2, TXT_LARG = 280, 680, 960

DOWNLOAD = os.path.expanduser("~/storage/shared/Download")
SAIDA_PADRAO = os.path.expanduser("~/storage/shared/Memes_Prontos")


def rodar(cmd, capturar=False):
    r = subprocess.run(cmd, stdout=subprocess.PIPE if capturar else None,
                       stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        sys.exit("Erro no ffmpeg:\n" + r.stderr[-1500:])
    return r.stdout


def info_video(caminho):
    out = rodar(["ffprobe", "-v", "error", "-show_entries",
                 "stream=codec_type,width,height:format=duration",
                 "-of", "json", caminho], capturar=True)
    j = json.loads(out)
    v = next((s for s in j["streams"] if s["codec_type"] == "video"), None)
    if v is None:
        sys.exit(f"ERRO: o arquivo {os.path.basename(caminho)} nao tem imagem (so audio ou vazio). "
                 "Confira se o video certo e o mais novo da Download.")
    tem_audio = any(s["codec_type"] == "audio" for s in j["streams"])
    return int(v["width"]), int(v["height"]), float(j["format"]["duration"]), tem_audio


# ---------------------------------------------------------------- corte automatico
def maior_faixa(mask, minimo):
    melhor, ini = (0, len(mask) - 1), None
    tam_melhor = 0
    for i, m in enumerate(list(mask) + [False]):
        if m and ini is None:
            ini = i
        elif not m and ini is not None:
            if i - ini > tam_melhor:
                tam_melhor, melhor = i - ini, (ini, i - 1)
            ini = None
    return melhor if tam_melhor >= minimo else None


def detectar_cena(caminho, vw, vh, dur):
    """Acha a regiao do video que se mexe (a cena), ignorando faixas pretas/brancas,
    logos e legendas paradas de outras paginas."""
    n = 10
    tmp = tempfile.mkdtemp()
    frames = []
    for k in range(n):
        t = dur * (k + 0.5) / n
        f = os.path.join(tmp, f"f{k}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", caminho,
                        "-frames:v", "1", "-vf", "scale=180:-2", f],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(f):
            frames.append(Image.open(f).convert("L"))
    if len(frames) < 3:
        return 0, 0, vw, vh
    fw, fh = frames[0].size
    px = [list(fr.tobytes()) for fr in frames]

    def variacao(i):
        vals = [p[i] for p in px]
        m = sum(vals) / len(vals)
        return sum(abs(v - m) for v in vals) / len(vals)

    var = [variacao(i) for i in range(fw * fh)]
    # textura (para cenas quase paradas)
    tex = [0.0] * (fw * fh)
    base = px[len(px) // 2]
    for y in range(fh):
        for x in range(1, fw):
            tex[y * fw + x] = abs(base[y * fw + x] - base[y * fw + x - 1])

    def faixa(eixo_linhas, limiar_var, usar_tex=False):
        tamanho = fh if eixo_linhas else fw
        outro = fw if eixo_linhas else fh
        score = []
        for a in range(tamanho):
            s = 0.0
            for b in range(outro):
                i = a * fw + b if eixo_linhas else b * fw + a
                s += tex[i] if usar_tex else var[i]
            score.append(s / outro)
        return [s > limiar_var for s in score]

    linhas = faixa(True, 6.0)
    colunas = faixa(False, 6.0)
    fl = maior_faixa(linhas, fh * 0.2)
    fc = maior_faixa(colunas, fw * 0.3)
    if fl is None or fc is None:  # cena parada: tenta por textura
        fl = maior_faixa(faixa(True, 4.0, True), fh * 0.2) or (0, fh - 1)
        fc = maior_faixa(faixa(False, 4.0, True), fw * 0.3) or (0, fw - 1)

    esc = vw / fw
    x1, x2 = int(fc[0] * esc), int((fc[1] + 1) * esc)
    y1, y2 = int(fl[0] * esc), int((fl[1] + 1) * esc)
    # margem de seguranca de 1% para nao pegar borda/linha
    mx, my = int((x2 - x1) * 0.01), int((y2 - y1) * 0.01)
    x1, x2, y1, y2 = x1 + mx, x2 - mx, y1 + my, y2 - my
    w, h = (x2 - x1) // 2 * 2, (y2 - y1) // 2 * 2
    return max(0, x1), max(0, y1), w, h


# ---------------------------------------------------------------- headline
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]+")


def carregar_emoji():
    p = os.path.join(FONTES, "NotoColorEmoji.ttf")
    try:
        return ImageFont.truetype(p, 109)
    except Exception:
        return None


def pedacos(texto):
    """separa texto e emojis"""
    out, pos = [], 0
    for m in EMOJI_RE.finditer(texto):
        if m.start() > pos:
            out.append(("t", texto[pos:m.start()]))
        out.append(("e", m.group()))
        pos = m.end()
    if pos < len(texto):
        out.append(("t", texto[pos:]))
    return out


def img_emoji(fonte_emoji, emo, tam):
    if fonte_emoji is None:
        return None
    c = Image.new("RGBA", (160 * len(emo), 160), (0, 0, 0, 0))
    try:
        ImageDraw.Draw(c).text((0, 0), emo, font=fonte_emoji, embedded_color=True)
    except Exception:
        return None
    bb = c.getbbox()
    if not bb:
        return None
    c = c.crop(bb)
    return c.resize((max(1, int(c.width * tam / c.height)), tam), Image.LANCZOS)


def largura(d, linha, fonte, fe, tam):
    w = 0
    for tipo, s in pedacos(linha):
        if tipo == "t":
            w += d.textlength(s, font=fonte)
        else:
            e = img_emoji(fe, s, tam)
            w += e.width if e else 0
    return w


def quebrar(d, texto, fonte, fe, tam):
    linhas, atual = [], ""
    palavras = []
    for p in texto.split():
        if palavras and EMOJI_RE.fullmatch(p):
            palavras[-1] += " " + p
        else:
            palavras.append(p)
    for p in palavras:
        t = (atual + " " + p).strip()
        if largura(d, t, fonte, fe, tam) <= TXT_LARG:
            atual = t
        else:
            if atual:
                linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    return linhas


def desenhar_headline(img, headline):
    d = ImageDraw.Draw(img)
    fe = carregar_emoji()
    blocos = [b.strip() for b in headline.split("|") if b.strip()]
    for tam in (58, 54, 50, 46, 42, 38):
        fonte = ImageFont.truetype(os.path.join(FONTES, "Poppins-Regular.ttf"), tam)
        lh, esp = int(tam * 1.28), int(tam * 0.6)
        todas = [quebrar(d, b, fonte, fe, tam) for b in blocos]
        altura = sum(len(l) for l in todas) * lh + esp * (len(todas) - 1)
        if altura <= TXT_Y2 - TXT_Y1:
            break
    y = TXT_Y1 + (TXT_Y2 - TXT_Y1 - altura) // 2
    for bi, linhas in enumerate(todas):
        if bi:
            y += esp
        for ln in linhas:
            x = (W - largura(d, ln, fonte, fe, tam)) / 2
            for tipo, s in pedacos(ln):
                if tipo == "t":
                    d.text((x, y), s, font=fonte, fill="black")
                    x += d.textlength(s, font=fonte)
                else:
                    e = img_emoji(fe, s, tam)
                    if e:
                        img.paste(e, (int(x), int(y + tam * 0.22)), e)
                        x += e.width
            y += lh


def desenhar_rodape(img, texto, y=1600):
    if not texto:
        return
    d = ImageDraw.Draw(img)
    fe = carregar_emoji()
    fonte = ImageFont.truetype(os.path.join(FONTES, "Poppins-Bold.ttf"), 40)
    x = (W - largura(d, texto, fonte, fe, 44)) / 2
    for tipo, s in pedacos(texto):
        if tipo == "t":
            d.text((x, y), s, font=fonte, fill="black")
            x += d.textlength(s, font=fonte)
        else:
            e = img_emoji(fe, s, 44)
            if e:
                img.paste(e, (int(x), y + 4), e)
                x += e.width


# ---------------------------------------------------------------- fundo anti-borda
def textura_fundo(img):
    """Deixa o branco levemente texturizado e com um degrade sutil, para o
    Facebook/Instagram nao identificarem as areas brancas como borda.
    A diferenca e quase invisivel para quem assiste."""
    w, h = img.size
    ruido = Image.effect_noise((w, h), 10).point(lambda v: min(14, abs(v - 128)))
    grad = Image.linear_gradient("L").resize((w, h)).point(lambda v: v * 10 // 255)
    sombra = ImageChops.add(ruido, grad).convert("RGB")
    return ImageChops.subtract(img, sombra)


# ---------------------------------------------------------------- principal
def tirar_faixas(video, vw, vh, dur):
    """so remove faixas pretas (cropdetect), sem cortar a cena."""
    r = subprocess.run(["ffmpeg", "-ss", f"{min(dur * 0.3, 20):.1f}", "-i", video, "-t", "8",
                        "-vf", "cropdetect=24:2:0", "-f", "null", "-"], capture_output=True, text=True)
    m = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", r.stderr)
    if not m:
        return 0, 0, vw, vh
    cw, ch, cx, cy = map(int, m[-1])
    if cw < vw * 0.5 or ch < vh * 0.3:
        return 0, 0, vw, vh
    print(f"Faixas pretas removidas: {cw}x{ch}")
    return cx, cy, cw // 2 * 2, ch // 2 * 2


def achar_ultimo():
    vids = [f for ext in ("mp4", "mov", "MP4", "webm") for f in glob.glob(os.path.join(DOWNLOAD, f"*.{ext}"))]
    if not vids:
        sys.exit(f"Nenhum video em {DOWNLOAD}")
    return max(vids, key=os.path.getmtime)


def main():
    ap = argparse.ArgumentParser(description="Coloca meme no template")
    ap.add_argument("video")
    ap.add_argument("template")
    ap.add_argument("headline", nargs="?", default="")
    ap.add_argument("--zoom", type=float, default=0.06)
    ap.add_argument("--intervalo", type=float, default=2.0)
    ap.add_argument("--cortar-topo", type=int, default=0)
    ap.add_argument("--cortar-baixo", type=int, default=0)
    ap.add_argument("--sem-corte-auto", action="store_true")
    ap.add_argument("--saida")
    ap.add_argument("--previa", action="store_true")
    ap.add_argument("--sem-unico", action="store_true", help="desliga o anti-duplicidade")
    ap.add_argument("--estatico", action="store_true", help="desliga o movimento do quadro inteiro")
    ap.add_argument("--espelhar", action="store_true", help="espelha o video (nao use se tiver texto na cena)")
    ap.add_argument("--rodape", default="Já segue aí pra não perder os próximos 🤣🤣",
                    help="texto de baixo (use \"\" para tirar)")
    ap.add_argument("--fundo-liso", action="store_true", help="fundo branco 100%% liso (pode ser marcado como borda)")
    ap.add_argument("--modelo", default=None, choices=["padrao", "meiatela", "filme", "fofoca", "colagem", "broll"],
                    help="padrao = template branco | meiatela = imagem em cima + faixa vermelha + video embaixo")
    ap.add_argument("--imagem", help="(meiatela) imagem de cima: caminho, ou 'ultima' = foto mais nova da Download. "
                                     "Sem isso, usa um quadro do proprio video")
    ap.add_argument("--cor-faixa", default="", help="cor da faixa em hex (meiatela: vermelho; colagem: rosa)")
    ap.add_argument("--legenda", action="store_true", help="legenda animada automatica (precisa do whisper.cpp)")
    ap.add_argument("--legenda-cor", default="", help="cor da palavra destacada (hex). Padrao amarelo")
    ap.add_argument("--legenda-demo", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--inicio", help="corta o video a partir daqui (ex: 18:28 ou 75.5)")
    ap.add_argument("--fim", help="corta o video ate aqui (ex: 19:12)")
    ap.add_argument("--gancho", help="(meia tela) trecho do gancho no inicio, em segundos do corte. Ex: 4-8.7")
    ap.add_argument("--sem-gancho", action="store_true", help="(meia tela) nao coloca gancho no inicio")
    ap.add_argument("--simples", action="store_true", help="(meia tela) modelo antigo, sem o modo pro")
    ap.add_argument("--sem-musica", action="store_true", help="(meia tela pro) sem trilha de fundo")
    ap.add_argument("--texto-fim", default="A TRETA CONTINUA…", help="(meia tela pro) frase do encerramento")
    ap.add_argument("--velocidade", type=float, help="velocidade fixa, ex: 1.10 (10%% mais rapido). Padrao: aleatorio 1.03-1.07")
    ap.add_argument("--fade", action="store_true", help="fade in e fade out (automatico no canal jota)")
    ap.add_argument("--sem-fade", action="store_true", help="desliga o fade do canal jota")
    ap.add_argument("--fonte", default="", help="(fofoca) texto da FONTE embaixo do video, ex: \"pronunciamento do Toguro no YouTube\"")
    ap.add_argument("--selo", default=None, help="(fofoca) texto do selo. Padrao do canal (FOFOCA / CLIPS)")
    ap.add_argument("--card", action="append", help="(fofoca) card verde, ex: --card \"R$ 190 MIL 💸@8.5\" (pode repetir)")
    ap.add_argument("--foto", action="append", help="(fofoca) foto por cima do video: --foto elis05@3-7 (pode repetir)")
    ap.add_argument("--sem-rosto", action="store_true", help="(fofoca) nao seguir o rosto; usa o corte fixo")
    ap.add_argument("--enquadrar", type=float, default=None, help="(fofoca) altura do recorte: 0=topo 0.5=meio 1=baixo. Padrao: automatico")
    ap.add_argument("--sem-aprimorar", action="store_true", help="(fofoca) desliga os filtros aprimorar + qualidade 4K + vivido")
    ap.add_argument("--logo-extra", default="", help="(fofoca) logo de campanha no lugar do selo, ex: elisjusti")
    ap.add_argument("--sem-legenda", action="store_true", help="(fofoca) nao faz a legenda automatica")
    ap.add_argument("--titulo", default="", help="(colagem) titulo escrito em cima das imagens")
    ap.add_argument("--img1", default="", help="(colagem) imagem da esquerda (nome da pasta fotos/ ou caminho)")
    ap.add_argument("--img2", default="", help="(colagem) imagem da direita")
    ap.add_argument("--cor-titulo", default="4fe3ff", help="(colagem) cor do titulo, ex: 4fe3ff")
    ap.add_argument("--broll", action="append", help="(broll) imagem embaixo num tempo: --broll carro@3-6 ou carro@3-6@whoosh (pode repetir)")
    ap.add_argument("--som-broll", default="clique", choices=["clique", "pop", "whoosh", "nenhum"],
                    help="(broll) som quando cada b-roll aparece")
    ap.add_argument("--parte", default="", help="(filme) etiqueta embaixo do video, ex: \"Parte 3\"")
    a = ap.parse_args()
    global IDIOMA
    IDIOMA = "en" if a.template.lower() in INGLES else "pt"
    if not a.cor_faixa:
        a.cor_faixa = "ff4fb8" if a.modelo == "colagem" else "e50914"

    video = achar_ultimo() if a.video == "ultimo" else os.path.expanduser(a.video)
    if not os.path.exists(video):
        sys.exit(f"Video nao encontrado: {video}")
    a.template = a.template.lower()
    tpl = os.path.join(TEMPLATES, a.template + ".png")
    so_logo = os.path.exists(os.path.join(LOGOS, a.template + ".png"))
    if a.modelo is None:  # escolhe o modelo certo do canal
        a.modelo = ("fofoca" if a.template in CANAIS_FOFOCA else
                    "filme" if a.template in CANAIS_FILME else
                    "padrao" if os.path.exists(tpl) else "meiatela")
    if not os.path.exists(tpl):
        if not so_logo:
            nomes = sorted(set(os.path.splitext(f)[0] for f in os.listdir(TEMPLATES) + os.listdir(LOGOS)))
            sys.exit(f"Canal '{a.template}' nao existe. Opcoes: {', '.join(nomes)}")
        if a.modelo == "padrao":  # canal sem template branco: escolhe o modelo certo sozinho
            a.modelo = ("fofoca" if a.template in CANAIS_FOFOCA else
                        "filme" if a.template in CANAIS_FILME else "meiatela")
            print(f"Canal {a.template}: usando modelo {a.modelo}")
        tpl = os.path.join(TEMPLATES, "memudobr.png")  # so como base, nao aparece

    if a.inicio or a.fim:
        def seg(x):
            p = [float(v) for v in str(x).replace(",", ".").split(":")]
            return sum(v * 60 ** i for i, v in enumerate(reversed(p)))
        _vw, _vh, dur_src, _ta = info_video(video)
        print(f"Video de origem: {os.path.basename(video)} ({int(dur_src//60)}min{int(dur_src%60):02d}s)")
        if a.inicio and seg(a.inicio) >= dur_src - 1:
            sys.exit(f"ERRO: --inicio {a.inicio} passa do fim desse video, que so tem "
                     f"{int(dur_src//60)}:{int(dur_src%60):02d}. O 'ultimo' pegou o video errado? "
                     "Use o nome do arquivo no lugar de ultimo.")
        tmpc = tempfile.mkdtemp()
        cortado = os.path.join(tmpc, "corte.mp4")
        cmd = ["ffmpeg", "-v", "error", "-y"]
        if a.inicio:
            cmd += ["-ss", f"{seg(a.inicio):.2f}"]
        cmd += ["-i", video]
        if a.fim:
            cmd += ["-t", f"{seg(a.fim) - (seg(a.inicio) if a.inicio else 0):.2f}"]
        print("Cortando o trecho...")
        rodar(cmd + ["-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-c:a", "aac", "-b:a", "192k", cortado])
        a._nome_base = os.path.splitext(os.path.basename(video))[0] + f"_{str(a.inicio or '0').replace(':', '')}"
        video = cortado
    vw, vh, dur, tem_audio = info_video(video)
    print(f"Video: {os.path.basename(video)}  {vw}x{vh}  {dur:.1f}s")

    if a.sem_corte_auto:
        cx, cy, cw, ch = 0, 0, vw, vh
    elif a.modelo in ("fofoca", "colagem", "broll"):
        cx, cy, cw, ch = tirar_faixas(video, vw, vh, dur)
    else:
        print("Detectando a cena...")
        cx, cy, cw, ch = detectar_cena(video, vw, vh, dur)
    if a.cortar_topo + a.cortar_baixo >= ch - 100:
        print(f"AVISO: --cortar-topo {a.cortar_topo} + --cortar-baixo {a.cortar_baixo} e maior que o video "
              f"({ch}px de altura). Ignorando esses cortes e usando o video inteiro.")
    else:
        cy += a.cortar_topo
        ch -= a.cortar_topo + a.cortar_baixo
    ch = ch // 2 * 2
    print(f"Corte da cena: x={cx} y={cy} {cw}x{ch}")

    # fundo com headline; area do video pintada de preto (por baixo de tudo)
    base = Image.open(tpl).convert("RGB")
    ImageDraw.Draw(base).rectangle((0, 1540, W, 1700), fill="white")  # tira o rodape antigo
    desenhar_rodape(base, a.rodape)
    if not a.fundo_liso:
        base = textura_fundo(base)
    if a.headline:
        desenhar_headline(base, a.headline)
    # tela um pouco maior que 1080x1920: o quadro inteiro "flutua" alguns pixels
    # durante o video, para o Facebook nao achar que e imagem estatica
    P = 0 if a.estatico else PAD
    grande = Image.new("RGB", (W + 2 * P, H + 2 * P), "white")
    if P:
        grande.paste(base.resize((W + 2 * P, H + 2 * P)), (0, 0))  # preenche as margens
    grande.paste(base, (P, P))
    base = grande
    VX, VY = 0, AREA[1] + P                 # video ocupa a largura toda da tela maior
    aw, ah = W + 2 * P, AREA[3] - AREA[1]
    ImageDraw.Draw(base).rectangle((VX, VY, VX + aw, VY + ah), fill="black")
    # escala "cobrir": o video preenche a area toda, sem borda
    esc = max(aw / cw, ah / ch) * 1.01
    sw, sh = int(cw * esc) // 2 * 2 + 2, int(ch * esc) // 2 * 2 + 2

    os.makedirs(SAIDA_PADRAO, exist_ok=True) if not a.saida else None
    nome = a.saida or os.path.join(
        SAIDA_PADRAO, f"{a.template}{'' if a.modelo == 'padrao' else '_' + a.modelo}_"
                      f"{getattr(a, '_nome_base', os.path.splitext(os.path.basename(video))[0])}.mp4")

    tmpdir = tempfile.mkdtemp()
    fundo = os.path.join(tmpdir, "fundo.png")
    base.save(fundo)

    # ---------- anti-duplicidade: variacoes aleatorias e sutis em cada video
    if a.sem_unico:
        vel, ini, cor, grao, vol, jit, fase = 1.0, 0.0, "", "", 1.0, (0, 0, 0, 0), 0
    else:
        vel = a.velocidade or round(random.uniform(1.03, 1.07), 3)  # um pouco mais rapido
        if a.template in SEM_ALTERAR or a.logo_extra in SEM_ALTERAR:
            vel = 1.0; a.espelhar = False
        ini = round(random.uniform(0.15, 0.4), 2) if dur > 4 else 0.0  # corta o comeco
        cor = (f"eq=contrast={random.uniform(1.03, 1.08):.3f}:saturation={random.uniform(1.04, 1.12):.3f}"
               f":brightness={random.uniform(-0.01, 0.02):.3f}:gamma={random.uniform(0.97, 1.03):.3f},")
        grao = ""  # granulado agora e aplicado no quadro inteiro
        vol = round(random.uniform(0.95, 1.05), 2)
        jit = tuple(random.randint(0, max(2, int(min(cw, ch) * 0.025)) // 2 * 2) for _ in range(4))
        fase = random.randint(0, 1)                            # zoom comeca aproximando ou afastando
        print(f"Anti-duplicidade: velocidade {vel}x, corte inicial {ini}s, cor/grao/audio variados")
    # recorte extra aleatorio (muda o enquadramento)
    cx, cy = cx + jit[0], cy + jit[1]
    cw, ch = (cw - jit[0] - jit[2]) // 2 * 2, (ch - jit[1] - jit[3]) // 2 * 2
    esc = max(aw / cw, ah / ch) * 1.01
    sw, sh = int(cw * esc) // 2 * 2 + 2, int(ch * esc) // 2 * 2 + 2
    espelho = "hflip," if a.espelhar else ""
    dur_final = (dur - ini) / vel

    a._sub = ""
    pro = a.modelo == "meiatela" and not a.simples
    if pro:
        return meia_tela_pro(a, video, nome, dur, tem_audio, (cx, cy, cw, ch), cor, ini, tmpdir)
    global TEMA
    TEMA = TEMAS.get(a.template, TEMAS["padrao"])
    if a.modelo in ("fofoca", "colagem", "broll") and not a.sem_legenda and not a.previa and (a.legenda or all(achar_whisper())):
        a.legenda = True
    if a.legenda or a.legenda_demo:
        y_leg = {"padrao": 1470, "meiatela": 1690, "filme": 1370, "fofoca": 1400, "colagem": 1660, "broll": BR_VH - 150}[a.modelo]
        if a.legenda_demo:
            pal = demo_palavras(dur_final)
        else:
            pal = transcrever(video, tmpdir, a.headline)
            pal = [(max(0.0, (t0 - ini) / vel), max(0.0, (t1 - ini) / vel), w) for t0, t1, w in pal]
        if pal:
            ass = os.path.join(tmpdir, "legenda.ass")
            if a.modelo in ("fofoca", "colagem", "broll"):
                gerar_ass_salto(pal, ass, y_leg, a.legenda_cor)
            else:
                gerar_ass(pal, ass, y_leg, a.legenda_cor or "ffe600")
            a._sub = f"subtitles=filename='{ass}':fontsdir='{FONTES}',"
            print(f"Legenda: {len(pal)} palavras")
        else:
            print("Legenda: nenhuma fala encontrada, seguindo sem legenda")

    if a.modelo in ("fofoca", "colagem", "broll"):
        return fofoca(a, video, nome, dur, dur_final, tem_audio, (cx, cy, cw, ch),
                      vel, ini, cor, vol, fase, espelho, tmpdir)
    if a.modelo == "filme":
        return filme(a, video, nome, dur, dur_final, tem_audio, (cx, cy, cw, ch),
                     vel, ini, cor, vol, fase, espelho, tmpdir)
    if a.modelo == "meiatela":
        return meia_tela(a, video, nome, dur, dur_final, tem_audio, (cx, cy, cw, ch),
                         vel, ini, cor, vol, fase, espelho, tmpdir)

    z, T = a.zoom, a.intervalo
    # zoom suave: aproxima em T segundos, afasta nos T seguintes (vai e volta)
    if z > 0:
        p = f"mod(t,{T})/{T}"
        ease = f"(1-cos(PI*{p}))/2"
        fator = f"if(eq(mod(floor(t/{T})+{fase},2),1),1+{z}-{z}*{ease},1+{z}*{ease})"
        zoom_f = (f"scale=w='trunc({sw}*({fator})/2)*2':h='trunc({sh}*({fator})/2)*2':eval=frame:flags=bicubic,")
    else:
        zoom_f = ""
    if P:
        a1, a2 = random.uniform(4.5, 6.5), random.uniform(5.5, 8.0)
        mov = (f",crop={W}:{H}:'{P}+{P-2}*sin(2*PI*t/{a1:.2f})':'{P}+{P-2}*sin(2*PI*t/{a2:.2f}+1)'"
               f",noise=alls=4:allf=t")
    else:
        mov = ""
    usar_fade = (a.fade or a.template == "jota") and not a.sem_fade
    FD = 0.6
    fade_v = (f"fade=t=in:st=0:d={FD},fade=t=out:st={max(0, dur_final - FD - 0.05):.2f}:d={FD},"
              if usar_fade else "")
    fade_a = (f",afade=t=in:st=0:d={FD},afade=t=out:st={max(0, dur_final - FD - 0.05):.2f}:d={FD}"
              if usar_fade else "")
    filtro = (f"[1:v]setpts=(PTS-STARTPTS)/{vel},crop={cw}:{ch}:{cx}:{cy},{espelho}{cor}"
              f"scale={sw}:{sh}:flags=lanczos,{zoom_f}"
              f"crop={aw}:{ah}:'(iw-{aw})/2':'(ih-{ah})*0.3',{grao}setsar=1,fps=30[v];"
              f"[0:v][v]overlay={VX}:{VY}:shortest=1{mov},{a._sub}{fade_v}format=yuv420p[out]")
    if tem_audio and not a.previa:
        filtro += f";[1:a]asetpts=PTS-STARTPTS,atempo={vel},volume={vol}{fade_a}[a]"

    if a.previa:
        prev = os.path.splitext(nome)[0] + "_previa.jpg"
        rodar(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", fundo, "-ss", f"{min(dur/2, 3):.2f}", "-i", video,
               "-filter_complex", filtro, "-map", "[out]", "-frames:v", "1", prev])
        print(f"Previa salva em: {prev}")
        return

    print("Renderizando... (pode levar alguns minutos)")
    cmd = ["ffmpeg", "-v", "error", "-stats", "-y", "-loop", "1", "-i", fundo,
           "-ss", f"{ini}", "-i", video, "-filter_complex", filtro, "-map", "[out]"]
    if tem_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-r", "30",
            "-map_metadata", "-1", "-metadata", f"title={a.template}_{random.randint(10000, 99999)}",
            "-movflags", "+faststart", "-t", f"{dur_final:.3f}", nome]
    r = subprocess.run(cmd)
    if r.returncode != 0:
        sys.exit("Falhou ao renderizar.")
    print(f"\nPronto! Video salvo em:\n{nome}")
    # avisa a galeria do Android (se o termux-api estiver instalado)
    subprocess.run(["termux-media-scan", nome], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) \
        if shutil_which("termux-media-scan") else None


# ---------------------------------------------------------------- modelo MEIA TELA
NOMES_CANAL = {"naoconte": "Não Conte a Ninguém", "memudobr": "@mememudobr", "jota": "Jota TV", "memeclaude": "@memeclaudebr",
               "jotinha": "Jotinha_React", "driverush": "DriveRush",
               # canais de corte (meia tela)
               "cortehubs": "Corte Hubs", "cityflow": "City Flow", "cyberdefend": "Cyber Defend",
               "silencio": "Depois do Silêncio", "qgclipes": "QG Clipes", "vrumm": "Universo Vrumm",
               # canais de filme
               "thejota": "The Jota Cortes", "neoronios": "Neoronios Clips", "nexora": "Nexora Clips",
               "mentalista": "O Mentalista", "zenthaku": "Zenthaku", "madruga": "Meme Madruga", "memeverse": "MemeVerse",
               "kreekcraft": "Fan Club Kreekcraft"}
LOGOS = os.path.join(PASTA, "logos")
SEAM = 760  # onde termina a imagem de cima e comeca o video


def expr_zoom(sw, sh, z, T, fase):
    if z <= 0:
        return ""
    p = f"mod(t,{T})/{T}"
    ease = f"(1-cos(PI*{p}))/2"
    fator = f"if(eq(mod(floor(t/{T})+{fase},2),1),1+{z}-{z}*{ease},1+{z}*{ease})"
    return f"scale=w='trunc({sw}*({fator})/2)*2':h='trunc({sh}*({fator})/2)*2':eval=frame:flags=bicubic,"


def avatar_do_template(nome_tpl, tam):
    lg = os.path.join(LOGOS, nome_tpl + ".png")
    if os.path.exists(lg):
        return Image.open(lg).convert("RGBA").resize((tam, tam), Image.LANCZOS)
    tpl = Image.open(os.path.join(TEMPLATES, nome_tpl + ".png")).convert("RGB")
    av = tpl.crop((60, 72, 250, 262)).resize((tam * 4, tam * 4), Image.LANCZOS)
    m = Image.new("L", av.size, 0)
    ImageDraw.Draw(m).ellipse((4, 4, av.width - 4, av.height - 4), fill=255)
    av.putalpha(m)
    return av.resize((tam, tam), Image.LANCZOS)


def camada_meia_tela(headline, nome_tpl, cor_hex):
    """PNG transparente com a faixa da headline e a marca do canal."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fe = carregar_emoji()
    # marca do canal (canto superior esquerdo)
    av = avatar_do_template(nome_tpl, 74)
    fn = ImageFont.truetype(os.path.join(FONTES, "Poppins-Bold.ttf"), 32)
    nome = NOMES_CANAL.get(nome_tpl, nome_tpl)
    larg = 74 + 16 + int(d.textlength(nome, font=fn)) + 28
    d.rounded_rectangle((26, 26, 26 + larg, 26 + 74 + 12), radius=43, fill=(0, 0, 0, 150))
    img.paste(av, (32, 32), av)
    d.text((32 + 74 + 14, 26 + 22), nome, font=fn, fill="white")
    # faixa com a headline
    if headline:
        texto = " ".join(b.strip() for b in headline.split("|")).upper()
        for tam in (66, 62, 58, 54, 50, 46, 42):
            fonte = ImageFont.truetype(os.path.join(FONTES, "Poppins-Bold.ttf"), tam)
            linhas = []
            atual = ""
            for p in texto.split():
                t = (atual + " " + p).strip()
                if largura(d, t, fonte, fe, tam) <= 930:
                    atual = t
                else:
                    linhas.append(atual)
                    atual = p
            linhas.append(atual)
            if len(linhas) <= 3:
                break
        lh = int(tam * 1.12)
        alt = lh * len(linhas) + 34
        larg_txt = max(largura(d, l, fonte, fe, tam) for l in linhas)
        bw = min(W - 50, int(larg_txt) + 70)
        x1, y2 = (W - bw) // 2, SEAM + 30
        y1 = y2 - alt
        cor = tuple(int(cor_hex.strip("#")[i:i + 2], 16) for i in (0, 2, 4))
        d.rectangle((x1 + 6, y1 + 8, x1 + bw + 6, y2 + 8), fill=(0, 0, 0, 120))  # sombra
        d.rectangle((x1, y1, x1 + bw, y2), fill=cor + (255,), outline=(0, 0, 0, 255), width=3)
        y = y1 + 14
        for ln in linhas:
            x = (W - largura(d, ln, fonte, fe, tam)) / 2
            for tipo, s_ in pedacos(ln):
                if tipo == "t":
                    d.text((x, y), s_, font=fonte, fill="white", stroke_width=5, stroke_fill="black")
                    x += d.textlength(s_, font=fonte)
                else:
                    e = img_emoji(fe, s_, tam)
                    if e:
                        img.paste(e, (int(x), int(y + tam * 0.18)), e)
                        x += e.width
            y += lh
    return img


def achar_ultima_imagem():
    imgs = [f for ext in ("jpg", "jpeg", "png", "webp", "JPG", "PNG")
            for f in glob.glob(os.path.join(DOWNLOAD, f"*.{ext}"))]
    if not imgs:
        sys.exit(f"Nenhuma imagem em {DOWNLOAD}")
    return max(imgs, key=os.path.getmtime)


def escolher_quadro(video, cena, dur, tmpdir):
    """Escolhe o quadro que mais chama atencao: momento de pico de audio (grito, risada,
    reacao), imagem nitida, com contraste e cor fortes. Evita o comeco e o final."""
    import array
    from PIL import ImageFilter, ImageStat
    cx, cy, cw, ch = cena
    # 1) energia do audio a cada 0,25s
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    amostras = array.array("h", r.stdout[: len(r.stdout) // 2 * 2])
    jan = 2000
    energia = []
    for i in range(0, len(amostras) - jan, jan):
        bloco = amostras[i:i + jan:4]
        energia.append(sum(abs(v) for v in bloco) / max(1, len(bloco)))
    ini_ok, fim_ok = dur * 0.12, dur * 0.88
    cand = []
    if energia:
        ordem = sorted(range(len(energia)), key=lambda k: energia[k], reverse=True)
        for k in ordem:
            t = k * 0.25 + 0.12
            if ini_ok <= t <= fim_ok and all(abs(t - c) > 1.0 for c in cand):
                cand.append(t)
            if len(cand) >= 5:
                break
    for f in (0.3, 0.5, 0.7):  # mais alguns pontos espalhados
        cand.append(dur * f)
    # 2) nota visual de cada candidato
    melhor, nota_max = None, -1
    emax = max(energia) if energia else 1
    for i, t in enumerate(cand):
        fr = os.path.join(tmpdir, f"cand{i}.png")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", video, "-frames:v", "1",
                        "-vf", f"crop={cw}:{ch}:{cx}:{cy}", fr], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if not os.path.exists(fr):
            continue
        im = Image.open(fr).convert("RGB")
        peq = im.resize((240, max(1, int(240 * im.height / im.width))))
        nitidez = ImageStat.Stat(peq.convert("L").filter(ImageFilter.FIND_EDGES)).mean[0]
        contraste = ImageStat.Stat(peq.convert("L")).stddev[0]
        rr, gg, bb = [ImageStat.Stat(c).mean[0] for c in peq.split()]
        cor = (abs(rr - gg) + abs(gg - bb) + abs(rr - bb)) / 3
        k = int((t - 0.12) / 0.25)
        audio = energia[k] / emax if energia and 0 <= k < len(energia) else 0.3
        nota = nitidez * 1.5 + contraste * 0.6 + cor * 0.5 + audio * 40
        if nota > nota_max:
            melhor, nota_max = (im, t), nota
    if melhor is None:
        return None, 0
    return melhor


def meia_tela(a, video, nome, dur, dur_final, tem_audio, cena, vel, ini, cor, vol, fase, espelho, tmpdir):
    cx, cy, cw, ch = cena
    camada = os.path.join(tmpdir, "camada.png")
    camada_meia_tela(a.headline, a.template.lower(), a.cor_faixa).save(camada)

    # imagem de cima
    if a.imagem:
        topo = achar_ultima_imagem() if a.imagem == "ultima" else os.path.expanduser(a.imagem)
        if not os.path.exists(topo):
            sys.exit(f"Imagem nao encontrada: {topo}")
        ti = Image.open(topo).convert("RGB")
    else:
        print("Escolhendo o quadro de maior impacto para a imagem de cima...")
        ti, t_q = escolher_quadro(video, cena, dur, tmpdir)
        if ti is None:
            fr = os.path.join(tmpdir, "quadro.png")
            rodar(["ffmpeg", "-v", "error", "-y", "-ss", f"{dur * 0.35:.2f}", "-i", video, "-frames:v", "1",
                   "-vf", f"crop={cw}:{ch}:{cx}:{cy}", fr])
            ti = Image.open(fr).convert("RGB")
        else:
            print(f"Quadro escolhido: {t_q:.1f}s")
        # da um "punch" na imagem: mais contraste, cor e uma vinheta escura nas bordas
        from PIL import ImageEnhance
        ti = ImageEnhance.Contrast(ImageEnhance.Color(ti).enhance(1.25)).enhance(1.15)
    topo_png = os.path.join(tmpdir, "topo.png")
    th = SEAM + 40
    e = max(W / ti.width, th / ti.height)
    ti = ti.resize((int(ti.width * e) + 2, int(ti.height * e) + 2), Image.LANCZOS)
    ti = ti.crop(((ti.width - W) // 2, int((ti.height - th) * 0.12), (ti.width - W) // 2 + W,
                  int((ti.height - th) * 0.12) + th))
    vin = Image.new("L", ti.size, 0)
    dv = ImageDraw.Draw(vin)
    for i in range(40):
        dv.rectangle((i * 3, i * 3, ti.width - i * 3, ti.height - i * 3), outline=int(110 * (1 - i / 40)))
    ti = Image.composite(Image.new("RGB", ti.size, "black"), ti, vin)
    ti.save(topo_png)

    # video de baixo
    vh_ = H - SEAM
    esc = max(W / cw, vh_ / ch) * 1.01
    sw, sh = int(cw * esc) // 2 * 2 + 2, int(ch * esc) // 2 * 2 + 2
    zoom_f = expr_zoom(sw, sh, a.zoom, a.intervalo, fase)
    D = max(dur_final, 1)
    kb = f"trunc({W}*(1+0.10*t/{D:.2f})/2)*2"   # imagem de cima aproxima devagar o video todo
    kbh = f"trunc({th}*(1+0.10*t/{D:.2f})/2)*2"
    filtro = (f"[2:v]scale=w='{kb}':h='{kbh}':eval=frame,crop={W}:{th}:'(iw-{W})/2':'(ih-{th})/2',fps=30[top];"
              f"[1:v]setpts=(PTS-STARTPTS)/{vel},crop={cw}:{ch}:{cx}:{cy},{espelho}{cor}"
              f"scale={sw}:{sh}:flags=lanczos,{zoom_f}"
              f"crop={W}:{vh_}:'(iw-{W})/2':'(ih-{vh_})*0.3',setsar=1,fps=30[v];"
              f"color=c=black:s={W}x{H}:r=30[bg];[bg][top]overlay=0:0[a1];[a1][v]overlay=0:{SEAM}[a2];"
              f"[a2][0:v]overlay=0:0,noise=alls=3:allf=t,{a._sub}format=yuv420p[out]")
    if tem_audio and not a.previa:
        filtro += f";[1:a]asetpts=PTS-STARTPTS,atempo={vel},volume={vol}[a]"

    if a.previa:
        prev = os.path.splitext(nome)[0] + "_previa.jpg"
        rodar(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", camada, "-ss", f"{min(dur / 2, 3):.2f}",
               "-i", video, "-loop", "1", "-i", topo_png, "-filter_complex", filtro, "-map", "[out]",
               "-frames:v", "1", prev])
        print(f"Previa salva em: {prev}")
        return
    print("Renderizando meia tela... (pode levar alguns minutos)")
    cmd = ["ffmpeg", "-v", "error", "-stats", "-y", "-loop", "1", "-i", camada, "-ss", f"{ini}", "-i", video,
           "-loop", "1", "-i", topo_png, "-filter_complex", filtro, "-map", "[out]"]
    if tem_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-r", "30", "-map_metadata", "-1",
            "-metadata", f"title={a.template}_mt_{random.randint(10000, 99999)}",
            "-movflags", "+faststart", "-t", f"{dur_final:.3f}", nome]
    if subprocess.run(cmd).returncode != 0:
        sys.exit("Falhou ao renderizar.")
    print(f"\nPronto! Video salvo em:\n{nome}")
    if shutil_which("termux-media-scan"):
        subprocess.run(["termux-media-scan", nome], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- modelo FILME
def texto_centro(img, d, linhas, fonte, fe, tam, y, lh, cor="white", contorno=5):
    for ln in linhas:
        x = (W - largura(d, ln, fonte, fe, tam)) / 2
        for tipo, s_ in pedacos(ln):
            if tipo == "t":
                d.text((x, y), s_, font=fonte, fill=cor, stroke_width=contorno, stroke_fill="black")
                x += d.textlength(s_, font=fonte)
            else:
                e = img_emoji(fe, s_, tam)
                if e:
                    img.paste(e, (int(x), int(y + tam * 0.18)), e)
                    x += e.width
        y += lh
    return y


def camada_filme(a, vy, vh_box):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fe = carregar_emoji()
    # marca do canal centralizada no topo
    av = avatar_do_template(a.template, 96)
    fn = ImageFont.truetype(os.path.join(FONTES, "Poppins-Bold.ttf"), 40)
    nome = NOMES_CANAL.get(a.template, a.template)
    larg = 96 + 18 + int(d.textlength(nome, font=fn)) + 34
    x0 = (W - larg) // 2
    d.rounded_rectangle((x0, 70, x0 + larg, 70 + 110), radius=55, fill=(0, 0, 0, 160))
    img.paste(av, (x0 + 7, 77), av)
    d.text((x0 + 7 + 96 + 16, 70 + 30), nome, font=fn, fill="white")
    # headline
    if a.headline:
        blocos = [b.strip() for b in a.headline.split("|") if b.strip()]
        y_top, y_bot = 210, vy - 30
        for tam in (64, 60, 56, 52, 48, 44, 40):
            fonte = ImageFont.truetype(os.path.join(FONTES, "Poppins-Bold.ttf"), tam)
            todas = [quebrar(d, b, fonte, fe, tam) for b in blocos]
            lh = int(tam * 1.2)
            alt = sum(len(l) for l in todas) * lh + 20 * (len(todas) - 1)
            if alt <= y_bot - y_top:
                break
        y = y_top + (y_bot - y_top - alt) // 2
        for i, l in enumerate(todas):
            y = texto_centro(img, d, l, fonte, fe, tam, y + (20 if i else 0), lh)
    # etiqueta "Parte X"
    yb = vy + vh_box + 45
    if a.parte:
        fp = ImageFont.truetype(os.path.join(FONTES, "Poppins-Bold.ttf"), 52)
        tw = d.textlength(a.parte.upper(), font=fp)
        d.rounded_rectangle(((W - tw) / 2 - 36, yb, (W + tw) / 2 + 36, yb + 84), radius=42, fill=(255, 196, 0, 255))
        d.text(((W - tw) / 2, yb + 10), a.parte.upper(), font=fp, fill="black")
        yb += 120
    rod = a.rodape if a.rodape != "Já segue aí pra não perder os próximos 🤣🤣" else "Segue pra ver a próxima parte 🎬"
    if rod:
        fr = ImageFont.truetype(os.path.join(FONTES, "Poppins-Bold.ttf"), 40)
        texto_centro(img, d, [rod], fr, fe, 44, yb + 10, 50, contorno=4)
    return img


def filme(a, video, nome, dur, dur_final, tem_audio, cena, vel, ini, cor, vol, fase, espelho, tmpdir):
    cx, cy, cw, ch = cena
    vh_box = min(int(W * ch / cw) // 2 * 2, 1100)       # video na largura toda (16:9 ~ 608px)
    vy = max(560, (980 - vh_box // 2) // 2 * 2)
    camada = os.path.join(tmpdir, "camada.png")
    camada_filme(a, vy, vh_box).save(camada)
    if a._sub:
        ass = a._sub.split("filename='")[1].split("'")[0]
        txt = open(ass, encoding="utf-8").read()
        mv = H - (vy + vh_box) + 40
        txt = re.sub(r"(Style: Leg,[^\n]*?,)(\d+)(,1\s*$)", lambda m: m.group(1) + str(mv) + m.group(3), txt, flags=re.M)
        open(ass, "w", encoding="utf-8").write(txt)
    esc = max(W / cw, vh_box / ch) * 1.01
    sw, sh = int(cw * esc) // 2 * 2 + 2, int(ch * esc) // 2 * 2 + 2
    zoom_f = expr_zoom(sw, sh, min(a.zoom, 0.05), a.intervalo, fase)
    # fundo = o proprio video, ampliado, desfocado e escurecido (sem borda e sempre em movimento)
    be = max(270 / cw, 480 / ch)
    bw, bh = int(cw * be) // 2 * 2 + 2, int(ch * be) // 2 * 2 + 2
    filtro = (f"[1:v]setpts=(PTS-STARTPTS)/{vel},crop={cw}:{ch}:{cx}:{cy},{espelho}fps=30,split[f1][f2];"
              f"[f1]scale={bw}:{bh},crop=270:480,boxblur=10:2,eq=brightness=-0.22:saturation=1.2,"
              f"scale={W}:{H}:flags=bicubic,setsar=1[bg];"
              f"[f2]{cor}scale={sw}:{sh}:flags=lanczos,{zoom_f}"
              f"crop={W}:{vh_box}:'(iw-{W})/2':'(ih-{vh_box})/2',setsar=1[v];"
              f"[bg][v]overlay=0:{vy}[x];[x][0:v]overlay=0:0,noise=alls=3:allf=t,{a._sub}format=yuv420p[out]")
    if tem_audio and not a.previa:
        if sons:
            filtro += f";[1:a]asetpts=PTS-STARTPTS,atempo={vel},volume={vol}[a0]"
            rot = ["[a0]"]
            for k, (t0, som) in enumerate(sons):
                wav = os.path.join(tmpdir, f"som_{som}.wav")
                if not os.path.exists(wav):
                    _som_wav(som, wav)
                idx = sum(1 for x in entradas if x == "-i")
                entradas += ["-i", wav]
                ms = int(t0 * 1000)
                filtro += f";[{idx}:a]aformat=channel_layouts=stereo,adelay={ms}|{ms},volume=0.9[s{k}]"
                rot.append(f"[s{k}]")
            filtro += f";{''.join(rot)}amix=inputs={len(rot)}:duration=first:dropout_transition=0:normalize=0[a]"
        else:
            filtro += f";[1:a]asetpts=PTS-STARTPTS,atempo={vel},volume={vol}[a]"
    if a.previa:
        prev = os.path.splitext(nome)[0] + "_previa.jpg"
        rodar(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", camada, "-ss", f"{min(dur / 2, 3):.2f}",
               "-i", video, "-filter_complex", filtro, "-map", "[out]", "-frames:v", "1", prev])
        print(f"Previa salva em: {prev}")
        return
    print("Renderizando filme... (pode levar alguns minutos)")
    cmd = ["ffmpeg", "-v", "error", "-stats", "-y", "-loop", "1", "-i", camada, "-ss", f"{ini}", "-i", video,
           "-filter_complex", filtro, "-map", "[out]"]
    if tem_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-r", "30", "-map_metadata", "-1",
            "-metadata", f"title={a.template}_f_{random.randint(10000, 99999)}",
            "-movflags", "+faststart", "-t", f"{dur_final:.3f}", nome]
    if subprocess.run(cmd).returncode != 0:
        sys.exit("Falhou ao renderizar.")
    print(f"\nPronto! Video salvo em:\n{nome}")
    if shutil_which("termux-media-scan"):
        subprocess.run(["termux-media-scan", nome], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- LEGENDA ANIMADA
WHISPER_DIR = os.path.expanduser("~/whisper.cpp")


def achar_whisper():
    for b in ("build/bin/whisper-cli", "build/bin/main", "main"):
        p = os.path.join(WHISPER_DIR, b)
        if os.path.exists(p):
            exe = p
            break
    else:
        return None, None
    for m in ("ggml-small.bin", "ggml-base.bin", "ggml-small-q5_1.bin", "ggml-base-q5_1.bin", "ggml-tiny.bin"):
        mp = os.path.join(WHISPER_DIR, "models", m)
        if os.path.exists(mp):
            return exe, mp
    return exe, None


def _preset_dtw(modelo):
    n = os.path.basename(modelo).lower()
    for p in ("large-v3-turbo", "large-v3", "large-v2", "medium", "small", "base", "tiny"):
        if p in n:
            return p.replace("large-v3-turbo", "large.v3.turbo").replace("large-v", "large.v")
    return ""


def _palavras_dtw(arq_json):
    """le o JSON completo do whisper e monta as palavras com o tempo do DTW (alinhado ao audio)"""
    with open(arq_json, encoding="utf-8", errors="ignore") as f:
        js = json.load(f)
    toks = []
    for seg_ in js.get("transcription", []):
        for t in seg_.get("tokens", []):
            txt = t.get("text", "")
            if not txt or txt.startswith("[_") or txt.startswith("<|"):
                continue
            td = t.get("t_dtw", -1)
            ini = td / 100.0 if td is not None and td >= 0 else t.get("offsets", {}).get("from", 0) / 1000.0
            toks.append((ini, txt))
    palavras = []
    for ini, txt in toks:
        if palavras and not txt.startswith(" ") and palavras[-1][2]:
            palavras[-1] = (palavras[-1][0], palavras[-1][1], palavras[-1][2] + txt)  # pedaco da mesma palavra
        else:
            palavras.append((ini, ini, txt.strip()))
    out = []
    for i, (t0, _, w) in enumerate(palavras):
        w = w.strip()
        if not w or w.startswith("[") or w.startswith("("):
            continue
        if out and re.fullmatch(r"[\W_]+", w):
            out[-1] = (out[-1][0], out[-1][1], out[-1][2] + w)
            continue
        out.append([t0, t0 + 0.3, w])
    for i in range(len(out)):        # fim = inicio da proxima (max 1,2 s)
        prox = out[i + 1][0] if i + 1 < len(out) else out[i][0] + 0.6
        out[i][1] = max(out[i][0] + 0.08, min(prox, out[i][0] + 1.2))
    return [tuple(x) for x in out]


def transcrever(video, tmpdir, dica=""):
    exe, modelo = achar_whisper()
    if not exe or not modelo:
        sys.exit("Legenda precisa do whisper.cpp. Rode uma vez:  bash ~/editor_memes/instalar_legenda.sh")
    wav = os.path.join(tmpdir, "audio.wav")
    rodar(["ffmpeg", "-v", "error", "-y", "-i", video, "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", wav])
    print(f"Transcrevendo a fala ({os.path.basename(modelo)})... pode levar alguns minutos")
    base = os.path.join(tmpdir, "fala")
    threads = str(min(4, os.cpu_count() or 4))
    dica = re.sub(r"[*|]", " ", dica or "")
    dica = re.sub(r"[^\w\s,.!?áéíóúâêôãõçÁÉÍÓÚÂÊÔÃÕÇ-]", "", dica).strip()
    extra = ["--prompt", dica.capitalize()] if dica else []
    # 1) tempo de cada palavra alinhado ao audio (DTW): bem mais certo em video com musica de fundo
    preset = _preset_dtw(modelo)
    if preset:
        r = subprocess.run([exe, "-m", modelo, "-f", wav, "-l", IDIOMA, "-dtw", preset, "-ojf", "-of", base,
                            "-t", threads, "-np"] + extra, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if r.returncode == 0 and os.path.exists(base + ".json"):
            try:
                pal = _palavras_dtw(base + ".json")
                if pal:
                    print(f"Legenda: {len(pal)} palavras (tempo alinhado ao audio)")
                    return pal
            except Exception as e:  # noqa: BLE001
                print(f"Legenda: alinhamento falhou ({e}), usando o modo antigo")
    # 2) modo antigo (estimativa por palavra)
    r = subprocess.run([exe, "-m", modelo, "-f", wav, "-l", IDIOMA, "-ml", "1", "-sow", "-osrt", "-of", base,
                        "-t", threads, "-np"] + extra, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    srt = base + ".srt"
    if r.returncode != 0 or not os.path.exists(srt):
        sys.exit("Falhou a transcricao:\n" + (r.stderr or "")[-800:])
    return ler_srt(srt)


def ler_srt(caminho):
    def seg(t):
        h, m, rest = t.strip().replace(",", ".").split(":")
        return int(h) * 3600 + int(m) * 60 + float(rest)
    palavras = []
    blocos = open(caminho, encoding="utf-8", errors="ignore").read().strip().split("\n\n")
    for b in blocos:
        linhas = b.strip().split("\n")
        if len(linhas) < 3 or "-->" not in linhas[1]:
            continue
        t0, t1 = linhas[1].split("-->")
        w = " ".join(linhas[2:]).strip()
        if not w or w.startswith("[") or w.startswith("("):
            continue
        if palavras and re.fullmatch(r"[\W_]+", w):
            palavras[-1] = (palavras[-1][0], seg(t1), palavras[-1][2] + w)
            continue
        palavras.append((seg(t0), seg(t1), w))
    return palavras


def demo_palavras(dur):
    frase = ("Olha so como fica a legenda animada no seu video, palavra por palavra, "
             "com destaque e efeito de pulo").split()
    passo = min(0.38, max(0.2, dur / (len(frase) + 2)))
    return [(0.2 + i * passo, 0.2 + (i + 1) * passo, w) for i, w in enumerate(frase)]


def _t(x):
    x = max(0.0, x)
    return f"{int(x // 3600)}:{int(x % 3600 // 60):02d}:{x % 60:05.2f}"


def gerar_ass(palavras, saida, y_base, cor_hex):
    """Estilo TikTok pop: grupos de ate 3 palavras, grupo entra com 'pulo',
    palavra falada fica colorida e maior."""
    c = cor_hex.strip("#")
    destaque = f"&H00{c[4:6]}{c[2:4]}{c[0:2]}&"
    # agrupa
    grupos, atual = [], []
    for i, p in enumerate(palavras):
        if atual and (len(atual) >= 3 or p[0] - atual[-1][1] > 0.6
                      or len("".join(w for _, _, w in atual)) + len(p[2]) > 16):
            grupos.append(atual)
            atual = []
        atual.append(p)
        if re.search(r"[.!?,;:]$", p[2]):
            grupos.append(atual)
            atual = []
    if atual:
        grupos.append(atual)
    mv = H - y_base
    linhas = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "",
              "[V4+ Styles]",
              "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
              "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
              "Alignment, MarginL, MarginR, MarginV, Encoding",
              f"Style: Leg,Poppins,84,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,-1,0,0,0,100,100,1,0,1,7,4,2,60,60,{mv},1",
              "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for gi, g in enumerate(grupos):
        fim_grupo = g[-1][1] + 0.15
        if gi + 1 < len(grupos):
            fim_grupo = min(fim_grupo, grupos[gi + 1][0][0])
        for wi, (t0, t1, w) in enumerate(g):
            ini = t0 if wi else g[0][0]
            fim = g[wi + 1][0] if wi + 1 < len(g) else fim_grupo
            if fim <= ini:
                fim = ini + 0.12
            pop = r"{\fscx72\fscy72\t(0,110,\fscx106\fscy106)\t(110,180,\fscx100\fscy100)}" if wi == 0 else ""
            partes = []
            for wj, (_, _, w2) in enumerate(g):
                txt = re.sub(r"[{}\\]", "", w2.upper())
                if wj == wi:
                    partes.append(r"{\c" + destaque + r"\fscx112\fscy112}" + txt + r"{\c&H00FFFFFF&\fscx100\fscy100}")
                else:
                    partes.append(txt)
            linhas.append(f"Dialogue: 0,{_t(ini)},{_t(fim)},Leg,,0,0,0,,{pop}{' '.join(partes)}")
    open(saida, "w", encoding="utf-8").write("\n".join(linhas) + "\n")


# ---------------------------------------------------------------- MEIA TELA PRO (estilo corte de reality)
HANDLES = {"cortehubs": "@cortehubs", "cityflow": "@cityflowcorts", "vrumm": "@universovrumm"}


def energia_audio(video, passo=0.1):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", video, "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
                       stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    import array
    am = array.array("h", r.stdout[: len(r.stdout) // 2 * 2])
    j = int(8000 * passo)
    return [sum(abs(v) for v in am[i:i + j:8]) / max(1, len(am[i:i + j:8])) for i in range(0, len(am) - j, j)]


def achar_gancho(en, dur, passo=0.1, tam=4.5):
    """janela de ~4,5s com mais energia de fala/grito (entre 10% e 85% do video)"""
    n = int(tam / passo)
    melhor, best = None, -1
    for i in range(int(len(en) * 0.10), max(int(len(en) * 0.85) - n, int(len(en) * 0.10) + 1)):
        s_ = sum(en[i:i + n])
        if s_ > best:
            best, melhor = s_, i
    if melhor is None:
        return None
    return (melhor * passo, min(dur, melhor * passo + tam))


def achar_impactos(en, dur, passo=0.1):
    """picos fortes de audio (gritos, risadas, respostas), separados por 5s"""
    idx = sorted(range(len(en)), key=lambda k: en[k], reverse=True)
    out = []
    for k in idx:
        t = k * passo
        if 1.0 < t < dur - 1 and all(abs(t - o) > 5 for o in out):
            out.append(t)
        if len(out) >= max(2, int(dur / 7)):
            break
    return sorted(out)


def trilha_tensao(total, hook_d, impactos, corpo, saida_mus, saida_sfx):
    try:
        import numpy as np
    except ImportError:
        print("(sem numpy: seguindo sem trilha. Para ter trilha: pkg install python-numpy)")
        return False
    import wave
    SR = 44100; n = int(total * SR); tt = np.arange(n) / SR
    mus = np.zeros(n); sfx = np.zeros(n)

    def add(buf, sig, st):
        i = int(st * SR); j = min(n, i + len(sig))
        if 0 <= i < n:
            buf[i:j] += sig[:j - i]
    x = np.arange(int(0.6 * SR)) / SR
    kick = np.sin(2 * np.pi * (42 + 90 * np.exp(-x * 28)) * x) * np.exp(-x * 6)
    mus += (np.sin(2 * np.pi * 55 * tt) + 0.5 * np.sin(2 * np.pi * 65.4 * tt) + 0.4 * np.sin(2 * np.pi * 82.4 * tt)) \
        * 0.12 * (0.6 + 0.4 * np.sin(2 * np.pi * tt / 8))
    b = 60 / random.choice([90, 94, 96, 100]); k = 0; tb = hook_d
    hl = int(0.04 * SR)
    hat = np.random.randn(hl) * np.exp(-np.arange(hl) / SR * 90) * 0.08
    while tb < corpo:
        if k % 4 in (0, 2):
            add(mus, kick * 0.7, tb)
        if k % 2 == 1:
            add(mus, hat, tb)
        k += 1; tb += b / 2
    cl = int(0.03 * SR)
    clic = np.sin(2 * np.pi * 1800 * np.arange(cl) / SR) * np.exp(-np.arange(cl) / SR * 120) * 0.25
    for i in range(int(hook_d / 0.5)):
        add(mus, clic, i * 0.5)
    boom = np.sin(2 * np.pi * (36 + 70 * np.exp(-x * 18)) * x) * np.exp(-x * 5) * 0.9
    m_ = int(0.55 * SR)
    wh = np.convolve(np.random.randn(m_), np.ones(30) / 30, "same") * np.sin(np.pi * np.linspace(0, 1, m_)) ** 2 * 1.2
    if hook_d > 0:
        add(sfx, wh, hook_d - 0.4)
    for t0 in impactos:
        add(sfx, boom, t0)
    add(sfx, boom * 1.2, corpo)
    mus *= np.clip(tt / 0.5, 0, 1) * np.clip((total - tt) / 1.0, 0, 1)
    for nome_, arr in ((saida_mus, mus), (saida_sfx, sfx)):
        arr = arr / (np.max(np.abs(arr)) + 1e-9) * 0.9
        with wave.open(nome_, "w") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes((arr * 32767).astype(np.int16).tobytes())
    return True


def meia_tela_pro(a, video, nome, dur, tem_audio, cena, cor, ini, tmpdir):
    global SEAM
    cx, cy, cw, ch = cena
    dur = dur - ini
    # gancho
    en = energia_audio(video) if tem_audio else []
    if en and ini:
        en = en[int(ini / 0.1):]
    if a.sem_gancho or dur < 14:
        hk = None
    elif a.gancho:
        h0, h1 = [float(v) for v in a.gancho.replace(",", ".").split("-")]
        hk = (h0, h1)
    else:
        hk = achar_gancho(en, dur) if en else None
    hook_d = (hk[1] - hk[0]) if hk else 0.0
    corpo = hook_d + dur
    END = 2.2
    total = corpo + END
    if hk:
        print(f"Gancho: {hk[0]:.1f}s a {hk[1]:.1f}s do corte")
    # impactos
    imp_src = achar_impactos(en, dur) if en else []
    impactos = ([0.05, hook_d] if hk else [0.05]) + [hook_d + t for t in imp_src]
    envx = "min(1," + "+".join(f"between(t,{x:.2f},{x + 0.45:.2f})*(1-(t-{x:.2f})/0.45)" for x in impactos) + ")"
    # camada (marca + faixa)
    SEAM = 800
    camada = os.path.join(tmpdir, "camada.png")
    camada_meia_tela(a.headline, a.template, a.cor_faixa).save(camada)
    # imagem de cima
    if a.imagem:
        topo = achar_ultima_imagem() if a.imagem == "ultima" else os.path.expanduser(a.imagem)
        ti = Image.open(topo).convert("RGB")
    else:
        print("Escolhendo o quadro de maior impacto para a imagem de cima...")
        ti, _ = escolher_quadro(video, cena, dur, tmpdir)
    from PIL import ImageEnhance, ImageFilter
    ti = ImageEnhance.Contrast(ImageEnhance.Color(ti).enhance(1.2)).enhance(1.12)
    th = 840
    e = max(W / ti.width, th / ti.height)
    ti = ti.resize((int(ti.width * e) + 2, int(ti.height * e) + 2), Image.LANCZOS)
    ti = ti.crop(((ti.width - W) // 2, int((ti.height - th) * 0.12), (ti.width - W) // 2 + W,
                  int((ti.height - th) * 0.12) + th))
    topo_png = os.path.join(tmpdir, "topo.png"); ti.save(topo_png)
    # encerramento proprio
    fim = ti.resize((W, H)).filter(ImageFilter.GaussianBlur(30))
    fim = Image.blend(fim, Image.new("RGB", (W, H), "black"), 0.6)
    d = ImageDraw.Draw(fim)
    lg = avatar_do_template(a.template, 360); fim.paste(lg, ((W - 360) // 2, 520), lg)
    corf = tuple(int(a.cor_faixa.strip("#")[i:i + 2], 16) for i in (0, 2, 4))
    nome_c = NOMES_CANAL.get(a.template, a.template)
    handle = HANDLES.get(a.template, nome_c)

    def ct(t, f, y, fill="white", sw=6):
        w = d.textlength(t, font=f)
        d.text(((W - w) / 2, y), t, font=f, fill=fill, stroke_width=sw, stroke_fill="black")
    fb = os.path.join(FONTES, "Poppins-Bold.ttf")
    ct(nome_c.upper(), ImageFont.truetype(fb, 100), 920, (255, 255, 255))
    ct(a.texto_fim.upper(), ImageFont.truetype(fb, 74), 1080, corf)
    ct(f"Segue {handle} pra ver o resto", ImageFont.truetype(fb, 46), 1200, sw=4)
    fim_png = os.path.join(tmpdir, "fim.png"); fim.save(fim_png)
    # caixa do video: deitado -> inteiro com fundo desfocado; em pe -> preenche
    deitado = cw / ch > 1.15
    if deitado:
        VH, VY = 760, 880
        VW = int(cw * VH / ch) // 2 * 2
        leg_y = 1775
    else:
        VH, VY = H - 800, 800
        VW = W
        leg_y = 1700
    # legenda
    sub = ""
    if a.legenda:
        pal = transcrever(video, tmpdir, a.headline)
        pal = [(t0 - ini, t1 - ini, w) for t0, t1, w in pal if t0 >= ini]
        final = []
        if hk:
            final += [(t0 - hk[0], t1 - hk[0], w) for t0, t1, w in pal if hk[0] - 0.05 <= t0 < hk[1]]
        final += [(t0 + hook_d, t1 + hook_d, w) for t0, t1, w in pal]
        if final:
            ass = os.path.join(tmpdir, "leg.ass"); gerar_ass(final, ass, leg_y, a.legenda_cor or "ffe600")
            sub = f"subtitles=filename='{ass}':fontsdir='{FONTES}',"
            print(f"Legenda: {len(final)} palavras")
    # trilha
    mus = os.path.join(tmpdir, "mus.wav"); sfx = os.path.join(tmpdir, "sfx.wav")
    tem_trilha = (not a.sem_musica) and trilha_tensao(total, hook_d, impactos[1 if hk else 0:], corpo, mus, sfx)
    # ---------- video
    largura_v = f"trunc({VW}*(1.02+0.14*({envx}))/2)*2" if deitado else f"trunc({max(VW, int(cw * VH / ch))}*1.02*(1+0.14*({envx}))/2)*2"
    altura_v = f"trunc({VH}*(1.02+0.14*({envx}))/2)*2" if deitado else f"trunc({max(VH, int(ch * W / cw))}*1.02*(1+0.14*({envx}))/2)*2"
    cw_out = min(VW, W)
    # reduz videos grandes (ex: 1920x1080) logo no inicio: muito mais leve no celular
    alt_max = 820 if deitado else 1240
    if ch > alt_max:
        reduz = f",scale=-2:{alt_max}"
    else:
        reduz = ""
    # o gancho e lido como uma entrada separada do mesmo arquivo (entrada 4):
    # assim nada fica guardado na memoria (antes o celular fechava por falta de RAM)
    vin = f"[1:v]trim=start={ini:.2f},setpts=PTS-STARTPTS,crop={cw}:{ch}:{cx}:{cy}{reduz},fps=30"
    if hk:
        vin = (f"[4:v]setpts=PTS-STARTPTS,crop={cw}:{ch}:{cx}:{cy}{reduz},fps=30,trim=0:{hook_d:.2f}[vh];"
               f"{vin}[vbb];[vh][vbb]concat=n=2:v=1:a=0")
    fc = (f"{vin},{cor}split=2[v1][v2];"
          f"[v1]scale=360:-2,boxblur=12:2,eq=brightness=-0.25,scale={W}:{H - 800},setsar=1[blur];"
          f"[v2]scale=w='{largura_v}':h='{altura_v}':eval=frame,"
          f"crop={cw_out}:{VH}:'(iw-{cw_out})/2+10*sin(t*70)*({envx})':'(ih-{VH})/2+10*cos(t*57)*({envx})',"
          f"eq=brightness='0.35*({envx})*({envx})':eval=frame,setsar=1[v];"
          f"[2:v]scale=w='trunc({W}*(1+0.10*t/{corpo:.2f})/2)*2':h='trunc(840*(1+0.10*t/{corpo:.2f})/2)*2':eval=frame,"
          f"crop={W}:840,fps=30[top];"
          f"color=c=black:s={W}x{H}:r=30:d={corpo:.2f}[bg];[bg][top]overlay=0:0[x1];[x1][blur]overlay=0:800[x2];"
          f"[x2][v]overlay=(W-w)/2:{VY}[x3];[x3][0:v]overlay=0:0,noise=alls=3:allf=t,{sub}"
          f"drawbox=x=0:y={VY + VH}:w={W}:h=8:color=black@0.5:t=fill[x4];"
          f"color=c=0x{a.cor_faixa.strip('#')}:s={W}x8:r=30:d={corpo:.2f}[pb];"
          f"[x4][pb]overlay=x='-{W}+{W}*t/{corpo:.2f}':y={VY + VH}:shortest=1,trim=0:{corpo:.2f},setpts=PTS-STARTPTS[corpo];"
          f"[3:v]scale=w='trunc({W}*(1+0.05*t/{END})/2)*2':h='trunc({H}*(1+0.05*t/{END})/2)*2':eval=frame,crop={W}:{H},"
          f"fade=t=in:st=0:d=0.2:color=white,fps=30,trim=0:{END},setpts=PTS-STARTPTS[fim];"
          f"[corpo][fim]concat=n=2:v=1:a=0,format=yuv420p[out]")
    entradas = ["-loop", "1", "-i", camada, "-i", video, "-loop", "1", "-i", topo_png, "-loop", "1", "-i", fim_png]
    if hk:
        entradas += ["-ss", f"{ini + hk[0]:.2f}", "-t", f"{hook_d + 0.2:.2f}", "-i", video]
    im_ = 5 if hk else 4  # indice da trilha
    if a.previa:
        prev = os.path.splitext(nome)[0] + "_previa.jpg"
        rodar(["ffmpeg", "-v", "error", "-y"] + entradas + ["-filter_complex", fc, "-map", "[out]",
               "-ss", f"{min(corpo / 2, 6):.2f}", "-frames:v", "1", prev])
        print(f"Previa salva em: {prev}")
        return
    # ---------- audio
    af = ""
    mapa_a = []
    if tem_audio:
        ain = f"[1:a]atrim=start={ini:.2f},asetpts=PTS-STARTPTS"
        if hk:
            ain = (f"[4:a]asetpts=PTS-STARTPTS,atrim=0:{hook_d:.2f}[ah];{ain}[abb];"
                   f"[ah][abb]concat=n=2:v=0:a=1")
        af = (f"{ain},highpass=f=80,equalizer=f=3000:t=q:w=1:g=3,acompressor=threshold=-20dB:ratio=3:makeup=3,"
              f"volume={random.uniform(0.95, 1.05):.2f},apad=whole_dur={total:.2f}")
        if tem_trilha:
            af += (f",asplit=2[fala][sc];[{im_}:a]volume=0.45[mu];[mu][sc]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300[duck];"
                   f"[{im_ + 1}:a]volume=0.7[fx];[fala][duck][fx]amix=inputs=3:duration=first:normalize=0")
        af += ",loudnorm=I=-14:TP=-1:LRA=9[au]"
    elif tem_trilha:
        af = f"[{im_}:a][{im_ + 1}:a]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1[au]"
    if af:
        fc += ";" + af
        mapa_a = ["-map", "[au]", "-c:a", "aac", "-b:a", "192k"]
    if tem_trilha:
        entradas += ["-i", mus, "-i", sfx]
    print("Renderizando corte pro... (pode levar alguns minutos)")
    cmd = (["ffmpeg", "-v", "error", "-stats", "-y", "-threads", "4", "-filter_complex_threads", "2"] + entradas + ["-filter_complex", fc, "-map", "[out]"] + mapa_a +
           ["-t", f"{total:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", "30",
            "-map_metadata", "-1", "-metadata", f"title={a.template}_pro_{random.randint(10000, 99999)}",
            "-movflags", "+faststart", nome])
    if subprocess.run(cmd).returncode != 0:
        sys.exit("Falhou ao renderizar.")
    print(f"\nPronto! Video salvo em:\n{nome}")
    if shutil_which("termux-media-scan"):
        subprocess.run(["termux-media-scan", nome], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------- modelo FOFOCA (Jota Explica)
CANAIS_FOFOCA = {"jotaexplica", "naoconte", "neoronios", "elisjusti", "nexora", "kreekcraft"}
# canais gringos: textos em ingles e legenda transcrita em ingles
INGLES = {"kreekcraft"}
# marca d'agua por cima do video (arquivo da pasta logos/)
MARCA_DAGUA = {"kreekcraft": "kreekcraft_wide.png"}
# canais em que a voz/rosto nao podem ser alterados (campanha): sem acelerar e sem espelhar
SEM_ALTERAR = {"elisjusti"}
# canais com filtro aprimorar + vivido ligado por padrao
APRIMORAR = {"jotaexplica", "nexora"}
# nome do canal no topo (linha branca, linha amarela) e @ embaixo
FOFOCA_MARCA = {"jotaexplica": ("JOTA", "EXPLICA", ""),
                "naoconte": ("NÃO CONTE", "A NINGUÉM", "@naoconteaninguemjs"),
                "neoronios": ("NEORONIOSZ", "CLIPS", "@neoronios.zclips"),
                "elisjusti": ("", "", "@elisjusti"),
                "nexora": ("NEXORA", "CLIPS", ""),
                "kreekcraft": ("", "", "@MisterCity-w7w")}
# cores de cada canal: destaque, selo (emoji, texto, cor), card, legenda (BGR do ASS)
TEMAS = {"padrao": dict(cor=(255, 196, 0), selo=("🚨", "FOFOCA", (150, 26, 26), (200, 60, 55)),
                        card=((28, 150, 40), (120, 240, 110)), leg="&H0000C4FF&", brilho=(58, 48, 26)),
         "neoronios": dict(cor=(0, 200, 235), selo=("🎬", "CLIPS", (10, 80, 150), (40, 170, 230)),
                           card=((10, 100, 180), (90, 210, 255)), leg="&H00EBC800&", brilho=(14, 44, 62)),
         "nexora": dict(cor=(168, 85, 255), selo=("🎮", "GAMES", (70, 24, 140), (168, 85, 255)),
                        card=((90, 40, 170), (200, 150, 255)), leg="&H00FF55A8&", brilho=(40, 18, 70)),
         "kreekcraft": dict(cor=(255, 214, 0), selo=("🎮", "CLIPS", (150, 18, 18), (235, 40, 40)),
                            card=((170, 20, 20), (255, 90, 90)), leg="&H0000D4FF&", brilho=(66, 14, 14)),
         "elisjusti": dict(cor=(214, 160, 122), selo=("🎤", "HISTÓRIA", (110, 62, 44), (214, 160, 122)),
                           card=((150, 92, 64), (236, 190, 156)), leg="&H007AA0D6&", brilho=(56, 38, 30))}
TEMA = TEMAS["padrao"]
FF_LINHA1, FF_LINHA2 = 640, 1603          # linhas amarelas (topo e base do video)
FF_VY, FF_VH = 648, 956                   # area do video
AMARELO = (255, 196, 0)


def _anton(t):
    return ImageFont.truetype(os.path.join(FONTES, "Anton-Regular.ttf"), t)


def _fundo_escuro(w, h):
    """fundo escuro com brilho dourado no centro (igual ao modelo do Jota Explica)."""
    import math
    g = Image.radial_gradient("L").resize((w, h), Image.BICUBIC)       # 0 no centro, 255 nas bordas
    centro = Image.new("RGB", (w, h), TEMA["brilho"])
    borda = Image.new("RGB", (w, h), (26, 26, 30))
    img = Image.composite(borda, centro, g)
    ruido = Image.effect_noise((w, h), 8).convert("RGB")
    return Image.blend(img, ruido, 0.04)


def _texto_cor(img, d, xy, partes, fonte, fe, tam, contorno=7):
    """desenha [(texto, cor)] com contorno preto e emojis coloridos."""
    x, y = xy
    for txt, cor in partes:
        for tipo, s in pedacos(txt):
            if tipo == "t":
                d.text((x, y), s, font=fonte, fill=cor, stroke_width=contorno, stroke_fill="black")
                x += d.textlength(s, font=fonte)
            else:
                e = img_emoji(fe, s, int(tam * 0.9))
                if e:
                    img.paste(e, (int(x), int(y + tam * 0.12)), e)
                    x += e.width
    return x


def _palavras_headline(headline):
    """*palavra* = amarela. Sem asteriscos, numeros/valores ficam amarelos sozinhos."""
    tem_marca = "*" in headline
    out = []
    for p in headline.replace("|", " | ").split():
        if p == "|":
            out.append(("|", False)); continue
        amarela = p.startswith("*") or p.endswith("*") or p.strip("*").endswith("*")
        limpo = p.replace("*", "").upper() if not EMOJI_RE.fullmatch(p) else p
        if not tem_marca:
            amarela = bool(re.search(r"\d|R\$|%", limpo))
        out.append((limpo, amarela))
    # asterisco que abre e fecha em palavras diferentes: *QUANTO COBRA*
    if tem_marca:
        dentro, res = False, []
        for p in headline.replace("|", " | ").split():
            if p == "|":
                res.append(("|", False)); continue
            abre, fecha = p.startswith("*"), p.endswith("*") and len(p) > 1
            if abre:
                dentro = True
            res.append((p.replace("*", "").upper() if not EMOJI_RE.fullmatch(p) else p, dentro))
            if fecha or (abre and p.count("*") == 2):
                dentro = False
        out = res
    return out


def _juntar_emoji(pal):
    out = []
    for p, am in pal:
        if out and p != "|" and EMOJI_RE.fullmatch(p) and out[-1][0] != "|":
            out[-1] = (out[-1][0] + " " + p, out[-1][1])
        else:
            out.append((p, am))
    return out


def camada_fofoca(a, PADD):
    AMARELO = TEMA["cor"]
    w, h = W + 2 * PADD, H + 2 * PADD
    img = _fundo_escuro(w, h)
    base = Image.new("RGB", (W, H))
    base.paste(img.crop((PADD, PADD, PADD + W, PADD + H)))
    d = ImageDraw.Draw(base)
    fe = carregar_emoji()
    # logo + JOTA EXPLICA
    wide = os.path.join(LOGOS, a.template + "_wide.png")
    if os.path.exists(wide):
        lw = Image.open(wide).convert("RGBA")
        lh_ = 130; lww = int(lw.width * lh_ / lw.height)
        if lww > 520:
            lww = 520; lh_ = int(lw.height * lww / lw.width)
        lw = lw.resize((lww, lh_), Image.LANCZOS)
        base.paste(lw, (60, 85), lw)
    else:
        lg = avatar_do_template(a.template, 160)
        base.paste(lg, (60, 75), lg)
    l1, l2, arroba = FOFOCA_MARCA.get(a.template, (NOMES_CANAL.get(a.template, a.template).upper(), "", ""))
    d.text((242, 96), l1, font=_anton(60), fill="white", stroke_width=3, stroke_fill="black")
    d.text((242, 158), l2, font=_anton(60), fill=AMARELO, stroke_width=3, stroke_fill="black")
    # selo FOFOCA (vermelho, levemente inclinado)
    extra = os.path.join(LOGOS, a.logo_extra + "_wide.png") if a.logo_extra else ""
    emo, selo_pad, cs1, cs2 = TEMA["selo"]
    selo = (a.selo or selo_pad).upper()
    fs = _anton(62)
    tw = int(d.textlength(selo, font=fs))
    sw_, sh_ = tw + 190, 124
    s = Image.new("RGBA", (sw_ + 20, sh_ + 20), (0, 0, 0, 0))
    sd = ImageDraw.Draw(s)
    sd.rounded_rectangle((14, 16, sw_ + 14, sh_ + 16), 16, fill=(0, 0, 0, 150))
    sd.rounded_rectangle((6, 6, sw_ + 6, sh_ + 6), 16, fill=cs1, outline=cs2, width=4)
    e = img_emoji(fe, emo, 74)
    if e:
        s.paste(e, (34, 26), e)
    sd.text((130, 24), selo, font=fs, fill=(205, 205, 205))
    s = s.rotate(-2, expand=True, resample=Image.BICUBIC)
    if extra and os.path.exists(extra):   # logo da campanha no lugar do selo
        lw = Image.open(extra).convert("RGBA")
        lh_ = 190; lww = int(lw.width * lh_ / lw.height)
        if lww > 500:
            lww = 500; lh_ = int(lw.height * lww / lw.width)
        lw = lw.resize((lww, lh_), Image.LANCZOS)
        base.paste(lw, (W - 40 - lww, 150 - lh_ // 2), lw)
    else:
        base.paste(s, (W - s.width - 40, 82), s)
    # headline
    if a.headline:
        pal = _juntar_emoji(_palavras_headline(a.headline))
        for tam in (98, 92, 86, 80, 76, 72, 68, 64):
            fn = _anton(tam)
            linhas, atual, larg_at = [], [], 0
            for p, am in pal:
                if p == "|":
                    if atual:
                        linhas.append(atual); atual, larg_at = [], 0
                    continue
                lp = largura(d, p, fn, fe, tam) + d.textlength(" ", font=fn)
                if atual and larg_at + lp > 900:
                    linhas.append(atual); atual, larg_at = [], 0
                atual.append((p, am)); larg_at += lp
            if atual:
                linhas.append(atual)
            lh = int(tam * 1.06)
            n_exp = a.headline.count("|") + 1 if "|" in a.headline else 0
            if len(linhas) * lh <= 360 and (not n_exp or len(linhas) <= n_exp or tam <= 64):
                break
        y = 270 + (360 - len(linhas) * lh) // 2
        for ln in linhas:
            txt = " ".join(p for p, _ in ln)
            x = (W - largura(d, txt, fn, fe, tam)) / 2
            partes = []
            for i, (p, am) in enumerate(ln):
                partes.append((p + (" " if i < len(ln) - 1 else ""), AMARELO if am else "white"))
            _texto_cor(base, d, (x, y), partes, fn, fe, tam)
            y += lh
    # linhas amarelas + janela do video
    d.rectangle((0, FF_LINHA1, W, FF_LINHA1 + 7), fill=AMARELO)
    d.rectangle((0, FF_VY, W, FF_VY + FF_VH), fill="black")
    d.rectangle((0, FF_LINHA2, W, FF_LINHA2 + 7), fill=AMARELO)
    # fonte
    if a.fonte:
        ff = _anton(46)
        t = (("SOURCE: " if a.template in INGLES else "FONTE: ") + a.fonte).upper()
        tw = d.textlength(t, font=ff)
        if tw > 980:
            ff = _anton(int(46 * 980 / tw)); tw = d.textlength(t, font=ff)
        d.text(((W - tw) / 2, 1650), t, font=ff, fill=(212, 206, 196))
    if arroba:
        fa = _anton(44)
        tw = d.textlength(arroba, font=fa)
        d.text(((W - tw) / 2, 1745), arroba, font=fa, fill=AMARELO)
    img.paste(base, (PADD, PADD))
    return img


def foto_png(caminho, saida, rotulo=""):
    """foto em moldura com a cor do canal + nome embaixo"""
    fw, fh = 430, 640
    im = Image.open(caminho).convert("RGB")
    esc = max(fw / im.width, fh / im.height)
    im = im.resize((int(im.width * esc) + 1, int(im.height * esc) + 1), Image.LANCZOS)
    im = im.crop(((im.width - fw) // 2, 0, (im.width - fw) // 2 + fw, fh))
    B = 10; extra = 70 if rotulo else 0
    c = Image.new("RGBA", (fw + 2 * B + 16, fh + 2 * B + extra + 16), (0, 0, 0, 0))
    d = ImageDraw.Draw(c)
    d.rounded_rectangle((14, 16, fw + 2 * B + 14, fh + 2 * B + extra + 14), 26, fill=(0, 0, 0, 140))
    d.rounded_rectangle((0, 0, fw + 2 * B, fh + 2 * B + extra), 26, fill=TEMA["cor"])
    m = Image.new("L", (fw, fh), 0); ImageDraw.Draw(m).rounded_rectangle((0, 0, fw, fh), 18, fill=255)
    c.paste(im, (B, B), m)
    if rotulo:
        fn = _anton(46); tw = d.textlength(rotulo, font=fn)
        d.text(((fw + 2 * B - tw) / 2, fh + 2 * B + 2), rotulo, font=fn, fill=(20, 20, 24))
    c.save(saida)
    return c.size


def card_png(texto, saida):
    """card verde estilo 'R$ 190 MIL 💸'"""
    fe = carregar_emoji()
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    tam = 96
    while True:
        fn = _anton(tam)
        tw = int(largura(tmp, texto.upper(), fn, fe, tam))
        if tw <= 860 or tam <= 50:
            break
        tam -= 4
    cw_, ch_ = tw + 90, 170
    c = Image.new("RGBA", (cw_ + 30, ch_ + 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(c)
    d.rounded_rectangle((16, 18, cw_ + 16, ch_ + 18), 26, fill=(0, 0, 0, 140))
    d.rounded_rectangle((6, 6, cw_ + 6, ch_ + 6), 26, fill=TEMA["card"][0], outline=TEMA["card"][1], width=7)
    _texto_cor(c, d, (51, 22 + (96 - tam) // 2), [(texto.upper(), "white")], fn, fe, tam, contorno=5)
    c = c.rotate(3, expand=True, resample=Image.BICUBIC)
    c.save(saida)
    return c.size


def gerar_ass_salto(palavras, saida, y, cor=""):
    """Legenda Salto de Cor: Anton, branco; palavra falada pula (pop) em amarelo;
    numeros/valores em vermelho."""
    AM, VM = TEMA["leg"], "&H003B3BFF&"
    if cor and re.fullmatch(r"#?[0-9a-fA-F]{6}", cor):
        c = cor.lstrip("#"); AM = f"&H00{c[4:6]}{c[2:4]}{c[0:2]}&".upper()
    grupos, atual = [], []
    for p in palavras:
        if atual and (len(atual) >= 3 or p[0] - atual[-1][1] > 0.6):
            grupos.append(atual); atual = []
        atual.append(p)
        if re.search(r"[.!?,;:]$", p[2]):
            grupos.append(atual); atual = []
    if atual:
        grupos.append(atual)
    L = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2", "",
         "[V4+ Styles]",
         "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
         "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
         "MarginR, MarginV, Encoding",
         "Style: S,Anton,106,&H00FFFFFF,&H00FFFFFF,&H00000000,&H66000000,0,0,0,0,100,100,1,0,1,9,5,5,60,60,0,1",
         "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for gi, g in enumerate(grupos):
        fim_g = g[-1][1] + 0.25
        if gi + 1 < len(grupos):
            fim_g = min(fim_g, grupos[gi + 1][0][0])
        for k, (t0, t1, w) in enumerate(g):
            ini = t0 if k else g[0][0]
            fim = g[k + 1][0] if k + 1 < len(g) else fim_g
            if fim <= ini:
                fim = ini + 0.12
            partes = []
            for j, (_, _, w2) in enumerate(g[:k + 1]):
                txt = re.sub(r"[{}\\]", "", w2.upper())
                num = bool(re.search(r"\d|R\$|%", txt))
                if j == k:
                    cor = VM if num else AM
                    volta = "" if num else r"\t(200,260,\1c&H00FFFFFF&)"
                    partes.append(r"{\1c" + cor + r"\fscx100\fscy100\t(0,90,\fscx118\fscy118)\t(90,180,\fscx100\fscy100)"
                                  + volta + "}" + txt)
                else:
                    partes.append(r"{\1c" + (VM if num else "&H00FFFFFF&") + r"\fscx100\fscy100}" + txt)
            L.append(f"Dialogue: 0,{_t(ini)},{_t(fim)},S,,0,0,0,,{{\\pos(540,{y})}}" + " ".join(partes))
    open(saida, "w", encoding="utf-8").write("\n".join(L) + "\n")



# ---------------------------------------------------------------- MODELO COLAGEM
# 2 imagens em cima + titulo escrito a mao + faixa colorida com a headline + video embaixo
def _cor_hex(h, padrao):
    h = (h or "").strip().lstrip("#")
    try:
        return tuple(int(h[k:k + 2], 16) for k in (0, 2, 4))
    except Exception:
        return padrao


def _achar_img(nome):
    if not nome:
        return None
    if os.path.exists(nome):
        return nome
    for ext in (".jpg", ".jpeg", ".png", ".webp", ""):
        c = os.path.join(PASTA, "fotos", nome + ext)
        if os.path.exists(c):
            return c
    print(f"AVISO: imagem {nome} nao encontrada")
    return None


def _cobrir(caminho, w, h):
    im = Image.open(caminho).convert("RGB")
    r = max(w / im.width, h / im.height)
    im = im.resize((max(w, round(im.width * r)), max(h, round(im.height * r))), Image.LANCZOS)
    x = (im.width - w) // 2
    y = max(0, int((im.height - h) * 0.25))   # rosto costuma ficar mais em cima
    return im.crop((x, y, x + w, y + h))


def camada_colagem(a, P):
    from PIL import ImageFilter
    TOPO = 760
    cf = _cor_hex(a.cor_faixa, (255, 79, 184))
    ct = _cor_hex(a.cor_titulo, (79, 227, 255))
    base = Image.new("RGB", (W, H), (12, 12, 14))
    imgs = [c for c in (_achar_img(a.img1), _achar_img(a.img2)) if c]
    if len(imgs) == 1:
        base.paste(_cobrir(imgs[0], W, TOPO), (0, 0))
    elif len(imgs) == 2:
        base.paste(_cobrir(imgs[0], W // 2, TOPO), (0, 0))
        base.paste(_cobrir(imgs[1], W // 2, TOPO), (W // 2, 0))
    else:   # sem imagem: degrade na cor da faixa
        for y in range(TOPO):
            k = 0.18 + 0.25 * (1 - y / TOPO)
            ImageDraw.Draw(base).line([(0, y), (W, y)], fill=tuple(int(c * k) for c in cf))
    d = ImageDraw.Draw(base)
    # titulo escrito a mao em cima das imagens
    if a.titulo:
        fp = os.path.join(FONTES, "Pacifico-Regular.ttf")
        tam = 140
        while tam > 60:
            f = ImageFont.truetype(fp, tam)
            if d.textlength(a.titulo, font=f) <= W - 80:
                break
            tam -= 6
        sombra = Image.new("RGBA", (W, 300), (0, 0, 0, 0))
        ImageDraw.Draw(sombra).text((44, 24), a.titulo, font=f, fill=(0, 0, 0, 170))
        base.paste(sombra.filter(ImageFilter.GaussianBlur(6)), (0, 0), sombra.filter(ImageFilter.GaussianBlur(6)))
        d.text((38, 14), a.titulo, font=f, fill=ct, stroke_width=7, stroke_fill=(255, 255, 255))
    # faixa colorida com a headline (palavra entre *asteriscos* sai em amarelo)
    texto = re.sub(r"\s+", " ", (a.headline or "").replace("|", " ")).strip()
    linhas, fonte = [], None
    if texto:
        fa = os.path.join(FONTES, "Anton-Regular.ttf")
        palavras = texto.upper().split()
        for tam in range(66, 34, -4):
            fonte = ImageFont.truetype(fa, tam)
            linhas, atual = [], ""
            for p_ in palavras:
                t = (atual + " " + p_).strip()
                if d.textlength(t.replace("*", ""), font=fonte) <= W - 110:
                    atual = t
                else:
                    linhas.append(atual); atual = p_
            linhas.append(atual)
            if len(linhas) <= 3:
                break
    lh = int(fonte.size * 1.16) if fonte else 0
    faixa_h = (len(linhas) * lh + 34) if linhas else 26
    camada = Image.new("RGBA", (W, faixa_h), cf + (255,))
    dc = ImageDraw.Draw(camada)
    y = 17
    for ln in linhas:
        partes = re.split(r"(\*[^*]+\*)", ln)
        larg = sum(dc.textlength(x.replace("*", "") + "", font=fonte) for x in partes)
        x = (W - larg) / 2
        for x_ in partes:
            if not x_:
                continue
            dest = x_.startswith("*")
            t = x_.strip("*")
            dc.text((x, y), t, font=fonte, fill=(255, 212, 0) if dest else (255, 255, 255),
                    stroke_width=5, stroke_fill=(0, 0, 0))
            x += dc.textlength(t, font=fonte)
        y += lh
    # inclina um pouco o texto da faixa (letra de impacto)
    camada = camada.transform(camada.size, Image.AFFINE, (1, 0.12, -faixa_h * 0.06, 0, 1, 0), Image.BICUBIC,
                              fillcolor=cf + (255,))
    base.paste(camada.convert("RGB"), (0, TOPO))
    vy = TOPO + faixa_h
    vh = (H - vy) // 2 * 2
    # moldura extra (o quadro balanca um pouco no anti-duplicidade)
    tela = base.resize((W + 2 * P, H + 2 * P), Image.LANCZOS) if P else base.copy()
    tela.paste(base, (P, P))
    return tela, vy, vh

# ---------------------------------------------------------------- MODELO B-ROLL
# video em cima + faixa da headline no meio (cor livre) + imagens de b-roll embaixo, com som em cada troca
BR_VH = 900   # altura do video em cima


def _faixa_headline(a, cf, inclinar=False, tam_max=66):
    d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    texto = re.sub(r"\s+", " ", (a.headline or "").replace("|", " ")).strip()
    linhas, fonte = [], None
    if texto:
        fa = os.path.join(FONTES, "Anton-Regular.ttf")
        palavras = texto.upper().split()
        for tam in range(tam_max, 34, -4):
            fonte = ImageFont.truetype(fa, tam)
            linhas, atual = [], ""
            for p_ in palavras:
                t = (atual + " " + p_).strip()
                if d.textlength(t.replace("*", ""), font=fonte) <= W - 110:
                    atual = t
                else:
                    linhas.append(atual); atual = p_
            linhas.append(atual)
            if len(linhas) <= 3:
                break
    lh = int(fonte.size * 1.16) if fonte else 0
    faixa_h = (len(linhas) * lh + 34) if linhas else 26
    camada = Image.new("RGBA", (W, faixa_h), cf + (255,))
    dc = ImageDraw.Draw(camada)
    y = 17
    for ln in linhas:
        partes = re.split(r"(\*[^*]+\*)", ln)
        larg = sum(dc.textlength(x.replace("*", ""), font=fonte) for x in partes)
        x = (W - larg) / 2
        for x_ in partes:
            if not x_:
                continue
            t = x_.strip("*")
            dc.text((x, y), t, font=fonte, fill=(255, 212, 0) if x_.startswith("*") else (255, 255, 255),
                    stroke_width=5, stroke_fill=(0, 0, 0))
            x += dc.textlength(t, font=fonte)
        y += lh
    if inclinar:
        camada = camada.transform(camada.size, Image.AFFINE, (1, 0.12, -faixa_h * 0.06, 0, 1, 0), Image.BICUBIC,
                                  fillcolor=cf + (255,))
    return camada.convert("RGB")


def camada_broll(a, P):
    cf = _cor_hex(a.cor_faixa, (229, 9, 20))
    base = Image.new("RGB", (W, H), (12, 12, 14))
    faixa = _faixa_headline(a, cf, tam_max=58)
    by = BR_VH + faixa.height                    # comeco da area do b-roll
    bh = H - by
    fundo_img = _achar_img(a.img1)
    if fundo_img:
        base.paste(_cobrir(fundo_img, W, bh), (0, by))
    else:   # sem imagem de fundo: degrade escuro na cor da faixa
        d = ImageDraw.Draw(base)
        for y in range(bh):
            k = 0.10 + 0.22 * (y / bh)
            d.line([(0, by + y), (W, by + y)], fill=tuple(int(c * k) for c in cf))
    base.paste(faixa, (0, BR_VH))
    tela = base.resize((W + 2 * P, H + 2 * P), Image.LANCZOS) if P else base.copy()
    tela.paste(base, (P, P))
    return tela, by, bh


def _som_wav(tipo, caminho):
    """gera o efeito sonoro na hora (sem precisar de arquivo): clique, pop ou whoosh"""
    import math, struct, wave
    sr = 44100
    rnd = random.Random(7)
    if tipo == "pop":
        n = int(sr * 0.09)
        amos, fase = [], 0.0
        for i in range(n):
            t = i / sr
            f = 900 - 650 * (t / 0.09)
            fase += 2 * math.pi * f / sr
            amos.append(math.sin(fase) * math.exp(-t * 38) * 0.9)
    elif tipo == "whoosh":
        n = int(sr * 0.38)
        amos, lp = [], 0.0
        for i in range(n):
            t = i / n
            env = math.sin(math.pi * t) ** 2
            a_ = 0.04 + 0.3 * t                    # filtro abre durante o som
            lp += a_ * ((rnd.random() * 2 - 1) - lp)
            amos.append(lp * env * 2.2)
    else:   # clique de mouse/camera
        n = int(sr * 0.05)
        amos = []
        for i in range(n):
            t = i / sr
            ruido = (rnd.random() * 2 - 1) * math.exp(-t * 260)
            tique = math.sin(2 * math.pi * 2400 * t) * math.exp(-t * 120) * 0.6
            amos.append((ruido * 0.7 + tique) * 0.9)
    with wave.open(caminho, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, v)) * 30000)) for v in amos))


def _ler_brolls(a, dur_final):
    """--broll nome@3-6@som  ->  [(caminho, t0, t1, som)] em ordem; sem fim = ate o proximo"""
    itens = []
    for b in a.broll or []:
        partes = b.split("@")
        if len(partes) < 2:
            continue
        nome, tempo = partes[0], partes[1]
        som = partes[2] if len(partes) > 2 and partes[2] else a.som_broll
        cam = _achar_img(nome)
        if not cam:
            continue
        t0, _, t1 = tempo.partition("-")
        try:
            t0 = max(0.0, float(t0)); t1 = float(t1) if t1 else None
        except ValueError:
            continue
        itens.append([cam, t0, t1, som])
    itens.sort(key=lambda x: x[1])
    for k, it in enumerate(itens):
        if it[2] is None:
            it[2] = itens[k + 1][1] if k + 1 < len(itens) else dur_final
    return [tuple(x) for x in itens if x[2] > x[1]]


# ---------------------------------------------------------------- ENQUADRAR NO ROSTO
_DET = [None]


def _rostos_img(cv2, img):
    """rostos de uma imagem: [(cx, cy, largura)] de 0 a 1 (YuNet; se nao tiver, Haar)"""
    h, w = img.shape[:2]
    yunet = os.path.join(PASTA, "face_yunet.onnx")
    out = []
    if os.path.exists(yunet) and hasattr(cv2, "FaceDetectorYN"):
        if _DET[0] is None:
            _DET[0] = cv2.FaceDetectorYN.create(yunet, "", (w, h), 0.7)
        _DET[0].setInputSize((w, h))
        _, res = _DET[0].detect(img)
        for f in (res if res is not None else []):
            x, y, fw, fh = [float(v) for v in f[:4]]
            out.append(((x + fw / 2) / w, (y + fh / 2) / h, fw / w))
        return out
    try:
        casc = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))
        cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        for x, y, fw, fh in casc.detectMultiScale(cinza, 1.15, 5, minSize=(int(w * 0.06), int(w * 0.06))):
            out.append(((x + fw / 2) / w, (y + fh / 2) / h, fw / w))
    except Exception:
        pass
    return out


def seguir_rosto(video, ini, dur, cena, tmpdir):
    """acha o rosto principal ao longo do trecho: [(t, x, y)] de 0 a 1 dentro da cena, ou None"""
    try:
        import cv2
    except Exception:
        print("Enquadrar no rosto: OpenCV nao instalado (pkg install opencv-python). Usando o corte padrao.")
        return None
    cx, cy, cw, ch = cena
    n = max(4, min(45, int(dur / 0.8)))
    pasta = os.path.join(tmpdir, "rostos"); os.makedirs(pasta, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{ini}", "-t", f"{dur:.2f}", "-i", video, "-vf",
                    f"crop={cw}:{ch}:{cx}:{cy},fps={n / dur:.4f},scale=480:-2", os.path.join(pasta, "f_%03d.jpg")])
    fotos = sorted(glob.glob(os.path.join(pasta, "f_*.jpg")))
    if not fotos:
        return None
    pts = []
    for k, f in enumerate(fotos):
        img = cv2.imread(f)
        if img is None:
            continue
        fs = _rostos_img(cv2, img)
        if fs:
            x, y, w = max(fs, key=lambda r: r[2])     # o maior rosto = quem esta falando/aparecendo
            pts.append(((k + 0.5) * dur / len(fotos), x, y))
    if len(pts) < max(2, len(fotos) * 0.3):
        print(f"Enquadrar no rosto: rosto em {len(pts)} de {len(fotos)} quadros, usando o corte padrao")
        return None
    # suaviza (mediana de 3 + media movel) pra camera nao ficar tremendo
    def suave(v):
        m = [sorted(v[max(0, i - 1):i + 2])[len(v[max(0, i - 1):i + 2]) // 2] for i in range(len(v))]
        return [sum(m[max(0, i - 1):i + 2]) / len(m[max(0, i - 1):i + 2]) for i in range(len(m))]
    xs, ys = suave([p_[1] for p_ in pts]), suave([p_[2] for p_ in pts])
    print(f"Enquadrar no rosto: rosto achado em {len(pts)} de {len(fotos)} quadros")
    return [(pts[i][0], xs[i], ys[i]) for i in range(len(pts))]


def _expr_tempo(pontos):
    """interpolacao linear ao longo do tempo: [(t, valor)] -> expressao do ffmpeg"""
    if len(pontos) == 1:
        return f"{pontos[0][1]:.4f}"
    e = f"{pontos[-1][1]:.4f}"
    for i in range(len(pontos) - 2, -1, -1):
        (t0, v0), (t1, v1) = pontos[i], pontos[i + 1]
        dt = max(0.01, t1 - t0)
        e = f"if(lt(t,{t1:.2f}),{v0:.4f}+({v1 - v0:.4f})*(t-{t0:.2f})/{dt:.2f},{e})"
    return f"if(lt(t,{pontos[0][0]:.2f}),{pontos[0][1]:.4f},{e})"


def fofoca(a, video, nome, dur, dur_final, tem_audio, cena, vel, ini, cor, vol, fase, espelho, tmpdir):
    cx, cy, cw, ch = cena
    PADD = 0 if a.estatico else PAD
    fundo = os.path.join(tmpdir, "fofoca.png")
    VY, VH, LINHA, COR_BARRA = FF_VY, FF_VH, FF_LINHA2, (TEMA["cor"] if a.template in TEMAS else (224, 24, 24))
    if a.modelo == "colagem":
        img, VY, VH = camada_colagem(a, PADD)
        img.save(fundo)
        LINHA, COR_BARRA = H - 12, _cor_hex(a.cor_faixa, (255, 79, 184))
    elif a.modelo == "broll":
        img, BY, BH = camada_broll(a, PADD)
        img.save(fundo)
        VY, VH = 0, BR_VH
        LINHA, COR_BARRA = H - 12, _cor_hex(a.cor_faixa, (229, 9, 20))
    else:
        camada_fofoca(a, PADD).save(fundo)
    esc = max(W / cw, VH / ch) * 1.01
    sw, sh = int(cw * esc) // 2 * 2 + 2, int(ch * esc) // 2 * 2 + 2
    zoom_f = expr_zoom(sw, sh, min(a.zoom, 0.05), a.intervalo, fase)
    # video em pe: rosto fica em cima, entao recorta mais perto do topo
    fy = a.enquadrar if a.enquadrar is not None else (0.12 if ch > cw * 1.1 else 0.35)
    pos_x, pos_y = "(iw-%d)/2" % W, "(ih-%d)*%s" % (VH, fy)
    # enquadrar no rosto: acompanha o rosto principal (fica a uns 40%% da altura do quadro, livre da legenda)
    if a.enquadrar is None and not a.sem_rosto:
        trilha = seguir_rosto(video, ini, dur, cena, tmpdir)
        if trilha:
            espx = bool(espelho)
            ty = _expr_tempo([(t / vel, y) for t, x, y in trilha])
            tx = _expr_tempo([(t / vel, (1 - x) if espx else x) for t, x, y in trilha])
            pos_y = f"max(0,min(ih-{VH},({ty})*ih-{int(VH * 0.40)}))"
            pos_x = f"max(0,min(iw-{W},({tx})*iw-{W // 2}))"
    entradas = ["-loop", "1", "-i", fundo, "-ss", f"{ini}", "-i", video]
    # APRIMORAR (tira ruido + nitidez) e VIVIDO (cores vivas). Ligado por padrao no jotaexplica
    aprim = ""
    if not a.sem_aprimorar and a.template in APRIMORAR:
        aprim = ("hqdn3d=1.5:1.2:4:3,vibrance=intensity=0.12,"
                 "eq=contrast=1.07:saturation=1.03,")
    # "QUALIDADE 4K": nitidez de detalhe depois de ajustar o tamanho (efeito de imagem mais definida)
    detalhe = "cas=0.6,unsharp=3:3:0.45:3:3:0," if aprim else ""
    filtro = (f"[1:v]setpts=(PTS-STARTPTS)/{vel},crop={cw}:{ch}:{cx}:{cy},{espelho}{cor}{aprim}fps=30,"
              f"scale={sw}:{sh}:flags=lanczos,{zoom_f}crop={W}:{VH}:'{pos_x}':'{pos_y}',{detalhe}setsar=1[v];"
              f"[0:v][v]overlay={PADD}:{VY + PADD}:shortest=1[b0];"
              f"color=c=0x{'%02X%02X%02X' % COR_BARRA}:s={W}x10:r=30[pb];"
              f"[b0][pb]overlay=x='{PADD}-{W}+{W}*t/{dur_final:.3f}':y={LINHA + PADD}:shortest=1[b1];")
    ultimo = "b1"
    # marca d'agua do canal por cima do video (canto de baixo, meio transparente)
    if a.template in MARCA_DAGUA and os.path.exists(os.path.join(LOGOS, MARCA_DAGUA[a.template])):
        md = Image.open(os.path.join(LOGOS, MARCA_DAGUA[a.template])).convert("RGBA")
        mw = 330; md = md.resize((mw, max(2, int(md.height * mw / md.width))), Image.LANCZOS)
        md.putalpha(md.getchannel("A").point(lambda v: int(v * 0.55)))
        mpng = os.path.join(tmpdir, "marca.png"); md.save(mpng)
        idx = sum(1 for x in entradas if x == "-i")
        entradas += ["-loop", "1", "-i", mpng]
        filtro += f"[{ultimo}][{idx}:v]overlay=x={W - mw - 30 + PADD}:y={VY + VH - md.height - 40 + PADD}:shortest=1[md];"
        ultimo = "md"
    # cards verdes:  --card "R$ 190 MIL 💸@8.5"  (aparece em 8.5s por 3s)  ou  "texto@8.5-12"
    for i, c in enumerate(a.card or []):
        txt, _, tempo = c.rpartition("@")
        if not txt:
            continue
        t0, _, t1 = tempo.partition("-")
        t0 = float(t0); t1 = float(t1) if t1 else t0 + 3.0
        png = os.path.join(tmpdir, f"card{i}.png")
        cw_, ch_ = card_png(txt, png)
        entradas += ["-loop", "1", "-i", png]
        xc = min(W - cw_ - 30, max(30, int(W * 0.62 - cw_ / 2)))
        yb = VY + 40
        filtro += (f"[{ultimo}][{2 + i}:v]overlay=x={xc + PADD}:y='{yb + PADD}-40*max(0,1-(t-{t0})/0.18)'"
                   f":enable='between(t,{t0},{t1})':shortest=1[c{i}];")
        ultimo = f"c{i}"
    # fotos: --foto elis05@3-7  (nome da pasta fotos/ ou caminho de imagem)
    for i, fo in enumerate(a.foto or []):
        nome_f, _, tempo = fo.rpartition("@")
        if not nome_f:
            continue
        t0, _, t1 = tempo.partition("-")
        t0 = float(t0); t1 = float(t1) if t1 else t0 + 3.0
        cam = nome_f if os.path.exists(nome_f) else os.path.join(PASTA, "fotos", nome_f + ".jpg")
        if not os.path.exists(cam):
            print(f"AVISO: foto {nome_f} nao encontrada, pulando"); continue
        png = os.path.join(tmpdir, f"foto{i}.png")
        fw, fh = foto_png(cam, png, "ELIS JUSTI" if os.path.basename(cam).startswith("elis") else "")
        idx = sum(1 for x in entradas if x == "-i")
        entradas += ["-loop", "1", "-i", png]
        xf = W - fw - 30; yf = VY + (VH - fh) // 2
        filtro += (f"[{ultimo}][{idx}:v]overlay=x='{xf + PADD}+600*max(0,1-(t-{t0})/0.25)':y={yf + PADD}"
                   f":enable='between(t,{t0},{t1})':shortest=1[f{i}];")
        ultimo = f"f{i}"
    # b-roll: imagens embaixo, entrando com um "pulo" e um som em cada troca
    sons = []
    if a.modelo == "broll":
        for i, (cam, t0, t1, som) in enumerate(_ler_brolls(a, dur_final)):
            png = os.path.join(tmpdir, f"broll{i}.jpg")
            _cobrir(cam, W, BH).save(png, quality=92)
            idx = sum(1 for x in entradas if x == "-i")
            entradas += ["-loop", "1", "-i", png]
            filtro += (f"[{ultimo}][{idx}:v]overlay=x={PADD}:y='{BY + PADD}+70*max(0,1-(t-{t0:.2f})/0.16)'"
                       f":enable='between(t,{t0:.2f},{t1:.2f})':shortest=1[br{i}];")
            ultimo = f"br{i}"
            if som != "nenhum":
                sons.append((t0, som))
        print(f"B-roll: {len(_ler_brolls(a, dur_final))} imagem(ns), {len(sons)} som(ns)")
    sub = ""
    if a._sub:
        sub = a._sub
    mov = ""
    if PADD:
        a1, a2 = random.uniform(4.5, 6.5), random.uniform(5.5, 8.0)
        mov = (f"crop={W}:{H}:'{PADD}+{PADD-2}*sin(2*PI*t/{a1:.2f})':'{PADD}+{PADD-2}*sin(2*PI*t/{a2:.2f}+1)',"
               f"noise=alls=3:allf=t,")
    filtro += f"[{ultimo}]{mov}{sub}format=yuv420p[out]"
    if tem_audio and not a.previa:
        if sons:
            filtro += f";[1:a]asetpts=PTS-STARTPTS,atempo={vel},volume={vol}[a0]"
            rot = ["[a0]"]
            for k, (t0, som) in enumerate(sons):
                wav = os.path.join(tmpdir, f"som_{som}.wav")
                if not os.path.exists(wav):
                    _som_wav(som, wav)
                idx = sum(1 for x in entradas if x == "-i")
                entradas += ["-i", wav]
                ms = int(t0 * 1000)
                filtro += f";[{idx}:a]aformat=channel_layouts=stereo,adelay={ms}|{ms},volume=0.9[s{k}]"
                rot.append(f"[s{k}]")
            filtro += f";{''.join(rot)}amix=inputs={len(rot)}:duration=first:dropout_transition=0:normalize=0[a]"
        else:
            filtro += f";[1:a]asetpts=PTS-STARTPTS,atempo={vel},volume={vol}[a]"
    if a.previa:
        prev = os.path.splitext(nome)[0] + "_previa.jpg"
        rodar(["ffmpeg", "-v", "error", "-y"] + entradas[:4] + ["-ss", f"{min(dur / 2, 3):.2f}", "-i", video]
              + entradas[8:] + ["-filter_complex", filtro, "-map", "[out]", "-frames:v", "1", prev])
        print(f"Previa salva em: {prev}")
        return
    print(f"Renderizando {a.modelo}... (pode levar alguns minutos)")
    cmd = ["ffmpeg", "-v", "error", "-stats", "-y"] + entradas + ["-filter_complex", filtro, "-map", "[out]"]
    if tem_audio:
        cmd += ["-map", "[a]", "-c:a", "aac", "-b:a", "160k"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "18" if aprim else "21", "-r", "30", "-map_metadata", "-1",
            "-metadata", f"title={a.template}_ff_{random.randint(10000, 99999)}",
            "-movflags", "+faststart", "-t", f"{dur_final:.3f}", nome]
    if subprocess.run(cmd).returncode != 0:
        sys.exit("Falhou ao renderizar.")
    print(f"\nPronto! Video salvo em:\n{nome}")
    if shutil_which("termux-media-scan"):
        subprocess.run(["termux-media-scan", nome], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def shutil_which(c):
    from shutil import which
    return which(c)


if __name__ == "__main__":
    main()
