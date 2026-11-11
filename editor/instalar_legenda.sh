#!/data/data/com.termux/files/usr/bin/bash
# Instala o whisper.cpp (reconhecimento de voz offline) para a legenda automatica.
# Uso: bash ~/editor_memes/instalar_legenda.sh          (modelo small - melhor qualidade)
#      bash ~/editor_memes/instalar_legenda.sh base     (modelo base - mais rapido)
set -e
MODELO="${1:-small}"
echo "== 1/4 Instalando ferramentas..."
pkg install -y git cmake clang make wget curl
echo "== 2/4 Baixando o whisper.cpp..."
if [ ! -d ~/whisper.cpp ]; then
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp ~/whisper.cpp
fi
cd ~/whisper.cpp
echo "== 3/4 Compilando (leva uns 5 a 10 minutos, deixe a tela ligada)..."
cmake -B build -DCMAKE_BUILD_TYPE=Release -DWHISPER_BUILD_TESTS=OFF -DWHISPER_BUILD_EXAMPLES=ON
cmake --build build -j4 --config Release --target whisper-cli
echo "== 4/4 Baixando o modelo de voz '$MODELO'..."
sh ./models/download-ggml-model.sh "$MODELO"
echo
if ffmpeg -hide_banner -filters 2>/dev/null | grep -q " subtitles "; then
  echo "OK! Legenda instalada. Use:  meme ultimo memudobr \"headline\" --legenda"
else
  echo "ATENCAO: seu ffmpeg nao tem suporte a legenda (libass). Rode: pkg install ffmpeg"
fi
