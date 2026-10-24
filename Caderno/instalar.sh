#!/usr/bin/env bash
# Instala o Nootebook como um programa do seu usuário (não precisa de sudo).
#
#   ./instalar.sh            instala ou atualiza (rode de novo depois de mudar o notebook.py)
#   ./instalar.sh --remover  remove o programa; seus cadernos continuam guardados
#
# O que ele faz:
#   - copia o programa para ~/.local/share/nootebook (com o próprio ambiente Python);
#   - cria o comando "nootebook" e o ícone no menu de aplicativos;
#   - deixa o servidor ligado sempre que você entra na sessão (serviço do systemd do usuário),
#     ouvindo só neste computador e no IP do Tailscale;
#   - traz os cadernos que já existem nesta pasta.

set -euo pipefail

SRC="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
APP="$DATA_HOME/nootebook"
BIN="$HOME/.local/bin"
LAUNCHER="$BIN/nootebook"
DESKTOP="$DATA_HOME/applications/nootebook.desktop"
ICON="$DATA_HOME/icons/hicolor/scalable/apps/nootebook.svg"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/nootebook.service"
PORT=8765

have() { command -v "$1" >/dev/null 2>&1; }
has_systemd() { have systemctl && systemctl --user show-environment >/dev/null 2>&1; }
refresh_menus() {
    have update-desktop-database && update-desktop-database "$DATA_HOME/applications" >/dev/null 2>&1 || true
    have gtk-update-icon-cache && gtk-update-icon-cache -q -t "$DATA_HOME/icons/hicolor" >/dev/null 2>&1 || true
}

if [ "${1:-}" = "--remover" ]; then
    if has_systemd; then
        systemctl --user disable --now nootebook.service >/dev/null 2>&1 || true
    fi
    pkill -f "$APP/nootebook.py" 2>/dev/null || true
    rm -f "$UNIT" "$LAUNCHER" "$DESKTOP" "$ICON"
    has_systemd && systemctl --user daemon-reload || true
    rm -rf "$APP/.notebook_venv" "$APP/janela" "$APP/nootebook.py" "$APP/servidor.log"
    refresh_menus
    echo "Nootebook removido. Seus cadernos continuam em $APP/notebook_data"
    exit 0
fi

PY="$(command -v python3 || true)"
if [ -z "$PY" ]; then
    echo "Python 3 não encontrado. Instale com: sudo apt install python3 python3-venv" >&2
    exit 1
fi

echo "Instalando o Nootebook em $APP ..."

# 1. para o que estiver usando a porta: o serviço (numa atualização) ou o caderno rodando desta pasta
if has_systemd; then systemctl --user stop nootebook.service >/dev/null 2>&1 || true; fi
if pgrep -f "$SRC/notebook.py" >/dev/null 2>&1; then
    echo "- Fechando o caderno que estava rodando desta pasta (ele passa a rodar como programa)"
    pkill -INT -f "$SRC/notebook.py" || true
    for _ in $(seq 50); do pgrep -f "$SRC/notebook.py" >/dev/null 2>&1 || break; sleep 0.1; done
    pkill -KILL -f "$SRC/notebook.py" 2>/dev/null || true
fi

# 2. programa e ambiente Python próprio
mkdir -p "$APP" "$BIN" "$(dirname "$DESKTOP")" "$(dirname "$ICON")" "$UNIT_DIR"
install -m 644 "$SRC/notebook.py" "$APP/nootebook.py"
install -m 644 "$SRC/nootebook.svg" "$ICON"
VPY="$APP/.notebook_venv/bin/python"
if ! "$VPY" -c "import flask" >/dev/null 2>&1; then
    echo "- Preparando o ambiente Python (só na primeira vez; precisa de internet)"
    rm -rf "$APP/.notebook_venv"
    if ! "$PY" -m venv "$APP/.notebook_venv"; then
        echo "Não consegui criar o ambiente. No Debian/Ubuntu: sudo apt install python3-venv" >&2
        exit 1
    fi
    "$VPY" -m pip install --disable-pip-version-check --quiet "flask>=2.2"
fi

