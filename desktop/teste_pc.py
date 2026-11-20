"""Teste da versao PC no Windows do GitHub: liga o editor, gera um video com legenda e testa o gravador."""
import json, os, shutil, subprocess, sys, time, urllib.request

PORTA = 8098
U = f"http://127.0.0.1:{PORTA}"
casa = os.path.expanduser("~")
os.makedirs(os.path.join(casa, "Downloads"), exist_ok=True)
shutil.copy("teste.mp4", os.path.join(casa, "Downloads", "teste.mp4"))
env = dict(os.environ, EDITOR_PORTA=str(PORTA))
alvo = sys.argv[1] if len(sys.argv) > 1 else None
cmd = [alvo, "--sem-janela"] if alvo else [sys.executable, "desktop/editorjota_pc.py", "--sem-janela"]
proc = subprocess.Popen(cmd, env=env)


def req(p, corpo=None):
    d = json.dumps(corpo).encode() if corpo is not None else None
    r = urllib.request.Request(U + p, data=d, method="POST" if d is not None else "GET")
    return json.loads(urllib.request.urlopen(r, timeout=120).read() or b"{}")


for _ in range(90):
    try:
        req("/api/tudo"); break
    except Exception:
        time.sleep(1)
d = req("/api/tudo")
print("pc:", d.get("pc"), "videos:", [v["nome"] for v in d["videos"]], "canais:", len(d["canais"]))
ok = True
for canal, modelo in (("jotaexplica", ""), ("qgclipes", "")):
    j = req("/api/render", {"video": "teste.mp4", "canal": canal, "headline": "TESTE NO *PC* DO EDITOR JOTA",
                            "inicio": 0, "fim": 7, "legenda": canal == "jotaexplica", "modelo": modelo})
    for _ in range(600):
        r = req("/api/job?id=" + j["id"])
        if r["status"] not in ("na fila", "rodando"):
            break
        time.sleep(2)
    print(canal, "->", r["status"], r.get("arquivo"))
    print("\n".join(r["log"][-8:]))
    ok = ok and r["status"] == "pronto"
g = req("/api/grav/iniciar", {"janela": "", "altura": 720}); print("gravador:", g)
time.sleep(8)
g = req("/api/grav/parar", {}); print("gravador parou:", g)
ok = ok and bool(g.get("partes")) and g["partes"][0]["mb"] > 0
proc.kill()
sys.exit(0 if ok else 1)
