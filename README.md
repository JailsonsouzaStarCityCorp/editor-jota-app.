# 🎬 Editor Jota

App Android pra editar cortes, memes e fofocas no padrão dos canais (Jota Explica, Jota TV, Memudobr, The Jota Cortes, O Mentalista, Nexora, Corte Hubs e outros), direto no celular.

## Baixar o app
➡️ **[Baixar EditorJota.apk](https://github.com/JailsonsouzaStarCityCorp/editor-jota-app./releases/latest/download/EditorJota.apk)**

## Primeira vez
1. Instale o **Termux** pela F-Droid (o app usa o Termux por trás pra fazer os vídeos).
2. Abra o app Editor Jota e siga a tela de configuração: ela copia o comando de instalação e abre o Termux.
3. Dê a permissão pedida. Pronto: depois disso é só abrir o app.

Instalar/atualizar só o editor (pelo Termux):
```
curl -sL https://github.com/JailsonsouzaStarCityCorp/editor-jota-app./raw/main/instalar.sh | bash
```

## O que tem
- **✂️ Editar** – vídeo, trecho com linha do tempo, ⭐ achar os momentos fortes, canal, headline, cards, foto, cor da legenda, campanha (regras e hashtags)
- **🎨 Filtros** – Aprimorar, Qualidade 4K, Vívido, brilho, contraste, quente, frio, cinema, P&B, vintage, vinheta, granulado
- **🎵 Áudio** – qualquer música do celular, volume, abaixar na fala
- **🪞 Espelhar**
- **📋 Fila** – vários vídeos em sequência, com conferência de qualidade (volume no padrão das redes, tela preta)

## Estrutura
- `editor/` – o editor (Python + ffmpeg): `editar.py` e o painel `painel.py`
- `android/` – o app (WebView em tela cheia que liga o painel pelo Termux)
- `instalar.sh` – instalador do editor no Termux
- `.github/workflows/apk.yml` – o GitHub monta e publica o APK a cada mudança
