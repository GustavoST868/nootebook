#!/usr/bin/env bash
# Abre o Nootebook. Se ele estiver instalado (./instalar.sh), abre o programa instalado;
# senão, roda direto desta pasta, acessível neste computador e pelo Tailscale.
#
#   ./iniciar.sh                 abre neste computador e no IP Tailscale
#   ./iniciar.sh --no-browser    não abre o navegador
#   PORTA=9000 ./iniciar.sh      usa outra porta (padrão: 8765)
#
# O servidor ouve só em localhost e no IP Tailscale, então outros aparelhos
# da rede local (Wi-Fi) não conseguem abrir; só os da sua tailnet.

set -euo pipefail

# Se o Nootebook ja esta instalado, abre o programa (mesmos cadernos, janela de app).
# Rodar daqui criaria uma segunda copia com outro banco de dados.
LAUNCHER="$HOME/.local/bin/nootebook"
if [ -x "$LAUNCHER" ] && [ -f "${XDG_DATA_HOME:-$HOME/.local/share}/nootebook/nootebook.py" ]; then
    exec "$LAUNCHER"
fi

DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
PYTHON="$(command -v python3 || command -v python || true)"
if [ -z "$PYTHON" ]; then
    echo "Python 3 não encontrado. Instale com: sudo apt install python3 python3-venv" >&2
    exit 1
fi
if ! command -v tailscale >/dev/null 2>&1; then
    echo "Aviso: o Tailscale não está instalado; o caderno vai abrir só neste computador." >&2
fi

exec "$PYTHON" "$DIR/notebook.py" --tailscale --port "${PORTA:-8765}" "$@"
