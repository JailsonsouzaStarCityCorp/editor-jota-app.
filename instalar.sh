#!/data/data/com.termux/files/usr/bin/bash
# Instala / atualiza o Editor Jota no Termux.
# Uso:  curl -sL https://github.com/JailsonsouzaStarCityCorp/editor-jota-app./raw/main/instalar.sh | bash
REPO="https://github.com/JailsonsouzaStarCityCorp/editor-jota-app."
echo ""
echo "  🎬 Instalando o Editor Jota..."
echo ""
# pacotes (so instala o que faltar)
for p in python ffmpeg curl tar python-numpy python-pillow; do
  if ! dpkg -s "$p" >/dev/null 2>&1; then
    echo "  - instalando $p"
    pkg install -y "$p" >/dev/null 2>&1 || { pkg update -y >/dev/null 2>&1; pkg install -y "$p" >/dev/null 2>&1; }
  fi
done
python -c "import numpy, PIL" 2>/dev/null || pip install numpy pillow >/dev/null 2>&1
# OpenCV: usado pra enquadrar no rosto (se nao instalar, o editor usa o corte fixo)
python -c "import cv2" 2>/dev/null || { echo "  - instalando opencv (enquadrar no rosto)"; pkg install -y x11-repo >/dev/null 2>&1; pkg update -y >/dev/null 2>&1; pkg install -y opencv-python dbus >/dev/null 2>&1; }

# acesso aos arquivos do celular (Download, Memes_Prontos)
if [ ! -d ~/storage/shared ]; then
  echo "  - liberando acesso aos arquivos: toque em PERMITIR"
  termux-setup-storage; sleep 4
fi

# baixa a versao mais nova do editor (mantem suas fotos e musicas)
T=$(mktemp -d)
if ! curl -sL "$REPO/archive/refs/heads/main.tar.gz" | tar xz -C "$T"; then
  echo "  ERRO: nao consegui baixar o editor. Confira a internet e rode de novo."; exit 1
fi
mkdir -p ~/editor_memes
cp -r "$T"/*/editor/. ~/editor_memes/
rm -rf "$T"
mkdir -p ~/storage/shared/Memes_Prontos 2>/dev/null

# deixa o app Editor Jota ligar o editor sozinho
mkdir -p ~/.termux
if ! grep -q "^allow-external-apps *= *true" ~/.termux/termux.properties 2>/dev/null; then
  echo "allow-external-apps = true" >> ~/.termux/termux.properties
  termux-reload-settings 2>/dev/null
fi

# atalho pro widget do Termux (opcional)
mkdir -p ~/.shortcuts
echo 'python ~/editor_memes/painel.py' > ~/.shortcuts/Editor && chmod +x ~/.shortcuts/Editor

echo ""
echo "  ✅ Editor Jota instalado!"
echo "  Volte pro app Editor Jota e toque em 'Tentar de novo'."
echo "  (Sem o app: python ~/editor_memes/painel.py)"
echo ""
