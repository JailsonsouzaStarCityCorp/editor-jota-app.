"""Editor Jota no computador (Windows): liga o painel e o editar.py ao que existe no PC.

  - ffmpeg.exe / ffprobe.exe e whisper-cli.exe da pasta bin do programa (sem piscar console)
  - caminhos do Windows arrumados dentro dos filtros do ffmpeg
  - o editar.py roda dentro do proprio programa (o .exe nao tem python separado)
  - comandos do Termux (termux-media-scan, termux-open...) viram "nao faz nada"
"""
import io, os, re, runpy, subprocess, sys, threading

_run_original = subprocess.run
_popen_original = subprocess.Popen
_trava = threading.Lock()
_cancelar = [False]
_proc_atual = [None]
SEM_JANELA = 0x08000000 if os.name == "nt" else 0          # CREATE_NO_WINDOW

_DRIVE = re.compile(r"(?<![\\A-Za-z])([A-Za-z]):[\\/]((?:[^'\\:,;\[\]]|\\(?![:,;']))*)")


def _arruma_filtro(txt):
    """Dentro de um filtro do ffmpeg, 'C:\\pasta\\x.ass' quebra no ':'. Vira 'C\\:/pasta/x.ass'."""
    if os.name != "nt":
        return txt
    return _DRIVE.sub(lambda m: m.group(1) + "\\:/" + m.group(2).replace("\\", "/"), txt)


def _ajusta_args(args):
    out = list(args)
    for i, a in enumerate(out[:-1]):
        if a in ("-vf", "-af", "-filter_complex", "-lavfi", "-filter:v", "-filter:a"):
            out[i + 1] = _arruma_filtro(str(out[i + 1]))
    return out


def _sem_janela(kw):
    if SEM_JANELA and "creationflags" not in kw:
        kw["creationflags"] = SEM_JANELA
    return kw


def _nome(cmd):
    return os.path.splitext(os.path.basename(str(cmd[0])))[0].lower() if isinstance(cmd, (list, tuple)) and cmd else ""


def _run(cmd, *a, **kw):
    nome = _nome(cmd)
    if nome in ("ffmpeg", "ffprobe"):
        if _cancelar[0] and nome == "ffmpeg":
            return subprocess.CompletedProcess(cmd, 255, None, None)
        cmd = [cmd[0]] + _ajusta_args([str(x) for x in cmd[1:]])
    elif nome.startswith("termux-"):
        t = kw.get("text") or kw.get("universal_newlines")
        return subprocess.CompletedProcess(cmd, 0, "" if t else b"", "" if t else b"")
    return _run_original(cmd, *a, **_sem_janela(kw))


class _Escritor(io.TextIOBase):
    def __init__(self, fd):
        self.fd = fd

    def write(self, s):
        try:
            os.write(self.fd, s.encode("utf-8", "replace"))
        except OSError:
            pass
        return len(s)

    def flush(self):
        pass


class _ProcessoEditor:
    """roda o editar.py dentro do programa e entrega a saida como se fosse um processo"""
    def __init__(self, args, **kw):
        r, w = os.pipe()
        self.stdout = os.fdopen(r, "rb")
        self._w = w
        self.returncode = None
        self.pid = 0
        script = next(x for x in args if str(x).endswith("editar.py"))
        self._argv = [script] + [str(x) for x in args[args.index(script) + 1:]]
        self._t = threading.Thread(target=self._rodar, daemon=True)
        self._t.start()

    def _rodar(self):
        codigo = 0
        with _trava:
            _cancelar[0] = False
            esc = _Escritor(self._w)
            antigo = (sys.argv, sys.stdout, sys.stderr)
            sys.argv, sys.stdout, sys.stderr = self._argv, esc, esc
            try:
                runpy.run_path(self._argv[0], run_name="__main__")
            except SystemExit as e:
                if e.code not in (None, 0):
                    codigo = 1
                    if not isinstance(e.code, int):
                        esc.write(str(e.code) + "\n")
            except Exception as e:  # noqa: BLE001
                import traceback
                esc.write("ERRO: " + "".join(traceback.format_exception_only(type(e), e)))
                codigo = 1
            finally:
                sys.argv, sys.stdout, sys.stderr = antigo
                if _cancelar[0]:
                    codigo = -9
                self.returncode = codigo
                os.close(self._w)

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self._t.join(timeout)
        return self.returncode

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.wait()

    def communicate(self, input=None, timeout=None):
        d = self.stdout.read()
        self.wait()
        return d, None

    def kill(self):
        _cancelar[0] = True
        p = _proc_atual[0]
        if p is not None:
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass

    terminate = kill


class _PopenPC(_popen_original):
    def __init__(self, args, *a, **kw):
        if _nome(args) in ("ffmpeg", "ffprobe"):
            args = [args[0]] + _ajusta_args([str(x) for x in args[1:]])
        super().__init__(args, *a, **_sem_janela(kw))
        _proc_atual[0] = self


def _popen(args, *a, **kw):
    if isinstance(args, (list, tuple)) and any(str(x).endswith("editar.py") for x in args):
        return _ProcessoEditor(list(args), **kw)
    return _PopenPC(args, *a, **kw)


def instalar():
    subprocess.run = _run
    subprocess.Popen = _popen