# 3. cadernos que já existiam nesta pasta (cópia consistente do banco; o original fica onde está)
if [ ! -f "$APP/notebook_data/cadernos.db" ] && [ -f "$SRC/notebook_data/cadernos.db" ]; then
    echo "- Trazendo seus cadernos de $SRC/notebook_data"
    mkdir -p "$APP/notebook_data"
    "$PY" - "$SRC/notebook_data/cadernos.db" "$APP/notebook_data/cadernos.db" <<'PYEOF'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
src.backup(dst)
dst.close(); src.close()
PYEOF
fi

# 4. comando "nootebook": liga o servidor se preciso e abre numa janela própria
cat > "$LAUNCHER" <<EOF
#!/usr/bin/env bash
# Abre o Nootebook numa janela própria.  "nootebook --enderecos" mostra os endereços de acesso.
APP="$APP"
PORT=$PORT
URL="http://127.0.0.1:\$PORT/"
up() { "\$APP/.notebook_venv/bin/python" -c "import urllib.request; urllib.request.urlopen('\$URL', timeout=1)" >/dev/null 2>&1; }

if ! up; then
    if ! systemctl --user start nootebook.service >/dev/null 2>&1; then
        nohup "\$APP/.notebook_venv/bin/python" "\$APP/nootebook.py" --no-browser --strict-port --tailscale --port "\$PORT" \\
            >"\$APP/servidor.log" 2>&1 &
    fi
    for _ in \$(seq 60); do up && break; sleep 0.2; done
fi

if [ "\${1:-}" = "--enderecos" ]; then
    echo "Neste computador: \$URL"
    if command -v tailscale >/dev/null 2>&1 && TS=\$(tailscale ip -4 2>/dev/null | head -n1) && [ -n "\$TS" ]; then
        echo "Pelo Tailscale:   http://\$TS:\$PORT/"
    else
        echo "Tailscale desconectado."
    fi
    exit 0
fi

# janela de aplicativo (sem abas nem barra de endereço), com perfil separado do seu navegador
for b in google-chrome google-chrome-stable chromium chromium-browser brave-browser microsoft-edge; do
    if command -v "\$b" >/dev/null 2>&1; then
        exec "\$b" --app="\$URL" --class=Nootebook --user-data-dir="\$APP/janela" \\
            --no-first-run --no-default-browser-check --start-maximized >/dev/null 2>&1
    fi
done
# sem Chrome/Chromium nao ha janela de app (o Firefox nao tem esse modo): abre no navegador padrao
command -v notify-send >/dev/null 2>&1 && notify-send -i nootebook "Nootebook" \
    "Para abrir como app (janela própria), instale o Chromium ou o Google Chrome." || true
exec xdg-open "\$URL"
EOF
chmod 755 "$LAUNCHER"

# 5. ícone no menu de aplicativos
cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=Nootebook
GenericName=Caderno digital
Comment=Caderno pautado para escrever e desenhar
Exec=$LAUNCHER
Icon=nootebook
Terminal=false
Categories=Office;
Keywords=caderno;notas;anotações;desenho;notebook;
StartupWMClass=Nootebook
StartupNotify=true
EOF
refresh_menus

# 6. servidor sempre ligado na sessão (para abrir na hora e para os aparelhos do Tailscale)
if has_systemd; then
    cat > "$UNIT" <<EOF
[Unit]
Description=Nootebook - servidor do caderno digital
After=network-online.target

[Service]
ExecStart=$VPY $APP/nootebook.py --no-browser --strict-port --tailscale --port $PORT
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now nootebook.service >/dev/null 2>&1
    sleep 1
    if ! systemctl --user is-active --quiet nootebook.service; then
        echo "O servidor não iniciou. Veja o motivo com: journalctl --user -u nootebook -n 30" >&2
        exit 1
    fi
else
    echo "- systemd do usuário indisponível: o servidor liga quando você abrir o Nootebook."
fi

echo
echo "Pronto! O Nootebook está no menu de aplicativos."
case ":$PATH:" in *":$BIN:"*) echo "No terminal: nootebook   (ou: nootebook --enderecos)";;
                  *) echo "No terminal: $LAUNCHER";; esac
"$LAUNCHER" --enderecos
