#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Nootebook - um caderno pautado digital que roda no navegador.

Para instalar como programa (menu de aplicativos, janela propria, inicia com o login):

    ./instalar.sh

Ou rode direto:

    python notebook.py

Na primeira execucao o script:
  1. cria um ambiente virtual (.notebook_venv) ao lado deste arquivo;
  2. instala as dependencias (Flask) dentro dele;
  3. cria a pasta notebook_data/ com o banco de dados SQLite;
  4. inicia o servidor e abre o app no navegador.

Opcoes:
    --port 8765       porta do servidor (se estiver ocupada, usa a proxima livre)
    --host 127.0.0.1  endereco (use 0.0.0.0 para acessar de outros aparelhos da rede;
                      pode repetir: --host 127.0.0.1 --host 100.x.y.z)
    --tailscale       tambem aceita conexoes pelo IP do Tailscale (e espera ele ficar pronto)
    --strict-port     falha se a porta estiver ocupada, em vez de usar outra
    --no-browser      nao abre a janela do app automaticamente

Os dados ficam em notebook_data/ ao lado do script (ou na pasta de NOOTEBOOK_DATA).
"""

import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

if sys.version_info < (3, 8):
    sys.exit("O Nootebook precisa do Python 3.8 ou mais recente.")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

# --------------------------------------------------------------------------
# Configuracao
# --------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
VENV_DIR = BASE_DIR / ".notebook_venv"
DATA_DIR = Path(os.environ.get("NOOTEBOOK_DATA") or BASE_DIR / "notebook_data")
DB_PATH = DATA_DIR / "cadernos.db"
REQUIREMENTS = ["flask>=2.2"]

LINES_PER_PAGE = 22
DEFAULT_PAGES = 50
MAX_PAGES = 400
MAX_LINE_CHARS = 400
MAX_STROKE_BYTES = 200_000   # um traco/forma salvo como JSON
PAGE_OPTIONS = [20, 50, 100, 200]

PALETTE = [
    {"name": "Marinho", "hex": "#2c3a52"},
    {"name": "Grafite", "hex": "#3a3a3d"},
    {"name": "Bordô", "hex": "#6b2e35"},
    {"name": "Musgo", "hex": "#4d5a48"},
    {"name": "Terracota", "hex": "#a0634b"},
    {"name": "Névoa", "hex": "#8a96a3"},
    {"name": "Rosé", "hex": "#c9a9a1"},
    {"name": "Areia", "hex": "#d8cdb9"},
]

INKS = {
    "black": {"name": "preta", "hex": "#1c1c1f"},
    "blue": {"name": "azul", "hex": "#24408e"},
    "red": {"name": "vermelha", "hex": "#b02a2a"},
}

# tipos de letra do caderno: "gf" e o nome no Google Fonts, "size" o tamanho
# em relacao a altura da linha e "shift" um ajuste vertical para assentar na pauta
FONTS = {
    "caveat": {"name": "Manuscrita", "gf": "Caveat:wght@400;500", "css": "'Caveat',cursive", "size": 0.82, "shift": 0},
    "patrick": {"name": "Caneta", "gf": "Patrick Hand", "css": "'Patrick Hand',cursive", "size": 0.68, "shift": 0},
    "kalam": {"name": "Escolar", "gf": "Kalam:wght@300;400", "css": "'Kalam',cursive", "size": 0.6, "shift": 0},
    "indie": {"name": "Rabisco", "gf": "Indie Flower", "css": "'Indie Flower',cursive", "size": 0.66, "shift": 0},
    "shadows": {"name": "Lápis", "gf": "Shadows Into Light", "css": "'Shadows Into Light',cursive", "size": 0.7, "shift": 0},
    "dancing": {"name": "Cursiva", "gf": "Dancing Script:wght@400;500", "css": "'Dancing Script',cursive", "size": 0.74, "shift": 0},
    "lora": {"name": "Livro", "gf": "Lora:ital,wght@0,400;1,400", "css": "'Lora',Georgia,serif", "size": 0.62, "shift": 0},
    "inter": {"name": "Simples", "gf": "Inter:wght@400;500", "css": "'Inter',system-ui,sans-serif", "size": 0.58, "shift": 0},
    "courier": {"name": "Máquina", "gf": "Courier Prime", "css": "'Courier Prime','Courier New',monospace", "size": 0.62, "shift": 0},
}
DEFAULT_FONT = "caveat"
FONTS_URL = "https://fonts.googleapis.com/css2?" + "&".join(
    "family=" + gf.replace(" ", "+")
    for gf in ["Cormorant Garamond:ital,wght@0,400;0,500;1,400"] + [f["gf"] for f in FONTS.values()]
) + "&display=swap"

HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

# o Nootebook e um "app web instalavel": nome, icone e janela propria (sem abas nem barra de endereco)
ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256">
  <defs>
    <linearGradient id="cover" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#3a4a66"/>
      <stop offset="1" stop-color="#243049"/>
    </linearGradient>
    <linearGradient id="spine" x1="0" x2="1">
      <stop offset="0" stop-color="#000" stop-opacity=".28"/>
      <stop offset="1" stop-color="#000" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <!-- folhas aparecendo na lateral -->
  <rect x="58" y="30" width="160" height="200" rx="10" fill="#e9e5dc"/>
  <rect x="54" y="26" width="160" height="200" rx="10" fill="#f7f4ee"/>
  <!-- capa -->
  <rect x="40" y="22" width="166" height="208" rx="12" fill="url(#cover)"/>
  <rect x="40" y="22" width="30" height="208" rx="12" fill="url(#spine)"/>
  <rect x="62" y="22" width="3" height="208" fill="#fff" opacity=".12"/>
  <!-- etiqueta -->
  <rect x="92" y="70" width="88" height="54" rx="6" fill="#f7f4ee"/>
  <path d="M104 89h64M104 105h44" stroke="#8a96a3" stroke-width="5" stroke-linecap="round"/>
  <!-- elastico -->
  <rect x="182" y="22" width="9" height="208" fill="#1a2335" opacity=".85"/>
</svg>"""
MANIFEST = {
    "name": "Nootebook",
    "short_name": "Nootebook",
    "description": "Caderno pautado para escrever e desenhar",
    "lang": "pt-BR",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "background_color": "#f5f3ee",
    "theme_color": "#f5f3ee",
    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"}],
}
# navegadores com "modo app" (janela de aplicativo); o Firefox nao tem, entao fica de fora
APP_BROWSERS = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                "brave-browser", "microsoft-edge"]


# --------------------------------------------------------------------------
# Bootstrap: cria o venv, instala dependencias e reinicia dentro dele
# --------------------------------------------------------------------------
def _venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _running_in_venv() -> bool:
    try:
        return Path(sys.prefix).resolve() == VENV_DIR.resolve()
    except OSError:
        return False


def _quiet_ok(cmd) -> bool:
    try:
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except OSError:
        return False


def bootstrap() -> None:
    if os.environ.get("CADERNOS_BOOTSTRAPPED") == "1":
        sys.exit(
            "Não consegui iniciar dentro do ambiente virtual.\n"
            f"Apague a pasta '{VENV_DIR}' e rode o script de novo."
        )

    py = _venv_python()

    if py.exists() and not _quiet_ok([str(py), "-c", "import sys"]):
        print("- O ambiente virtual existente está quebrado; recriando...")
        shutil.rmtree(VENV_DIR, ignore_errors=True)

    if not py.exists():
        print(f"- Criando ambiente virtual em {VENV_DIR} ...")
        try:
            import venv

            venv.EnvBuilder(with_pip=True, clear=True).create(str(VENV_DIR))
        except Exception as exc:
            shutil.rmtree(VENV_DIR, ignore_errors=True)
            print(f"\nErro ao criar o ambiente virtual: {exc}")
            if sys.platform.startswith("linux"):
                print(
                    "Dica: no Debian/Ubuntu instale o suporte a venv com:\n"
                    "    sudo apt install python3-venv"
                )
            sys.exit(1)

    if not _quiet_ok([str(py), "-c", "import flask"]):
        print(f"- Instalando dependências ({', '.join(REQUIREMENTS)}). Isso só acontece na primeira vez...")
        cmd = [str(py), "-m", "pip", "install", "--disable-pip-version-check", "--quiet", *REQUIREMENTS]
        if subprocess.call(cmd) != 0:
            print(
                "\nNão foi possível instalar as dependências.\n"
                "Verifique sua conexão com a internet e tente novamente."
            )
            sys.exit(1)

    env = dict(os.environ, CADERNOS_BOOTSTRAPPED="1")
    args = [str(py), str(Path(__file__).resolve()), *sys.argv[1:]]
    sys.stdout.flush()
    if os.name == "nt":
        try:
            sys.exit(subprocess.call(args, env=env))
        except KeyboardInterrupt:
            sys.exit(0)
    os.execve(str(py), args, env)


# --------------------------------------------------------------------------
# Banco de dados
# --------------------------------------------------------------------------
SCHEMA = """
CREATE TABLE IF NOT EXISTS notebooks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    color       TEXT    NOT NULL,
    pages       INTEGER NOT NULL,
    font        TEXT    NOT NULL DEFAULT 'caveat',
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
CREATE TABLE IF NOT EXISTS lines (
    notebook_id INTEGER NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    page        INTEGER NOT NULL,
    line        INTEGER NOT NULL,
    text        TEXT    NOT NULL,
    ink         TEXT    NOT NULL DEFAULT 'blue',
    PRIMARY KEY (notebook_id, page, line)
);
CREATE TABLE IF NOT EXISTS strokes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    notebook_id INTEGER NOT NULL REFERENCES notebooks(id) ON DELETE CASCADE,
    page        INTEGER NOT NULL,
    ink         TEXT    NOT NULL DEFAULT 'blue',
    data        TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS strokes_by_page ON strokes (notebook_id, page);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _seed(conn) -> None:
    ts = _now()
    cur = conn.execute(
        "INSERT INTO notebooks (title, color, pages, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("Meu primeiro caderno", PALETTE[0]["hex"], DEFAULT_PAGES, ts, ts),
    )
    nid = cur.lastrowid
    lines = [
        (0, 0, "Bem-vindo ao seu caderno!", "red"),
        (0, 2, "Clique numa linha para escrever.", "blue"),
        (0, 3, "Enter desce para a linha de baixo.", "blue"),
        (0, 5, "Se a frase não couber, ela continua", "blue"),
        (0, 6, "sozinha na linha de baixo.", "blue"),
        (0, 8, "Para virar a página, arraste a folha", "blue"),
        (0, 9, "com o mouse no sentido em que ela vira.", "blue"),
        (0, 10, "Também dá com as setas ou os botões.", "blue"),
        (0, 12, "Escolha a letra e a cor da caneta", "black"),
        (0, 13, "lá em cima.", "black"),
        (0, 15, "Para desenhar, escolha a Caneta no", "blue"),
        (0, 16, "menu do canto (ou aperte D). Formas", "blue"),
        (0, 17, "tortas ficam retinhas sozinhas.", "blue"),
        (0, 19, "Tudo é salvo automaticamente :)", "black"),
        (1, 0, "Ideias", "red"),
        (1, 2, "- livros para ler", "blue"),
        (1, 3, "- receitas para testar", "blue"),
        (1, 4, "- planos para o fim de semana", "blue"),
    ]
    for page, line, text, ink in lines:
        conn.execute(
            "INSERT INTO lines (notebook_id, page, line, text, ink) VALUES (?, ?, ?, ?, ?)",
            (nid, page, line, text, ink),
        )


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    is_new = not DB_PATH.exists()
    with get_db() as conn:
        conn.executescript(SCHEMA)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(notebooks)")}
        if "font" not in cols:
            conn.execute(f"ALTER TABLE notebooks ADD COLUMN font TEXT NOT NULL DEFAULT '{DEFAULT_FONT}'")
        if is_new:
            _seed(conn)
        # canetas que deixaram de existir passam a ser azuis
        marks = ",".join("?" * len(INKS))
        conn.execute(f"UPDATE lines SET ink = 'blue' WHERE ink NOT IN ({marks})", tuple(INKS))


def _clean_title(value) -> str:
    title = re.sub(r"\s+", " ", str(value or "")).strip()[:80]
    return title or "Sem título"


def _clean_color(value) -> str:
    value = str(value or "")
    return value if HEX_RE.match(value) else PALETTE[0]["hex"]


def _clean_font(value) -> str:
    return value if value in FONTS else DEFAULT_FONT


def _clean_pages(value) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = DEFAULT_PAGES
    n = max(2, min(MAX_PAGES, n))
    return n + (n % 2)  # sempre par: duas paginas por vez


# --------------------------------------------------------------------------
# Servidor web (Flask)
# --------------------------------------------------------------------------
NB_SELECT = """
SELECT n.*,
       (SELECT COUNT(*)  FROM lines l WHERE l.notebook_id = n.id) AS used,
       (SELECT MAX(page) FROM (SELECT page FROM lines   WHERE notebook_id = n.id
                               UNION ALL
                               SELECT page FROM strokes WHERE notebook_id = n.id)) AS max_page
FROM notebooks n
"""


def _nb_json(row) -> dict:
    last_page = 0 if row["max_page"] is None else row["max_page"] + 1
    min_pages = max(2, last_page + (last_page % 2))
    return {
        "id": row["id"],
        "title": row["title"],
        "color": row["color"],
        "pages": row["pages"],
        "font": _clean_font(row["font"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "used_lines": row["used"],
        "last_page": last_page,
        "min_pages": min_pages,
    }


def create_app():
    from flask import Flask, Response, jsonify, request

    app = Flask(__name__)

    def err(message, code=400):
        return jsonify({"error": message}), code

    def fetch_nb(conn, nid):
        return conn.execute(NB_SELECT + " WHERE n.id = ?", (nid,)).fetchone()

    @app.get("/manifest.webmanifest")
    def manifest():
        return Response(json.dumps(MANIFEST, ensure_ascii=False), mimetype="application/manifest+json")

    @app.get("/icon.svg")
    def icon():
        resp = Response(ICON_SVG, mimetype="image/svg+xml")
        resp.headers["Cache-Control"] = "max-age=86400"
        return resp

    @app.get("/")
    def index():
        html = (
            INDEX_HTML.replace("__LINES__", str(LINES_PER_PAGE))
            .replace("__PALETTE__", json.dumps(PALETTE))
            .replace("__INKS__", json.dumps(INKS))
            .replace("__FONTS_URL__", FONTS_URL)
            .replace("__FONTS__", json.dumps({k: {"name": f["name"], "css": f["css"], "size": f["size"], "shift": f["shift"]}
                                              for k, f in FONTS.items()}))
            .replace("__DEFAULT_FONT__", json.dumps(DEFAULT_FONT))
            .replace("__PAGE_OPTIONS__", json.dumps(PAGE_OPTIONS))
            .replace("__DEFAULT_PAGES__", str(DEFAULT_PAGES))
            .replace("__MAX_CHARS__", str(MAX_LINE_CHARS))
        )
        resp = Response(html, mimetype="text/html")
        resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.get("/api/notebooks")
    def list_notebooks():
        with get_db() as conn:
            rows = conn.execute(NB_SELECT + " ORDER BY n.updated_at DESC, n.id DESC").fetchall()
        return jsonify([_nb_json(r) for r in rows])

    @app.post("/api/notebooks")
    def create_notebook():
        data = request.get_json(silent=True) or {}
        ts = _now()
        with get_db() as conn:
            cur = conn.execute(
                "INSERT INTO notebooks (title, color, pages, font, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (_clean_title(data.get("title")), _clean_color(data.get("color")),
                 _clean_pages(data.get("pages")), _clean_font(data.get("font")), ts, ts),
            )
            row = fetch_nb(conn, cur.lastrowid)
        return jsonify(_nb_json(row)), 201

    @app.get("/api/notebooks/<int:nid>")
    def get_notebook(nid):
        with get_db() as conn:
            row = fetch_nb(conn, nid)
            if row is None:
                return err("Caderno não encontrado.", 404)
            lines = conn.execute(
                "SELECT page, line, text, ink FROM lines WHERE notebook_id = ? ORDER BY page, line",
                (nid,),
            ).fetchall()
            strokes = conn.execute(
                "SELECT id, page, ink, data FROM strokes WHERE notebook_id = ? ORDER BY id", (nid,)
            ).fetchall()
        return jsonify({
            "notebook": _nb_json(row),
            "lines": [dict(l) for l in lines],
            "strokes": [{"id": r["id"], "page": r["page"], "ink": r["ink"], "data": json.loads(r["data"])}
                        for r in strokes],
        })

    @app.patch("/api/notebooks/<int:nid>")
    def update_notebook(nid):
        data = request.get_json(silent=True) or {}
        with get_db() as conn:
            row = fetch_nb(conn, nid)
            if row is None:
                return err("Caderno não encontrado.", 404)
            info = _nb_json(row)
            title = _clean_title(data["title"]) if "title" in data else row["title"]
            color = _clean_color(data["color"]) if "color" in data else row["color"]
            font = _clean_font(data["font"]) if "font" in data else row["font"]
            pages = row["pages"]
            if "pages" in data:
                pages = _clean_pages(data["pages"])
                if pages < info["min_pages"]:
                    return err(
                        f"Este caderno tem anotações até a página {info['last_page']}. "
                        f"Escolha {info['min_pages']} páginas ou mais."
                    )
            conn.execute(
                "UPDATE notebooks SET title = ?, color = ?, pages = ?, font = ?, updated_at = ? WHERE id = ?",
                (title, color, pages, font, _now(), nid),
            )
            row = fetch_nb(conn, nid)
        return jsonify(_nb_json(row))

    @app.delete("/api/notebooks/<int:nid>")
    def delete_notebook(nid):
        with get_db() as conn:
            cur = conn.execute("DELETE FROM notebooks WHERE id = ?", (nid,))
            if cur.rowcount == 0:
                return err("Caderno não encontrado.", 404)
        return "", 204

    @app.put("/api/notebooks/<int:nid>/lines")
    def save_line(nid):
        data = request.get_json(silent=True) or {}
        try:
            page = int(data.get("page"))
            line = int(data.get("line"))
        except (TypeError, ValueError):
            return err("Linha inválida.")
        text = re.sub(r"[\r\n\t]+", " ", str(data.get("text") or ""))[:MAX_LINE_CHARS].rstrip()
        ink = data.get("ink") if data.get("ink") in INKS else "blue"
        ts = _now()
        with get_db() as conn:
            row = conn.execute("SELECT pages FROM notebooks WHERE id = ?", (nid,)).fetchone()
            if row is None:
                return err("Caderno não encontrado.", 404)
            if not (0 <= page < row["pages"] and 0 <= line < LINES_PER_PAGE):
                return err("Essa linha não existe no caderno.")
            if text:
                conn.execute(
                    "INSERT OR REPLACE INTO lines (notebook_id, page, line, text, ink) VALUES (?, ?, ?, ?, ?)",
                    (nid, page, line, text, ink),
                )
            else:
                conn.execute(
                    "DELETE FROM lines WHERE notebook_id = ? AND page = ? AND line = ?",
                    (nid, page, line),
                )
            conn.execute("UPDATE notebooks SET updated_at = ? WHERE id = ?", (ts, nid))
        return jsonify({"ok": True, "updated_at": ts})

    def clean_stroke(data):
        stroke = data.get("data")
        if not isinstance(stroke, dict) or stroke.get("kind") not in ("ink", "shape"):
            return None, None
        raw = json.dumps(stroke, separators=(",", ":"))
        if len(raw) > MAX_STROKE_BYTES:
            return None, None
        ink = data.get("ink") if data.get("ink") in INKS else "blue"
        return raw, ink

    @app.post("/api/notebooks/<int:nid>/strokes")
    def add_stroke(nid):
        data = request.get_json(silent=True) or {}
        try:
            page = int(data.get("page"))
        except (TypeError, ValueError):
            return err("Página inválida.")
        raw, ink = clean_stroke(data)
        if raw is None:
            return err("Desenho inválido.")
        with get_db() as conn:
            row = conn.execute("SELECT pages FROM notebooks WHERE id = ?", (nid,)).fetchone()
            if row is None:
                return err("Caderno não encontrado.", 404)
            if not 0 <= page < row["pages"]:
                return err("Essa página não existe no caderno.")
            cur = conn.execute(
                "INSERT INTO strokes (notebook_id, page, ink, data) VALUES (?, ?, ?, ?)", (nid, page, ink, raw)
            )
            conn.execute("UPDATE notebooks SET updated_at = ? WHERE id = ?", (_now(), nid))
        return jsonify({"id": cur.lastrowid}), 201

    @app.put("/api/notebooks/<int:nid>/strokes/<int:sid>")
    def update_stroke(nid, sid):
        raw, ink = clean_stroke(request.get_json(silent=True) or {})
        if raw is None:
            return err("Desenho inválido.")
        with get_db() as conn:
            cur = conn.execute(
                "UPDATE strokes SET data = ?, ink = ? WHERE id = ? AND notebook_id = ?", (raw, ink, sid, nid)
            )
            if cur.rowcount == 0:
                return err("Desenho não encontrado.", 404)
            conn.execute("UPDATE notebooks SET updated_at = ? WHERE id = ?", (_now(), nid))
        return jsonify({"ok": True})

    @app.delete("/api/notebooks/<int:nid>/strokes/<int:sid>")
    def delete_stroke(nid, sid):
        with get_db() as conn:
            conn.execute("DELETE FROM strokes WHERE id = ? AND notebook_id = ?", (sid, nid))
            conn.execute("UPDATE notebooks SET updated_at = ? WHERE id = ?", (_now(), nid))
        return "", 204

    @app.errorhandler(404)
    def not_found(_e):
        if request.path.startswith("/api/"):
            return err("Recurso não encontrado.", 404)
        return Response("Página não encontrada.", 404, mimetype="text/plain")

    return app


def port_is_free(hosts, port: int) -> bool:
    import socket

    for host in hosts:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("" if host == "0.0.0.0" else host, port))
            except OSError:
                return False
    return True


def find_free_port(hosts, start: int) -> int:
    for port in range(start, start + 50):
        if port_is_free(hosts, port):
            return port
    sys.exit(f"Nenhuma porta livre encontrada entre {start} e {start + 49}.")


def tailscale_info():
    """IP (100.x.y.z) e nome MagicDNS deste computador na tailnet, ou (None, None)."""
    exe = shutil.which("tailscale")
    if not exe:
        return None, None
    try:
        out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5).stdout.split()
        ip = out[0] if out else None
    except (OSError, subprocess.SubprocessError):
        return None, None
    name = None
    if ip:
        try:
            st = json.loads(subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=5).stdout)
            name = ((st.get("Self") or {}).get("DNSName") or "").rstrip(".") or None
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return ip, name


def open_app_window(url: str) -> None:
    """Abre o Nootebook numa janela de aplicativo (como um app web instalado)."""
    import webbrowser

    for name in APP_BROWSERS:
        exe = shutil.which(name)
        if exe:
            subprocess.Popen(
                [exe, f"--app={url}", "--class=Nootebook", f"--user-data-dir={BASE_DIR / 'janela'}",
                 "--no-first-run", "--no-default-browser-check", "--start-maximized"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
            return
    webbrowser.open(url)


def main() -> None:
    import argparse
    import logging
    import threading

    parser = argparse.ArgumentParser(
        prog="nootebook", description="Nootebook - caderno pautado digital no navegador."
    )
    parser.add_argument("--host", action="append",
                        help="endereço do servidor; pode repetir para ouvir em vários (padrão: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="porta (padrão: 8765)")
    parser.add_argument("--tailscale", action="store_true",
                        help="também aceitar conexões pelo IP do Tailscale (espera ele conectar)")
    parser.add_argument("--strict-port", action="store_true", help="falhar se a porta estiver ocupada")
    parser.add_argument("--no-browser", action="store_true", help="não abrir o navegador automaticamente")
    args = parser.parse_args()
    hosts = list(dict.fromkeys(args.host or ["127.0.0.1"]))
    if "0.0.0.0" in hosts:
        hosts = ["0.0.0.0"]

    init_db()
    app = create_app()
    if args.strict_port:
        if not port_is_free(hosts, args.port):
            sys.exit(f"A porta {args.port} já está em uso (o Nootebook já está aberto?).")
        port = args.port
    else:
        port = find_free_port(hosts, args.port)
    local = next((h for h in hosts if h in ("127.0.0.1", "0.0.0.0", "localhost")), None)
    url = f"http://{'localhost' if local else hosts[0]}:{port}/"

    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    from werkzeug.serving import make_server

    def serve(host):
        srv = make_server(host, port, app, threaded=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv

    try:
        servers = [serve(h) for h in hosts]
    except OSError as exc:
        sys.exit(f"Não consegui abrir o servidor: {exc}")

    line = "=" * 52
    print(f"\n{line}\n  Nootebook está rodando!\n")
    print(f"  Abra:      {url}")
    for h in hosts:
        if h.startswith("100."):
            print(f"  Tailscale: http://{h}:{port}/")
    if "0.0.0.0" in hosts:
        print("  (acessível por outros aparelhos da rede pelo IP deste computador)")
    print(f"  Dados:     {DB_PATH}")
    print(f"  Para sair, pressione Ctrl+C\n{line}\n", flush=True)

    # Tailscale: abre (e reabre se o IP mudar) um servidor no IP da tailnet assim que ele existir.
    # So ouve nesse IP, entao quem esta no mesmo Wi-Fi nao entra; so os aparelhos da sua tailnet.
    stop = threading.Event()

    def watch_tailscale():
        current, srv, warned = None, None, False
        while not stop.is_set():
            ip, name = tailscale_info()
            if ip != current:
                if srv:
                    srv.shutdown()
                    srv.server_close()
                    srv = None
                if ip:
                    try:
                        srv = serve(ip)
                        print(f"  Tailscale: http://{ip}:{port}/" + (f"  ou  http://{name}:{port}/" if name else ""), flush=True)
                    except OSError as exc:
                        print(f"  Tailscale: não consegui ouvir em {ip}: {exc}", flush=True)
                elif not warned:
                    print("  Tailscale: desconectado; o acesso pela tailnet volta quando ele conectar.", flush=True)
                    warned = True
                current = ip
            stop.wait(20)

    if args.tailscale:
        threading.Thread(target=watch_tailscale, daemon=True).start()

    if not args.no_browser:
        threading.Timer(1.0, lambda: open_app_window(url)).start()

    import signal

    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    try:
        while not stop.wait(3600):
            pass
    except KeyboardInterrupt:
        pass
    stop.set()
    for srv in servers:
        srv.shutdown()
        srv.server_close()
    print("\nAté logo! Seus cadernos ficam salvos em:", DB_PATH)


# --------------------------------------------------------------------------
# Interface (HTML + CSS + JavaScript em uma unica pagina)
# --------------------------------------------------------------------------
INDEX_HTML = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Nootebook</title>
<link rel="icon" href="/icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/icon.svg">
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#f5f3ee">
<meta name="application-name" content="Nootebook">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="Nootebook">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="__FONTS_URL__" rel="stylesheet">
<style>
:root{
  --ui:'Inter',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  --serif:'Cormorant Garamond','Iowan Old Style',Georgia,serif;
  --hand:'Caveat','Segoe Print','Bradley Hand',cursive;
  --bg:#f5f3ee; --text:#1f1f22; --muted:#8c877e; --hair:rgba(31,31,34,.12); --danger:#a8322b;
  --paper:#fefdfa; --rule:rgba(112,140,178,.26); --margin-line:rgba(206,120,120,.38);
}
*{box-sizing:border-box}
[hidden]{display:none!important}
html,body{margin:0;height:100%}
body{font-family:var(--ui);font-size:14px;color:var(--text);background:var(--bg);-webkit-font-smoothing:antialiased;overflow:hidden}
button{font:inherit;color:inherit}
svg{display:block}
.view{position:fixed;inset:0;opacity:0;visibility:hidden;transition:opacity .4s ease,visibility .4s}
.view.active{opacity:1;visibility:visible}

.btn{display:inline-flex;align-items:center;justify-content:center;height:36px;padding:0 18px;border-radius:999px;border:1px solid transparent;
  background:transparent;cursor:pointer;font-size:13px;font-weight:500;letter-spacing:.01em;white-space:nowrap;transition:background .2s,border-color .2s,color .2s,opacity .2s}
.btn:disabled{opacity:.5;cursor:default}
.btn-primary{background:var(--text);color:#fff}
.btn-primary:hover{background:#000}
.btn-ghost{border-color:var(--hair)}
.btn-ghost:hover{border-color:rgba(31,31,34,.35)}
.btn-danger{background:var(--danger);color:#fff}
.btn-danger:hover{filter:brightness(1.08)}

/* ---------------- Estante ---------------- */
#wall-view{overflow-y:auto}
.topbar{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:20px;height:72px;padding:0 clamp(20px,5vw,64px);background:var(--bg)}
.brand{margin:0;font-family:var(--serif);font-size:28px;font-weight:400;letter-spacing:.01em;flex:1}
.search{width:min(200px,30vw);height:32px;border:0;border-bottom:1px solid var(--hair);background:transparent;outline:none;font:inherit;font-size:13px;color:var(--text);transition:border-color .2s}
.search:focus{border-color:var(--text)}
.search::placeholder{color:var(--muted)}
.wall{max-width:1240px;margin:0 auto;padding:40px clamp(20px,5vw,64px) 96px}
.grid{--cw:164px;display:grid;grid-template-columns:repeat(auto-fill,minmax(calc(var(--cw) + 16px),1fr));gap:56px 24px;justify-items:center}
.empty{text-align:center;font-family:var(--serif);font-style:italic;font-size:22px;color:var(--muted);margin-top:12vh}

.nb{position:relative;width:var(--cw);cursor:pointer;outline:none;animation:rise .6s ease backwards;animation-delay:var(--delay,0s);transition:opacity .35s,transform .35s}
.nb.removing{opacity:0;transform:scale(.96)}
.cover{position:relative;width:var(--cw,164px);height:calc(var(--cw,164px) * 1.4);border-radius:2px 5px 5px 2px;background-color:var(--c);
  background-image:linear-gradient(90deg,rgba(0,0,0,.16) 0,rgba(0,0,0,.04) 5%,rgba(255,255,255,.08) 6.5%,rgba(255,255,255,0) 11%);
  box-shadow:0 1px 2px rgba(0,0,0,.08),0 18px 30px -22px rgba(0,0,0,.45);transition:transform .45s cubic-bezier(.2,.8,.2,1),box-shadow .45s}
.cover::after{content:"";position:absolute;top:0;bottom:0;right:14%;width:4px;background:rgba(0,0,0,.2);box-shadow:1px 0 0 rgba(255,255,255,.08)}
.nb:hover .cover,.nb:focus-visible .cover{transform:translateY(-6px);box-shadow:0 1px 2px rgba(0,0,0,.06),0 30px 40px -24px rgba(0,0,0,.45)}
.nb .meta{margin-top:16px;line-height:1.35}
.nb .meta b{display:block;font-family:var(--serif);font-size:18px;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.nb .meta small{display:block;margin-top:2px;font-size:11.5px;color:var(--muted)}
.nb .actions{position:absolute;z-index:2;top:10px;right:10px;display:flex;gap:6px;opacity:0;transition:opacity .25s}
.nb:hover .actions,.nb:focus-within .actions{opacity:1}
@media (hover:none){.nb .actions{opacity:1}}
.icon-btn{width:28px;height:28px;border-radius:50%;border:0;display:grid;place-items:center;cursor:pointer;background:rgba(255,255,255,.92);color:var(--text);transition:background .2s,color .2s}
.icon-btn:hover{background:#fff}
.icon-btn.del:hover{background:var(--danger);color:#fff}
.icon-btn svg{width:13px;height:13px}

/* ---------------- Caderno aberto ---------------- */
#book-view{--cover:#2c3a52;--page-w:400px;--page-h:572px;--lh:22px;--pad:5px;overflow:hidden}
/* tudo o que nao e o caderno fica pequeno e apagado ate o mouse chegar perto */
.corner-ui{position:absolute;z-index:20;opacity:.4;transition:opacity .25s}
.corner-ui:hover,.corner-ui:focus-within,.corner-ui.open{opacity:1}
@media (hover:none){.corner-ui{opacity:.75}}
.back-btn{top:10px;left:12px;width:32px;height:32px;padding:0;border:0;border-radius:50%;display:grid;place-items:center;background:transparent;color:var(--text);cursor:pointer;transition:opacity .25s,background .2s}
.back-btn:hover{background:rgba(31,31,34,.06)}
.back-btn svg{width:18px;height:18px}
.nb-tools{top:10px;right:12px}
.tools-btn{position:relative;width:32px;height:32px;padding:0;border:0;border-radius:50%;display:grid;place-items:center;background:transparent;color:var(--text);cursor:pointer;transition:background .2s}
.tools-btn svg{width:17px;height:17px}
#toolsIcon{display:grid;place-items:center}
.modes{display:grid;grid-template-columns:repeat(3,1fr);gap:4px}
.mode{display:flex;flex-direction:column;align-items:center;gap:4px;padding:8px 4px 6px;border:1px solid var(--hair);border-radius:8px;background:transparent;cursor:pointer;font-size:11px;color:var(--muted);transition:border-color .2s,background .2s,color .2s}
.mode svg{width:17px;height:17px}
.mode:hover{border-color:rgba(31,31,34,.35);color:var(--text)}
.mode.active{background:var(--text);border-color:var(--text);color:#fff}
.keys{margin-top:8px;font-size:11px;line-height:1.7;color:var(--muted)}
.keys kbd{display:inline-block;min-width:16px;padding:0 4px;border:1px solid var(--hair);border-radius:4px;font:inherit;font-size:10.5px;text-align:center;color:var(--text)}
@media (hover:none){.keys{display:none}}
.toggle{display:flex;align-items:center;gap:8px;margin:2px 0 8px;font-size:12.5px;cursor:pointer}
.toggle input{width:14px;height:14px;margin:0;accent-color:var(--text);cursor:pointer}
.undo-btn{display:inline-flex;align-items:center;gap:6px;height:28px;margin-top:2px;padding:0 10px 0 8px;border:1px solid var(--hair);border-radius:999px;background:transparent;cursor:pointer;font-size:12px;transition:border-color .2s}
.undo-btn:hover{border-color:rgba(31,31,34,.4)}
.undo-btn svg{width:14px;height:14px}
.nb-tools:hover .tools-btn,.nb-tools.open .tools-btn{background:rgba(31,31,34,.06)}
.tools-btn .dot{position:absolute;top:5px;right:5px;width:6px;height:6px;border-radius:50%;background:transparent;transition:background .2s}
.nb-tools[data-status=saving] .tools-btn .dot{background:#d8b56a;animation:pulse 1s infinite}
.nb-tools[data-status=error] .tools-btn .dot{background:var(--danger)}
.nb-tools[data-status=error]{opacity:1}
.tools-panel{position:absolute;top:100%;right:0;padding-top:8px;opacity:0;visibility:hidden;transform:translateY(-4px);transition:opacity .2s,transform .2s,visibility .2s}
.nb-tools:hover .tools-panel,.nb-tools:focus-within .tools-panel,.nb-tools.open .tools-panel{opacity:1;visibility:visible;transform:none}
.tools-card{width:260px;max-height:calc(100vh - 70px);overflow:auto;padding:16px;border-radius:10px;background:#fff;box-shadow:0 1px 2px rgba(0,0,0,.06),0 18px 40px -16px rgba(0,0,0,.3)}
.nb-title{margin:0 0 14px;font-family:var(--serif);font-size:20px;font-weight:500;line-height:1.2;overflow-wrap:anywhere}
.tools-sec{margin-top:16px}
.tools-sec>span{display:block;margin-bottom:8px;font-size:10.5px;font-weight:500;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
.pens{display:flex;gap:14px;padding:2px 3px}
.pen{width:14px;height:14px;padding:0;border-radius:50%;border:0;cursor:pointer;background:var(--ink);transition:transform .2s,box-shadow .2s}
.pen:hover{transform:scale(1.2)}
.pen.active{box-shadow:0 0 0 3px #fff,0 0 0 4px var(--ink)}
.font-list{display:grid;grid-template-columns:1fr 1fr;gap:1px;margin:0 -8px}
.font-opt{display:flex;align-items:baseline;justify-content:space-between;gap:10px;width:100%;padding:6px 8px;border:0;border-radius:6px;background:transparent;cursor:pointer;text-align:left}
.font-opt:hover{background:var(--bg)}
.font-opt.active{background:#ecebe6}
.font-opt span{font-size:18px;line-height:1.2;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.font-opt small{display:none}
.chip.font-chip{font-size:17px;height:34px}
.status{display:flex;align-items:center;gap:7px;margin-top:16px;padding-top:12px;border-top:1px solid var(--hair);font-size:12px;color:var(--muted);white-space:nowrap}
.status .dot{width:5px;height:5px;border-radius:50%;background:#9bbfa5}
.status.saving .dot{background:#d8b56a;animation:pulse 1s infinite}
.status.error{color:var(--danger)}
.status.error .dot{background:var(--danger)}
@keyframes pulse{50%{opacity:.3}}

.desk{position:absolute;top:0;bottom:0;left:0;right:0;display:flex;overflow:auto;padding:14px 0}
.book{position:relative;flex:none;margin:auto;padding:var(--pad);border-radius:4px;background:var(--cover);
  box-shadow:0 1px 2px rgba(0,0,0,.06),0 24px 48px -30px rgba(0,0,0,.3)}
#book-view.active .book{animation:rise .6s cubic-bezier(.2,.8,.2,1) both}
@keyframes rise{from{opacity:0;transform:translateY(14px)}}
.spread{position:relative;display:flex;perspective:2400px;perspective-origin:50% 40%}
.slot{position:relative;flex:none;width:var(--page-w);height:var(--page-h)}


.page{--grain:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='2' stitchTiles='stitch'/%3E%3CfeColorMatrix values='0 0 0 0 .32 0 0 0 0 .26 0 0 0 0 .2 .13 0 0 0 -.035'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  position:absolute;inset:0;overflow:hidden;background-color:var(--paper);background-image:var(--grain);-webkit-user-select:none;user-select:none;touch-action:pan-y pinch-zoom}
body.page-drag,body.page-drag *{cursor:grabbing!important;-webkit-user-select:none!important;user-select:none!important}
.page.left{border-radius:2px 0 0 2px;background-image:linear-gradient(270deg,rgba(40,30,20,.13),rgba(40,30,20,.04) 2.5%,rgba(40,30,20,.012) 7%,rgba(40,30,20,0) 12%),var(--grain)}
.page.right{border-radius:0 2px 2px 0;background-image:linear-gradient(90deg,rgba(40,30,20,.13),rgba(40,30,20,.04) 2.5%,rgba(40,30,20,.012) 7%,rgba(40,30,20,0) 12%),var(--grain)}
.margin-line{position:absolute;top:0;bottom:0;left:calc(var(--page-w) * .12);border-left:1px solid var(--margin-line);pointer-events:none}
.lines{position:absolute;left:0;right:0;top:calc(var(--lh) * 2.6);border-top:1px solid var(--rule)}
.line{position:relative;height:var(--lh);border-bottom:1px solid var(--rule);cursor:text;padding:0 calc(var(--page-w) * .06) 0 calc(var(--page-w) * .14)}
.line.editing{background:rgba(112,140,178,.05)}
.txt,.line-input{display:block;width:100%;height:calc(var(--lh) * 1.2);margin:0;padding:0;border:0;border-radius:0;background:transparent;outline:none;
  position:relative;top:calc(var(--lh) * var(--fy,0));font-family:var(--nbfont,var(--hand));font-size:calc(var(--lh) * var(--fs,.82));font-weight:400;line-height:calc(var(--lh) * 1.2);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#24408e}
.txt{-webkit-user-select:text;user-select:text}
.line-input{caret-color:currentColor;-webkit-appearance:none;appearance:none}
svg.ink{position:absolute;inset:0;z-index:1;width:100%;height:100%;overflow:visible;pointer-events:none}
svg.ink .ink-line,svg.ink .shape{fill:none;stroke-linecap:round;stroke-linejoin:round}
svg.ink .fade-in{animation:inkIn .35s ease}
svg.ink .fade-out{opacity:0;transition:opacity .3s ease}
@keyframes inkIn{from{opacity:0}}
#book-view.mode-draw .slot .page,#book-view.mode-erase .slot .page{touch-action:none}
body.pen-user #book-view .slot .page{touch-action:pan-y pinch-zoom}
#book-view.mode-draw .slot .page,#book-view.mode-draw .slot .line{cursor:crosshair}
#book-view.mode-erase .slot .page,#book-view.mode-erase .slot .line{cursor:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='18' height='18'%3E%3Ccircle cx='9' cy='9' r='8' fill='white' fill-opacity='.55' stroke='%23333' stroke-width='1'/%3E%3C/svg%3E") 9 9,cell}
.pnum{position:absolute;bottom:calc(var(--lh) * .45);font-size:10.5px;letter-spacing:.04em;color:#b0aba2;pointer-events:none}
.page.left .pnum{left:calc(var(--page-w) * .06)}
.page.right .pnum{right:calc(var(--page-w) * .06)}
.corner{position:absolute;bottom:0;z-index:2;width:calc(var(--lh) * 2.2);height:calc(var(--lh) * 2.2);cursor:grab}
.page.left .corner{left:0}
.page.right .corner{right:0}
.corner::before{content:"";position:absolute;bottom:0;width:calc(var(--lh) * .7);height:calc(var(--lh) * .7);transition:width .3s ease,height .3s ease}
.page.right .corner::before{right:0;background:linear-gradient(to bottom right,#fbfaf6 0%,#eeebe4 46%,#e2ddd3 50%,var(--cover) 50%)}
.page.left .corner::before{left:0;background:linear-gradient(to bottom left,#fbfaf6 0%,#eeebe4 46%,#e2ddd3 50%,var(--cover) 50%)}
.corner:hover::before{width:calc(var(--lh) * 1.5);height:calc(var(--lh) * 1.5)}

/* folha virando sem WebGL: gira inteira (com WebGL ela e desenhada no canvas .flip-gl) */
.curl{position:absolute;top:0;z-index:6;width:var(--page-w);height:var(--page-h);transform-style:preserve-3d;pointer-events:none}
.curl.fwd{left:var(--page-w)}
.curl.bwd{left:0}
.strip{position:absolute;top:0;height:100%;transform-style:preserve-3d;will-change:transform}
.curl.fwd .strip{transform-origin:0 50%}
.curl.bwd .strip{transform-origin:100% 50%}
.face{position:absolute;top:0;bottom:0;left:0;width:calc(100% + 1px);overflow:hidden;-webkit-backface-visibility:hidden;backface-visibility:hidden}
.curl.bwd .face{left:-1px}
.face.back{transform:rotateY(180deg)}
.face .page{-webkit-backface-visibility:hidden;backface-visibility:hidden}
.face .corner{display:none}
.lit{position:absolute;inset:0;z-index:3;pointer-events:none}
.flip-gl{position:absolute;inset:0;z-index:15;width:100%;height:100%;display:none;pointer-events:none}

.pager{right:12px;bottom:10px;display:flex;align-items:center;gap:6px;height:32px;padding:0 3px;border-radius:999px;transition:opacity .25s,background .25s}
.pager:hover,.pager:focus-within{background:var(--bg);box-shadow:0 0 0 1px var(--hair)}
.pager .round{opacity:0;transition:opacity .25s}
.pager:hover .round,.pager:focus-within .round{opacity:1}
.pager:hover .round:disabled,.pager:focus-within .round:disabled{opacity:.3}
@media (hover:none){.pager .round{opacity:1}}
.round{flex:none;width:26px;height:26px;border-radius:50%;border:1px solid var(--hair);display:grid;place-items:center;cursor:pointer;background:transparent;color:var(--text);transition:border-color .2s,opacity .2s}
.round svg{width:14px;height:14px}
.round:hover:not(:disabled){border-color:rgba(31,31,34,.4)}
.round:disabled{opacity:.3;cursor:default}
.page-label{min-width:72px;text-align:center;font-size:11.5px;color:var(--muted);font-variant-numeric:tabular-nums;white-space:pre}
#book-view.tight .pager{flex-direction:column;width:38px;height:auto;right:7px;padding:4px 0;gap:4px;border-radius:19px}
#book-view.tight .pager input[type=range]{display:none}
#book-view.tight .page-label{min-width:0;font-size:10.5px;line-height:1.3}
.zoom{display:flex;align-items:center;gap:6px}
.zbtn{width:26px;height:26px;padding:0;border:1px solid var(--hair);border-radius:50%;background:transparent;cursor:pointer;font-size:15px;line-height:1;transition:border-color .2s,opacity .2s}
.zbtn:hover:not(:disabled){border-color:rgba(31,31,34,.4)}
#zoomVal{min-width:40px;text-align:center;font-size:12.5px;font-variant-numeric:tabular-nums}
.zlink{height:26px;padding:0 8px;border:0;border-radius:6px;background:transparent;cursor:pointer;font-size:12px;color:var(--muted);transition:color .2s,background .2s}
.zlink:hover:not(:disabled){color:var(--text);background:var(--bg)}
.zbtn:disabled,.zlink:disabled{opacity:.35;cursor:default}
.pager input[type=range]{-webkit-appearance:none;appearance:none;width:0;height:16px;margin:0;opacity:0;background:transparent;cursor:pointer;transition:width .25s,opacity .25s}
.pager:hover input[type=range],.pager:focus-within input[type=range]{width:clamp(80px,14vw,180px);opacity:1}
.pager input[type=range]:focus{outline:none}
.pager input[type=range]::-webkit-slider-runnable-track{height:1px;background:rgba(31,31,34,.2)}
.pager input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:9px;height:9px;margin-top:-4px;border-radius:50%;background:var(--text)}
.pager input[type=range]::-moz-range-track{height:1px;background:rgba(31,31,34,.2)}
.pager input[type=range]::-moz-range-thumb{width:9px;height:9px;border:0;border-radius:50%;background:var(--text)}

/* ---------------- Modais e avisos ---------------- */
.backdrop{position:fixed;inset:0;z-index:100;display:grid;place-items:center;padding:16px;background:rgba(31,31,34,.22);
  backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px);animation:fade .25s ease}
@keyframes fade{from{opacity:0}}
.modal{width:min(600px,100%);max-height:calc(100vh - 32px);overflow:auto;display:flex;gap:40px;padding:40px;border-radius:8px;background:#fff;
  box-shadow:0 30px 70px -30px rgba(0,0,0,.35);animation:rise .35s cubic-bezier(.2,.8,.2,1)}
.modal h2{margin:0 0 28px;font-family:var(--serif);font-size:30px;font-weight:400;line-height:1}
.preview{flex:none;display:grid;place-items:center}
.preview .cover{--cw:140px;transition:background-color .3s}
.form{flex:1;min-width:0}
.field{margin-bottom:24px}
.field>span,.field>label{display:block;font-size:11px;font-weight:500;letter-spacing:.1em;text-transform:uppercase;color:var(--muted);margin-bottom:10px}
.input{width:100%;height:38px;padding:0;border:0;border-bottom:1px solid var(--hair);background:transparent;font-family:var(--serif);font-size:20px;
  color:var(--text);outline:none;border-radius:0;transition:border-color .2s}
.input:focus{border-color:var(--text)}
.swatches{display:flex;flex-wrap:wrap;gap:12px}
.swatch{width:22px;height:22px;border-radius:50%;border:0;padding:0;cursor:pointer;background:var(--c);transition:transform .2s,box-shadow .2s}
.swatch:hover{transform:scale(1.12)}
.swatch.active{box-shadow:0 0 0 3px #fff,0 0 0 4px var(--c)}
.chips{display:flex;flex-wrap:wrap;gap:8px}
.chip{height:30px;min-width:46px;padding:0 12px;border-radius:999px;border:1px solid var(--hair);background:transparent;cursor:pointer;font-size:12.5px;transition:.2s}
.chip:hover:not(:disabled){border-color:rgba(31,31,34,.4)}
.chip.active{background:var(--text);border-color:var(--text);color:#fff}
.chip:disabled{opacity:.3;cursor:not-allowed}
.hint{font-size:12px;color:var(--muted);margin-top:10px}
.modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:36px}
.modal.small{flex-direction:column;text-align:center;width:min(380px,100%);gap:0}
.modal.small h2{margin-bottom:14px}
.modal.small p{margin:0;color:#6b675f;line-height:1.6}
.modal.small .modal-actions{justify-content:center}
.toast{position:fixed;left:50%;bottom:28px;z-index:200;transform:translate(-50%,8px);opacity:0;padding:10px 18px;border-radius:999px;background:var(--text);color:#fff;
  font-size:12.5px;transition:.3s;pointer-events:none;max-width:calc(100vw - 32px);text-align:center}
.toast.show{opacity:1;transform:translate(-50%,0)}
.toast.error{background:var(--danger)}

@media (max-width:600px){
  .grid{--cw:138px;gap:44px 12px}
  .modal{flex-direction:column;padding:28px}
  .preview{display:none}
  .pager input[type=range]{display:none}
}
@media (prefers-reduced-motion:reduce){*{animation-duration:.01ms!important;transition-duration:.01ms!important}}
</style>
</head>
<body>

<section id="wall-view" class="view" aria-label="Seus cadernos">
  <header class="topbar">
    <h1 class="brand">Nootebook</h1>
    <input class="search" id="search" type="search" placeholder="Procurar" autocomplete="off" hidden>
    <button class="btn btn-primary" id="newBtn">Novo caderno</button>
  </header>
  <main class="wall">
    <div class="grid" id="grid"></div>
    <p class="empty" id="empty" hidden></p>
  </main>
</section>

<section id="book-view" class="view" aria-label="Caderno aberto">
  <main class="desk" id="desk">
    <div class="book">
      <div class="spread" id="spread">
        <div class="slot left" id="slotL"></div>
        <div class="slot right" id="slotR"></div>
      </div>
    </div>
  </main>
  <button class="back-btn corner-ui" id="backBtn" title="Voltar aos cadernos (Esc)" aria-label="Voltar aos cadernos"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg></button>
  <div class="nb-tools corner-ui" id="nbTools" data-status="saved">
    <button class="tools-btn" id="toolsBtn" aria-label="Configurações do caderno" aria-expanded="false" title="Configurações do caderno"><span id="toolsIcon"></span><span class="dot"></span></button>
    <div class="tools-panel">
      <div class="tools-card">
        <h2 class="nb-title" id="bookTitle"></h2>
        <div class="tools-sec"><span>Ferramenta</span><div class="modes" id="modes"></div>
          <div class="keys">Atalhos: <kbd>T</kbd> texto · <kbd>D</kbd> caneta · <kbd>E</kbd> borracha · <kbd>Ctrl</kbd>+<kbd>Z</kbd> desfazer · <kbd>Ctrl</kbd>+roda do mouse: tamanho</div></div>
        <div class="tools-sec"><span>Tamanho</span><div class="zoom">
          <button type="button" class="zbtn" id="zoomOut" aria-label="Diminuir o caderno" title="Diminuir (Ctrl −)">−</button>
          <span id="zoomVal">100%</span>
          <button type="button" class="zbtn" id="zoomIn" aria-label="Aumentar o caderno" title="Aumentar (Ctrl +)">+</button>
          <button type="button" class="zlink" id="zoomFit" title="O caderno inteiro na tela (Ctrl 0)">Caber</button>
          <button type="button" class="zlink" id="zoomMax" title="Ocupar a largura da tela">Máximo</button>
        </div></div>
        <div class="tools-sec"><span>Cor</span><div class="pens" id="pens"></div></div>
        <div class="tools-sec"><span>Letra</span><div class="font-list" id="fontMenu" role="listbox" aria-label="Tipo de letra"></div></div>
        <div class="tools-sec"><span>Correção automática</span>
          <label class="toggle"><input type="checkbox" id="fixShapes"><span>Formas geométricas</span></label>
          <label class="toggle"><input type="checkbox" id="fixWriting"><span>Traço da escrita</span></label>
          <label class="toggle"><input type="checkbox" id="sound"><span>Som ao virar a folha</span></label>
          <button type="button" class="undo-btn" id="undoBtn" title="Desfazer (Ctrl+Z)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/></svg>Desfazer desenho</button>
        </div>
        <div class="status saved" id="status"><span class="dot"></span><span id="statusText">Salvo</span></div>
      </div>
    </div>
  </div>
  <nav class="pager corner-ui" aria-label="Folhear">
    <button class="round" id="prevBtn" aria-label="Páginas anteriores" title="Páginas anteriores (←)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg></button>
    <input type="range" id="pageRange" min="0" max="0" value="0" aria-label="Ir para as páginas">
    <div class="page-label" id="pageLabel"></div>
    <button class="round" id="nextBtn" aria-label="Próximas páginas" title="Próximas páginas (→)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m9 18 6-6-6-6"/></svg></button>
  </nav>
</section>

<div class="backdrop" id="nbModal" hidden>
  <form class="modal" id="nbForm" autocomplete="off">
    <div class="preview" id="preview"></div>
    <div class="form">
      <h2 id="nbModalTitle">Novo caderno</h2>
      <div class="field"><label for="nbTitle">Nome</label><input class="input" id="nbTitle" maxlength="80" placeholder="Sem título"></div>
      <div class="field"><span>Capa</span><div class="swatches" id="swatches"></div></div>
      <div class="field"><span>Letra</span><div class="chips" id="fontChips"></div></div>
      <div class="field"><span>Páginas</span><div class="chips" id="chips"></div><div class="hint" id="pagesHint" hidden></div></div>
      <div class="modal-actions"><button type="button" class="btn btn-ghost" data-close>Cancelar</button><button type="submit" class="btn btn-primary" id="nbSubmit">Criar</button></div>
    </div>
  </form>
</div>

<div class="backdrop" id="confirmModal" hidden>
  <div class="modal small" role="alertdialog" aria-modal="true" aria-labelledby="confirmTitle">
    <h2 id="confirmTitle">Apagar caderno?</h2>
    <p id="confirmText"></p>
    <div class="modal-actions"><button type="button" class="btn btn-ghost" data-close id="confirmCancel">Cancelar</button><button type="button" class="btn btn-danger" id="confirmOk">Apagar</button></div>
  </div>
</div>

<div class="toast" id="toast" role="status" aria-live="polite"></div>

<script>
"use strict";
const LINES = __LINES__;
const PALETTE = __PALETTE__;
const INKS = __INKS__;
const FONTS = __FONTS__;
const DEFAULT_FONT = __DEFAULT_FONT__;
const PAGE_OPTIONS = __PAGE_OPTIONS__;
const DEFAULT_PAGES = __DEFAULT_PAGES__;
const MAX_CHARS = __MAX_CHARS__;
const RATIO = 0.707;         // largura / altura da pagina (proporcao A4)
const SEARCH_FROM = 7;       // a busca so aparece quando ha muitos cadernos
const ICON = {
  edit:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>',
  trash:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M18 7l-1 13H7L6 7"/></svg>'
};

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => Array.from(el.querySelectorAll(s));
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const key = (p, l) => p + ':' + l;
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
const inkHex = k => (INKS[k] || INKS.blue).hex;
const fontOf = k => FONTS[k] || FONTS[DEFAULT_FONT];
const store = {
  get(k, d) { try { const v = localStorage.getItem('cadernos:' + k); return v === null ? d : JSON.parse(v); } catch (e) { return d; } },
  set(k, v) { try { localStorage.setItem('cadernos:' + k, JSON.stringify(v)); } catch (e) {} }
};

const state = {
  view: null, notebooks: [], filter: '',
  nb: null, lines: new Map(), strokes: new Map(), spread: 0, mode: store.get('mode', 'text'),
  ink: store.get('ink', 'blue'), editing: null, flipping: false, pending: 0,
  zoom: +store.get('zoom', 1.3) || 1.3, zoomMax: 1
};
if (!INKS[state.ink]) state.ink = 'blue';
if (!['text', 'draw', 'erase'].includes(state.mode)) state.mode = 'text';

/* ---------- utilidades ---------- */
async function api(method, url, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
  let res;
  try { res = await fetch(url, opts); }
  catch (e) { const er = new Error('Sem conexão com o servidor. Ele ainda está rodando?'); er.offline = true; throw er; }
  if (!res.ok) {
    let msg = 'Algo deu errado (' + res.status + ')';
    try { const j = await res.json(); if (j.error) msg = j.error; } catch (e) {}
    throw new Error(msg);
  }
  return res.status === 204 ? null : res.json();
}

let toastTimer;
function toast(msg, isError) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.toggle('error', !!isError);
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), isError ? 4000 : 2400);
}

const rtf = new Intl.RelativeTimeFormat('pt-BR', { numeric: 'auto' });
function ago(iso) {
  const s = (new Date(iso).getTime() - Date.now()) / 1000, a = Math.abs(s);
  if (a < 45) return 'agora mesmo';
  if (a < 3600) return rtf.format(Math.round(s / 60), 'minute');
  if (a < 86400) return rtf.format(Math.round(s / 3600), 'hour');
  if (a < 86400 * 30) return rtf.format(Math.round(s / 86400), 'day');
  if (a < 86400 * 365) return rtf.format(Math.round(s / (86400 * 30)), 'month');
  return rtf.format(Math.round(s / (86400 * 365)), 'year');
}

function setView(name) {
  state.view = name;
  $('#wall-view').classList.toggle('active', name === 'wall');
  $('#book-view').classList.toggle('active', name === 'book');
}

/* ---------- estante de cadernos ---------- */
function coverHTML(color) {
  return `<div class="cover" style="--c:${esc(color)}"></div>`;
}

function updateEmpty(shown) {
  const el = $('#empty');
  el.textContent = state.notebooks.length === 0 ? 'Nenhum caderno ainda.' : 'Nenhum caderno com esse nome.';
  el.hidden = shown > 0;
}

function renderWall() {
  const search = $('#search');
  search.hidden = state.notebooks.length < SEARCH_FROM && !state.filter;
  const q = state.filter.trim().toLowerCase();
  const list = state.notebooks.filter(n => !q || n.title.toLowerCase().includes(q));
  $('#grid').innerHTML = list.map((n, i) => `
    <div class="nb" tabindex="0" role="button" data-id="${n.id}" aria-label="Abrir ${esc(n.title)}" style="--delay:${Math.min(i, 14) * 40}ms">
      ${coverHTML(n.color)}
      <div class="actions">
        <button class="icon-btn" data-action="edit" title="Editar" aria-label="Editar caderno">${ICON.edit}</button>
        <button class="icon-btn del" data-action="delete" title="Apagar" aria-label="Apagar caderno">${ICON.trash}</button>
      </div>
      <div class="meta"><b>${esc(n.title)}</b><small>${ago(n.updated_at)}</small></div>
    </div>`).join('');
  updateEmpty(list.length);
}

async function showWall() {
  finishEdit();
  flushWord();
  toggleTools(false);
  state.nb = null;
  document.title = 'Nootebook';
  setView('wall');
  try { state.notebooks = await api('GET', '/api/notebooks'); }
  catch (e) { toast(e.message, true); }
  renderWall();
}

$('#grid').addEventListener('click', e => {
  const card = e.target.closest('.nb');
  if (!card) return;
  const actionEl = e.target.closest('[data-action]');
  const action = actionEl ? actionEl.dataset.action : null;
  const nb = state.notebooks.find(n => n.id === +card.dataset.id);
  if (!nb) return;
  if (action === 'edit') return openNbModal(nb);
  if (action === 'delete') return confirmDelete(nb, card);
  location.hash = '#/c/' + nb.id;
});
$('#grid').addEventListener('keydown', e => {
  if ((e.key === 'Enter' || e.key === ' ') && e.target.classList.contains('nb')) { e.preventDefault(); e.target.click(); }
});
$('#search').addEventListener('input', e => { state.filter = e.target.value; renderWall(); });
$('#newBtn').addEventListener('click', () => openNbModal());

/* ---------- modal: criar / editar ---------- */
let modalNb = null, modalColor = PALETTE[0].hex, modalPages = DEFAULT_PAGES, modalFont = DEFAULT_FONT;

function openNbModal(nb) {
  modalNb = nb || null;
  modalColor = nb ? nb.color : PALETTE[state.notebooks.length % PALETTE.length].hex;
  modalPages = nb ? nb.pages : DEFAULT_PAGES;
  modalFont = nb ? nb.font : store.get('font', DEFAULT_FONT);
  if (!FONTS[modalFont]) modalFont = DEFAULT_FONT;
  $('#nbModalTitle').textContent = nb ? 'Editar caderno' : 'Novo caderno';
  $('#nbSubmit').textContent = nb ? 'Salvar' : 'Criar';
  $('#nbTitle').value = nb ? nb.title : '';
  renderSwatches(); renderChips(); renderFontChips(); updatePreview();
  $('#nbModal').hidden = false;
  setTimeout(() => $('#nbTitle').focus(), 60);
}
function renderSwatches() {
  $('#swatches').innerHTML = PALETTE.map(c =>
    `<button type="button" class="swatch${c.hex === modalColor ? ' active' : ''}" style="--c:${c.hex}" data-hex="${c.hex}" title="${esc(c.name)}" aria-label="${esc(c.name)}"></button>`).join('');
}
function renderChips() {
  const min = modalNb ? modalNb.min_pages : 2;
  const opts = Array.from(new Set(PAGE_OPTIONS.concat([modalPages]))).sort((a, b) => a - b);
  $('#chips').innerHTML = opts.map(p =>
    `<button type="button" class="chip${p === modalPages ? ' active' : ''}" data-pages="${p}"${p < min ? ' disabled' : ''}>${p}</button>`).join('');
  const locked = !!modalNb && modalNb.last_page > 0 && opts.some(p => p < min);
  $('#pagesHint').hidden = !locked;
  $('#pagesHint').textContent = locked ? `Há anotações até a página ${modalNb.last_page}.` : '';
}
function renderFontChips() {
  $('#fontChips').innerHTML = Object.keys(FONTS).map(k =>
    `<button type="button" class="chip font-chip${k === modalFont ? ' active' : ''}" data-font="${k}" style="font-family:${esc(FONTS[k].css)}">${esc(FONTS[k].name)}</button>`).join('');
}
function updatePreview() {
  $('#preview').innerHTML = coverHTML(modalColor);
}
$('#swatches').addEventListener('click', e => {
  const b = e.target.closest('.swatch'); if (!b) return;
  modalColor = b.dataset.hex; renderSwatches(); updatePreview();
});
$('#chips').addEventListener('click', e => {
  const b = e.target.closest('.chip'); if (!b || b.disabled) return;
  modalPages = +b.dataset.pages; renderChips(); updatePreview();
});
$('#fontChips').addEventListener('click', e => {
  const b = e.target.closest('.chip'); if (!b) return;
  modalFont = b.dataset.font; renderFontChips();
});
$('#nbForm').addEventListener('submit', async e => {
  e.preventDefault();
  const btn = $('#nbSubmit'); btn.disabled = true;
  const body = { title: $('#nbTitle').value.trim() || 'Sem título', color: modalColor, pages: modalPages, font: modalFont };
  try {
    if (modalNb) { await api('PATCH', '/api/notebooks/' + modalNb.id, body); toast('Caderno salvo'); }
    else { await api('POST', '/api/notebooks', body); store.set('font', modalFont); toast('Caderno criado'); }
    closeModals();
    state.notebooks = await api('GET', '/api/notebooks');
    renderWall();
  } catch (err) { toast(err.message, true); }
  finally { btn.disabled = false; }
});

/* ---------- modal: apagar ---------- */
let pendingDelete = null;
function confirmDelete(nb, card) {
  pendingDelete = { nb, card };
  $('#confirmText').innerHTML = `“${esc(nb.title)}” e tudo o que foi escrito nele serão apagados.`;
  $('#confirmModal').hidden = false;
  setTimeout(() => $('#confirmCancel').focus(), 60);
}
$('#confirmOk').addEventListener('click', async () => {
  const pd = pendingDelete; if (!pd) return;
  closeModals();
  try {
    await api('DELETE', '/api/notebooks/' + pd.nb.id);
    state.notebooks = state.notebooks.filter(n => n.id !== pd.nb.id);
    pd.card.classList.add('removing');
    setTimeout(() => { pd.card.remove(); updateEmpty($('#grid').children.length); }, 350);
    toast('Caderno apagado');
  } catch (err) { toast(err.message, true); }
});
function closeModals() {
  $('#nbModal').hidden = true; $('#confirmModal').hidden = true;
  pendingDelete = null;
}
$$('.backdrop').forEach(bd => bd.addEventListener('mousedown', e => { if (e.target === bd) closeModals(); }));
$$('[data-close]').forEach(b => b.addEventListener('click', closeModals));

/* ---------- caderno aberto ---------- */
async function openNotebook(id) {
  finishEdit();
  let data;
  try { data = await api('GET', '/api/notebooks/' + id); }
  catch (e) { toast(e.message, true); location.hash = '#/'; return; }
  state.nb = data.notebook;
  state.lines = new Map(data.lines.map(l => [key(l.page, l.line), { text: l.text, ink: l.ink }]));
  state.strokes = new Map();
  for (const st of data.strokes) pageStrokes(st.page).push({ key: ++strokeSeq, id: st.id, page: st.page, ink: st.ink, data: st.data });
  inkHistory = []; wordGroup = null;
  state.spread = clamp(+store.get('spread:' + id, 0) || 0, 0, state.nb.pages / 2 - 1);
  document.title = state.nb.title + ' — Nootebook';
  $('#bookTitle').textContent = state.nb.title;
  $('#book-view').style.setProperty('--cover', state.nb.color);
  applyFont(state.nb.font);
  renderFontMenu();
  setMode(state.mode);
  setView('book');
  layout();
  renderSpread();
  setStatus('saved');
}

function layout() {
  if (state.view !== 'book') return;
  const desk = $('#desk'), bv = $('#book-view');
  const W = desk.offsetWidth, H = desk.offsetHeight;
  const pad = W < 700 ? 3 : 5;   // borda da capa em volta das folhas
  const fitW = mx => (W - 2 * mx - 2 * pad) / 2 / RATIO;
  // 100% = o caderno inteiro na tela, na altura toda, com os controles nos cantos ao lado.
  // Se nao sobrar espaco nos lados, reserva uma faixa fina em cima e embaixo para eles.
  let base = Math.min(H - 28 - 2 * pad, fitW(0));
  const roomy = (W - 2 * base * RATIO - 2 * pad) / 2 >= 130;
  if (!roomy) base = Math.min(H - 96 - 2 * pad, fitW(8));
  // ampliado, cresce ate ocupar a largura (sobra a margem dos botoes) e a mesa rola na vertical
  state.zoomMax = Math.max(1, (roomy ? fitW(60) : fitW(8)) / base);
  const z = clamp(state.zoom, 1, state.zoomMax);
  const lh = Math.floor(clamp(base * z, 240, 2400) / (LINES + 4));
  const ph = lh * (LINES + 4);
  const pw = Math.floor(ph * RATIO);
  const s = bv.style;
  s.setProperty('--page-w', pw + 'px');
  s.setProperty('--page-h', ph + 'px');
  s.setProperty('--lh', lh + 'px');
  s.setProperty('--pad', pad + 'px');
  // pouco espaco nos lados: a paginacao fica em pe, na margem
  bv.classList.toggle('tight', (W - 2 * pw - 2 * pad) / 2 < 160);
  $('#zoomVal').textContent = Math.round(z * 100) + '%';
  $('#zoomOut').disabled = z <= 1.001;
  $('#zoomIn').disabled = $('#zoomMax').disabled = z >= state.zoomMax - 0.001;
  $('#zoomFit').disabled = z <= 1.001;
  if (state.nb) updatePager();
}

function setZoom(z) {
  const desk = $('#desk');
  const mid = (desk.scrollTop + desk.clientHeight / 2) / (desk.scrollHeight || 1);   // mantem o mesmo ponto no meio
  state.zoom = clamp(Math.round(z * 100) / 100, 1, state.zoomMax || 1);
  store.set('zoom', state.zoom);
  layout();
  desk.scrollTop = mid * desk.scrollHeight - desk.clientHeight / 2;
}
$('#zoomIn').addEventListener('click', () => setZoom(Math.min(state.zoom, state.zoomMax) + 0.1));
$('#zoomOut').addEventListener('click', () => setZoom(Math.min(state.zoom, state.zoomMax) - 0.1));
$('#zoomFit').addEventListener('click', () => setZoom(1));
$('#zoomMax').addEventListener('click', () => setZoom(Infinity));
$('#desk').addEventListener('wheel', e => {
  if (!e.ctrlKey && !e.metaKey) return;
  e.preventDefault();
  setZoom(Math.min(state.zoom, state.zoomMax) - Math.sign(e.deltaY) * 0.05);
}, { passive: false });

function renderPage(p, forLeaf) {
  const nb = state.nb;
  const el = document.createElement('div');
  el.className = 'page ' + (p % 2 === 0 ? 'left' : 'right');
  el.dataset.page = p;
  let h = '<div class="margin-line"></div><div class="lines">';
  for (let i = 0; i < LINES; i++) {
    const d = state.lines.get(key(p, i));
    h += `<div class="line" data-line="${i}"><span class="txt"${d ? ` style="color:${inkHex(d.ink)}"` : ''}>${d ? esc(d.text) : ''}</span></div>`;
  }
  h += `</div>${inkLayer(p)}<div class="pnum">${p + 1}</div>`;
  if (forLeaf) {}
  else if (p % 2 === 1 && p < nb.pages - 1) h += '<div class="corner" title="Arraste para a esquerda para virar"></div>';
  else if (p % 2 === 0 && p > 0) h += '<div class="corner" title="Arraste para a direita para voltar"></div>';
  el.innerHTML = h;
  return el;
}

function renderSpread() {
  if (!state.nb) return;
  const s = state.spread;
  $('#slotL').replaceChildren(renderPage(2 * s));
  $('#slotR').replaceChildren(renderPage(2 * s + 1));
  updateStacks();
  updatePager();
  store.set('spread:' + state.nb.id, s);
}

// as bordas das folhas embaixo de cada lado engrossam/afinam conforme se avanca no caderno
function stackShadow(n, side) {
  const c = ['#e9e6de', '#faf9f5', '#e2ded5', '#f5f3ee'];
  return Array.from({ length: n }, (_, k) => `${side * (k + 1)}px ${k + 1}px 0 ${c[k % 4]}`).join(',');
}
function updateStacks() {
  const spreads = state.nb.pages / 2, f = spreads > 1 ? state.spread / (spreads - 1) : 0;
  $('#slotL').style.boxShadow = stackShadow(1 + Math.round(5 * f), -1);
  $('#slotR').style.boxShadow = stackShadow(1 + Math.round(5 * (1 - f)), 1);
}

function pagerLabel(s) {
  const sep = $('#book-view').classList.contains('tight') ? '\n' : ' ';
  return `${2 * s + 1}–${2 * s + 2}${sep}de ${state.nb.pages}`;
}
function updatePager() {
  const spreads = state.nb.pages / 2, s = state.spread;
  $('#prevBtn').disabled = s <= 0;
  $('#nextBtn').disabled = s >= spreads - 1;
  const r = $('#pageRange'); r.max = spreads - 1; r.value = s;
  $('#pageLabel').textContent = pagerLabel(s);
}

function goTo(target) {
  if (!state.nb) return Promise.resolve(false);
  target = clamp(target, 0, state.nb.pages / 2 - 1);
  if (target === state.spread || state.flipping) return Promise.resolve(false);
  finishEdit();
  flushWord();
  const from = state.spread, dir = target > from ? 1 : -1;
  if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
    state.spread = target; renderSpread(); return Promise.resolve(true);
  }
  state.flipping = true;
  const L = startLeaf(from, target, dir);
  setLeaf(L, L.C0, 0);
  state.spread = target;
  updatePager();
  playFlip(1);
  // o canto de baixo faz um arco ate o outro lado; o papel enrola mais no meio do caminho
  return animate(1000, easeInOut, t => {
    const sn = Math.sin(Math.PI * t);
    setLeaf(L, [L.W * Math.cos(Math.PI * t), L.H - L.W * CORNER_LIFT * sn], L.W * 0.15 * Math.pow(sn, 0.8));
  }).then(() => { endLeaf(L); state.flipping = false; renderSpread(); return true; });
}
const next = () => goTo(state.spread + 1);
const prev = () => goTo(state.spread - 1);

/* ---------- a folha que vira ---------- */
// Com WebGL (quase todo navegador) a folha e uma malha continua que se enrola num cilindro ao longo
// de uma linha de dobra, como papel de verdade. A dobra acompanha o canto que esta sendo puxado (pode
// ficar inclinada), a luz muda com a curvatura e a folha levantada faz sombra nas paginas de baixo.
// Sem WebGL a folha gira inteira, sem curvar.
const easeInOut = t => t < .5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;
const easeOut = t => 1 - Math.pow(1 - t, 3);
const CORNER_LIFT = 0.1;    // quanto o canto sobe no meio de uma virada automatica (fracao da largura)
const EYE = 3000;           // distancia da "camera" (perspectiva)

const FLIP_VS = `
attribute vec2 a_uv;
uniform vec2 u_size, u_fold, u_n, u_spine, u_view;
uniform vec3 u_eye;
uniform float u_r, u_dir;
varying vec2 v_uv;
varying vec3 v_n;
void main() {
  vec2 pos = a_uv * u_size;
  // coordenada da textura da frente: a pagina da esquerda tem a lombada do lado direito
  v_uv = vec2(u_dir > 0.0 ? a_uv.x : 1.0 - a_uv.x, a_uv.y);
  vec3 p = vec3(pos, 0.0);
  vec3 n = vec3(0.0, 0.0, 1.0);
  float d = dot(pos - u_fold, u_n);          // distancia da linha de dobra, do lado do canto puxado
  if (d > 0.0) {
    vec2 base = pos - d * u_n;
    float half_turn = 3.14159265 * u_r;
    if (d < half_turn) {                     // enrolado no cilindro
      float th = d / u_r;
      p = vec3(base + u_n * (u_r * sin(th)), u_r * (1.0 - cos(th)));
      n = vec3(-u_n * sin(th), cos(th));
    } else {                                 // ja passou do cilindro: volta deitado por cima
      p = vec3(base - u_n * (d - half_turn), 2.0 * u_r);
      n = vec3(0.0, 0.0, -1.0);
    }
  }
  vec3 w = vec3(u_spine.x + u_dir * p.x, u_spine.y + p.y, p.z);
  float k = u_eye.z / (u_eye.z - w.z);
  vec2 s = u_eye.xy + (w.xy - u_eye.xy) * k;
  float iw = 1.0 / k;
  gl_Position = vec4((s.x / u_view.x * 2.0 - 1.0) * iw, (1.0 - s.y / u_view.y * 2.0) * iw, -w.z / 4000.0 * iw, iw);
  v_n = vec3(n.x * u_dir, n.y, n.z);
}`;
const FLIP_FS = `
precision mediump float;
uniform sampler2D u_front, u_back;
varying vec2 v_uv;
varying vec3 v_n;
void main() {
  vec3 n = normalize(v_n);
  bool front = n.z >= 0.0;
  vec4 c = front ? texture2D(u_front, v_uv) : texture2D(u_back, vec2(1.0 - v_uv.x, v_uv.y));
  vec3 N = front ? n : -n;
  vec3 L = normalize(vec3(-0.35, -0.5, 1.0));
  float diffuse = (0.5 + 0.5 * max(dot(N, L), 0.0)) / (0.5 + 0.5 * L.z);   // papel deitado = 1
  vec3 H = normalize(L + vec3(0.0, 0.0, 1.0));
  float shine = 0.07 * pow(max(dot(N, H), 0.0), 18.0) * (1.0 - N.z * N.z) * 4.0;  // brilho so na curva
  gl_FragColor = vec4(min(c.rgb * diffuse + shine, 1.0), 1.0);
}`;

const flipGL = (() => {
  try {
    const canvas = document.createElement('canvas');
    canvas.className = 'flip-gl';
    const gl = canvas.getContext('webgl', { alpha: true, antialias: true, premultipliedAlpha: false });
    if (!gl) return null;
    const shader = (type, src) => {
      const sh = gl.createShader(type);
      gl.shaderSource(sh, src); gl.compileShader(sh);
      if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(sh));
      return sh;
    };
    const prog = gl.createProgram();
    gl.attachShader(prog, shader(gl.VERTEX_SHADER, FLIP_VS));
    gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, FLIP_FS));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog));
    gl.useProgram(prog);
    // malha da folha: bem fina para a curva ficar lisa
    const NX = 64, NY = 80, uv = new Float32Array(NX * NY * 2), idx = new Uint16Array((NX - 1) * (NY - 1) * 6);
    for (let j = 0, q = 0; j < NY; j++) for (let i = 0; i < NX; i++) { uv[q++] = i / (NX - 1); uv[q++] = j / (NY - 1); }
    for (let j = 0, q = 0; j < NY - 1; j++) for (let i = 0; i < NX - 1; i++) {
      const a = j * NX + i, b = a + 1, c = a + NX, d = c + 1;
      idx[q++] = a; idx[q++] = c; idx[q++] = b; idx[q++] = b; idx[q++] = c; idx[q++] = d;
    }
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, uv, gl.STATIC_DRAW);
    const aUv = gl.getAttribLocation(prog, 'a_uv');
    gl.enableVertexAttribArray(aUv);
    gl.vertexAttribPointer(aUv, 2, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx, gl.STATIC_DRAW);
    const u = {};
    for (const k of ['size', 'fold', 'n', 'spine', 'view', 'eye', 'r', 'dir', 'front', 'back']) u[k] = gl.getUniformLocation(prog, 'u_' + k);
    gl.uniform1i(u.front, 0); gl.uniform1i(u.back, 1);
    const tex = unit => {
      const t = gl.createTexture();
      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, t);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      return t;
    };
    const texF = tex(0), texB = tex(1);
    gl.enable(gl.DEPTH_TEST);
    $('#book-view').appendChild(canvas);
    return { gl, canvas, u, texF, texB, count: idx.length };
  } catch (e) {
    console.warn('Nootebook: folha sem WebGL, usando a virada simples.', e);
    window.__flipError = String(e && e.stack || e);
    return null;
  }
})();

/* textura da folha: a pagina desenhada num canvas, igual a da tela */
let grainImg = null;
function inkPathD(pts) {
  const p = pts.map(q => [r1(+q[0]), r1(+q[1])]);
  let path = `M${p[0][0]} ${p[0][1]}`;
  for (let i = 1; i < p.length - 1; i++) path += `Q${p[i][0]} ${p[i][1]} ${r1((p[i][0] + p[i + 1][0]) / 2)} ${r1((p[i][1] + p[i + 1][1]) / 2)}`;
  return path + `L${p[p.length - 1][0]} ${p[p.length - 1][1]}`;
}
function drawStrokeCanvas(x, s) {
  try {
    const d = s.data, c = inkHex(s.ink), w = BW * (+d.w || 1);
    x.strokeStyle = x.fillStyle = c;
    x.lineWidth = w;
    x.beginPath();
    if (d.kind === 'shape') {
      const sh = d.shape;
      if (sh.type === 'ellipse') x.ellipse(+sh.cx, +sh.cy, +sh.rx, +sh.ry, +sh.rot, 0, 2 * Math.PI);
      else {
        sh.pts.forEach((q, i) => i ? x.lineTo(+q[0], +q[1]) : x.moveTo(+q[0], +q[1]));
        if (sh.closed) x.closePath();
      }
      x.stroke();
    } else if (d.pts.length === 1) {
      x.arc(+d.pts[0][0], +d.pts[0][1], w / 2 + 0.2, 0, 2 * Math.PI);
      x.fill();
    } else x.stroke(new Path2D(inkPathD(d.pts)));
  } catch (e) {}
}
function paintPageTexture(p, W, H, scale) {
  const cv = document.createElement('canvas');
  cv.width = Math.round(W * scale); cv.height = Math.round(H * scale);
  const x = cv.getContext('2d');
  x.scale(scale, scale);
  const left = p % 2 === 0, lh = H / (LINES + 4), top = lh * 2.6;
  x.fillStyle = '#fefdfa';
  x.fillRect(0, 0, W, H);
  if (!grainImg) {
    const m = /url\("?(.*?)"?\)$/.exec(getComputedStyle($('.slot .page')).getPropertyValue('--grain').trim());
    grainImg = new Image();
    if (m) grainImg.src = m[1];
  }
  if (grainImg.complete && grainImg.naturalWidth) { x.fillStyle = x.createPattern(grainImg, 'repeat'); x.fillRect(0, 0, W, H); }
  const g = x.createLinearGradient(left ? W : 0, 0, left ? 0 : W, 0);   // sombra da lombada
  g.addColorStop(0, 'rgba(40,30,20,.13)'); g.addColorStop(0.025, 'rgba(40,30,20,.04)');
  g.addColorStop(0.07, 'rgba(40,30,20,.012)'); g.addColorStop(0.12, 'rgba(40,30,20,0)');
  x.fillStyle = g;
  x.fillRect(0, 0, W, H);
  x.fillStyle = 'rgba(206,120,120,.38)';
  x.fillRect(Math.round(W * 0.12), 0, 1, H);
  x.fillStyle = 'rgba(112,140,178,.26)';
  x.fillRect(0, top, W, 1);
  for (let i = 0; i < LINES; i++) x.fillRect(0, top + (i + 1) * lh, W, 1);
  // texto: mesma letra, tamanho e altura das linhas da tela
  const f = fontOf(state.nb.font), fs = lh * f.size;
  x.font = `400 ${fs}px ${f.css}`;
  const mt = x.measureText('Hg'), A = mt.fontBoundingBoxAscent || fs * 0.8, D = mt.fontBoundingBoxDescent || fs * 0.25;
  x.save();
  x.beginPath(); x.rect(W * 0.14, 0, W * 0.8, H); x.clip();
  for (let i = 0; i < LINES; i++) {
    const dl = state.lines.get(key(p, i));
    if (!dl) continue;
    x.fillStyle = inkHex(dl.ink);
    x.fillText(dl.text, W * 0.14, top + 1 + i * lh + lh * f.shift + (lh * 1.2 - (A + D)) / 2 + A);
  }
  x.restore();
  x.save();
  x.scale(W / PAGE_U, H / U);
  x.lineCap = x.lineJoin = 'round';
  for (const s of pageStrokes(p)) drawStrokeCanvas(x, s);
  x.restore();
  x.font = '10.5px Inter, system-ui, sans-serif';
  x.fillStyle = '#b0aba2';
  x.textAlign = left ? 'left' : 'right';
  x.fillText(String(p + 1), left ? W * 0.06 : W * 0.94, H - lh * 0.45 - 3);
  return cv;
}

// comeca uma virada: a pagina de baixo ja aparece, a folha que vira e desenhada por cima
function startLeaf(from, target, dir) {
  const W = $('#slotL').offsetWidth, H = $('#slotL').offsetHeight;
  const L = { from, target, dir, W, H, C0: [W, H], P: [W, H], R: 0 };
  if (flipGL) {
    const { gl, canvas, texF, texB } = flipGL;
    const scale = Math.min(window.devicePixelRatio || 1, 2);
    const front = paintPageTexture(dir > 0 ? 2 * from + 1 : 2 * from, W, H, scale);
    const back = paintPageTexture(dir > 0 ? 2 * target : 2 * target + 1, W, H, scale);
    gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_2D, texF);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, front);
    gl.activeTexture(gl.TEXTURE1); gl.bindTexture(gl.TEXTURE_2D, texB);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, back);
    canvas.style.display = 'block';
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const cw = Math.round(canvas.clientWidth * dpr), ch = Math.round(canvas.clientHeight * dpr);
    if (canvas.width !== cw || canvas.height !== ch) { canvas.width = cw; canvas.height = ch; }
    if (dir > 0) $('#slotR').replaceChildren(renderPage(2 * target + 1));
    else $('#slotL').replaceChildren(renderPage(2 * target));
  } else Object.assign(L, makeLeaf(from, target, dir));
  return L;
}
function endLeaf(L) {
  if (flipGL) {
    const { gl, canvas } = flipGL;
    gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
    canvas.style.display = 'none';
  } else removeLeaf(L);
}
// P = onde esta o canto puxado (medido a partir da lombada); R = raio da curva do papel
function setLeaf(L, P, R) {
  L.P = P; L.R = R;
  if (!flipGL) { L.t = clamp((L.W - P[0]) / (2 * L.W), 0, 1); paintCurl(L); return; }
  const { gl, canvas, u, count } = flipGL;
  const r = $('#slotL').getBoundingClientRect(), box = canvas.getBoundingClientRect();
  const spine = [r.right - box.left, r.top - box.top];
  const rr = Math.max(R, 0.5), C = L.C0;
  let n = [C[0] - P[0], C[1] - P[1]], fold;
  const len = Math.hypot(n[0], n[1]);
  if (len < 0.5) { n = [1, 0]; fold = [L.W + 10, 0]; }
  else {
    // a dobra fica entre o canto original e o ponteiro, um pouco para o lado do ponteiro,
    // para o canto enrolado chegar onde o ponteiro esta
    n = [n[0] / len, n[1] / len];
    const sh = Math.PI * rr / 2;
    fold = [(C[0] + P[0]) / 2 - n[0] * sh, (C[1] + P[1]) / 2 - n[1] * sh];
  }
  gl.viewport(0, 0, canvas.width, canvas.height);
  gl.uniform2f(u.size, L.W, L.H);
  gl.uniform2f(u.fold, fold[0], fold[1]);
  gl.uniform2f(u.n, n[0], n[1]);
  gl.uniform1f(u.r, rr);
  gl.uniform1f(u.dir, L.dir);
  gl.uniform2f(u.spine, spine[0], spine[1]);
  gl.uniform2f(u.view, box.width, box.height);
  gl.uniform3f(u.eye, spine[0], spine[1] + L.H * 0.4, EYE);
  gl.clearColor(0, 0, 0, 0);
  gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
  gl.drawElements(gl.TRIANGLES, count, gl.UNSIGNED_SHORT, 0);
  // sombra da folha levantada nas paginas de baixo (segue o contorno do papel)
  const lift = clamp(rr / (L.W * 0.1), 0, 1);
  canvas.style.filter = lift > 0.02
    ? `drop-shadow(0 ${(2 + 4 * lift).toFixed(1)}px ${(4 + 14 * lift).toFixed(1)}px rgba(30,20,8,${(0.32 * lift).toFixed(3)}))`
    : 'none';
}
// a folha esta presa na lombada: o canto nao pode se afastar mais que a largura da pagina do
// ponto da lombada na mesma altura, nem mais que a diagonal do outro ponto da lombada
function clampCorner(L, P) {
  const W = L.W, H = L.H, diag = Math.hypot(W, H);
  const limit = (q, s, max) => {
    const d = Math.hypot(q[0] - s[0], q[1] - s[1]);
    return d > max ? [s[0] + (q[0] - s[0]) * max / d, s[1] + (q[1] - s[1]) * max / d] : q;
  };
  return limit(limit(P, [0, L.C0[1]], W), [0, H - L.C0[1]], diag);
}
function animate(dur, ease, fn) {
  return new Promise(resolve => {
    const t0 = performance.now();
    const step = now => {
      const k = Math.min(1, (now - t0) / dur);
      fn(ease(k));
      if (k < 1) requestAnimationFrame(step); else resolve();
    };
    requestAnimationFrame(step);
  });
}
// curva do papel durante o arrasto: mais enrolado no meio da virada
const dragRadius = L => {
  const prog = clamp((L.W - L.P[0]) / (2 * L.W), 0, 1);
  return L.W * (0.05 + 0.1 * Math.sin(Math.PI * prog));
};

/* sem WebGL: a folha gira inteira (uma tira so, sem curva) */
const STRIPS = 1;
function leafAngle(t) { return clamp(180 * t, 0, 180); }
function makeLeaf(from, target, dir) {
  const pw = $('#slotL').offsetWidth, ph = $('#slotL').offsetHeight, w = pw / STRIPS;
  const frontP = dir > 0 ? 2 * from + 1 : 2 * from, backP = dir > 0 ? 2 * target : 2 * target + 1;
  const leaf = document.createElement('div');
  leaf.className = 'curl ' + (dir > 0 ? 'fwd' : 'bwd');
  const slice = (p, off, back) => {
    const face = document.createElement('div');
    face.className = 'face' + (back ? ' back' : '');
    const pg = renderPage(p, true);
    pg.style.cssText = `inset:auto;top:0;left:${-off}px;width:${pw}px;height:${ph}px`;
    const lit = document.createElement('div');
    lit.className = 'lit';
    face.append(pg, lit);
    return [face, lit];
  };
  const strips = [];
  let parent = leaf;
  for (let i = 0; i < STRIPS; i++) {
    const st = document.createElement('div');
    st.className = 'strip';
    st.style.width = w + 'px';
    st.style.left = (i === 0 ? (dir > 0 ? 0 : pw - w) : (dir > 0 ? w : -w)) + 'px';
    const [f, fl] = slice(frontP, dir > 0 ? i * w : pw - (i + 1) * w, false);
    const [b, bl] = slice(backP, dir > 0 ? pw - (i + 1) * w : i * w, true);
    st.append(f, b);
    parent.appendChild(st);
    parent = st;
    strips.push({ el: st, fl, bl });
  }
  if (dir > 0) $('#slotR').replaceChildren(renderPage(2 * target + 1));
  else $('#slotL').replaceChildren(renderPage(2 * target));
  $('#spread').append(leaf);
  return { leaf, strips, pw, w, t: 0 };
}
function removeLeaf(L) { L.leaf.remove(); }
const tint = a => `rgba(35,25,15,${a.toFixed(3)})`;
function paintCurl(L) {
  const a = leafAngle(L.t), st = L.strips[0], sign = L.dir > 0 ? -1 : 1;
  st.el.style.transform = `rotateY(${(sign * a).toFixed(3)}deg)`;
  st.fl.style.background = tint(0.34 * Math.pow(Math.min(a, 90) / 90, 1.5));
  st.bl.style.background = tint(0.34 * Math.pow(Math.min(180 - a, 90) / 90, 1.5));
}

/* som de papel: ruido filtrado com pequenos estalos, gerado na hora (nada de arquivo de audio) */
let audioCtx = null;
function playFlip(strength) {
  if (!prefs.sound) return;
  try {
    audioCtx = audioCtx || new (window.AudioContext || window.webkitAudioContext)();
    const ctx = audioCtx, dur = 0.5, n = Math.floor(ctx.sampleRate * dur), now = ctx.currentTime;
    const buf = ctx.createBuffer(1, n, ctx.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < n; i++) {
      const x = i / n, env = Math.pow(Math.sin(Math.PI * Math.min(1, x * 1.15)), 0.7);
      const crackle = Math.random() < 0.015 ? 2.5 : 1;
      d[i] = (Math.random() * 2 - 1) * env * crackle * (0.65 + 0.35 * Math.sin(x * 37));
    }
    const src = ctx.createBufferSource(); src.buffer = buf;
    const hp = ctx.createBiquadFilter(); hp.type = 'highpass'; hp.frequency.value = 600;
    const bp = ctx.createBiquadFilter(); bp.type = 'bandpass'; bp.Q.value = 0.7;
    bp.frequency.setValueAtTime(1500, now); bp.frequency.linearRampToValueAtTime(4200, now + dur);
    const g = ctx.createGain(); g.gain.value = 0.09 * strength;
    src.connect(hp).connect(bp).connect(g).connect(ctx.destination);
    src.start();
  } catch (e) {}
}

/* ---------- virar a folha arrastando ---------- */
// A folha so vira se o usuario arrastar no sentido em que ela passa:
// pagina da direita para a esquerda (avancar), pagina da esquerda para a direita (voltar).
// O canto mais perto de onde a folha foi pega acompanha o ponteiro.
const DRAG_START = 10;     // px de movimento antes de virar arrasto
const DRAG_FLIP = 0.33;    // ao soltar depois dessa fracao do caminho, a folha termina de virar
const FLICK = 0.6;         // px/ms: um arrasto rapido vira mesmo que curto
let drag = null;

// ponteiro em coordenadas da folha: x a partir da lombada, y a partir do topo
function leafPoint(L, e) {
  const r = $('#slotL').getBoundingClientRect();
  return [L.dir * (e.clientX - r.right), e.clientY - r.top];
}

function beginDrag(e) {
  finishEdit();
  flushWord();
  state.flipping = true;
  const L = startLeaf(state.spread, drag.target, drag.dir);
  const g = leafPoint(L, { clientX: drag.x, clientY: drag.y });
  L.C0 = [L.W, g[1] < L.H / 2 ? 0 : L.H];     // pegou em cima: puxa o canto de cima
  drag.L = L;
  drag.off = [L.C0[0] - g[0], L.C0[1] - g[1]];
  try { $('#spread').setPointerCapture(e.pointerId); } catch (err) {}
  document.body.classList.add('page-drag');
  const sel = window.getSelection(); if (sel) sel.removeAllRanges();
}

function moveDrag(e) {
  const d = drag, L = d.L, q = leafPoint(L, e);
  const P = clampCorner(L, [q[0] + d.off[0], q[1] + d.off[1]]);
  L.P = P;
  setLeaf(L, P, dragRadius(L));
}

function endDrag(e) {
  if (!drag || e.pointerId !== drag.id) return;
  const d = drag; drag = null;
  if (!d.L) return;
  document.body.classList.remove('page-drag');
  const L = d.L;
  const recent = e.timeStamp - d.t < 100;
  const vx = recent ? -d.dir * d.vx : 0;   // positivo = no sentido da virada
  const prog = (L.W - L.P[0]) / (2 * L.W);
  const complete = e.type !== 'pointercancel' && vx > -FLICK && (prog > DRAG_FLIP || vx > FLICK);
  const P0 = L.P.slice(), R0 = L.R, P1 = complete ? [-L.W, L.C0[1]] : L.C0.slice();
  if (complete) playFlip(0.8);
  animate(160 + 650 * Math.hypot(P1[0] - P0[0], P1[1] - P0[1]) / (2 * L.W), easeOut, k => {
    setLeaf(L, clampCorner(L, [P0[0] + (P1[0] - P0[0]) * k, P0[1] + (P1[1] - P0[1]) * k]), R0 * (1 - k));
  }).then(() => {
    endLeaf(L);
    if (complete) state.spread = d.target;
    state.flipping = false;
    renderSpread();
  });
}

$('#spread').addEventListener('pointerdown', e => {
  if (state.flipping || !state.nb || !e.isPrimary || (e.pointerType === 'mouse' && e.button !== 0)) return;
  const page = e.target.closest('.slot .page');
  if (!page) return;
  if (e.pointerType === 'pen' && !penSeen) { penSeen = true; document.body.classList.add('pen-user'); }
  const drawing = state.mode !== 'text' || e.pointerType === 'pen';
  if (drawing && e.pointerType === 'touch' && penSeen) return;   // e a palma da mao apoiada
  if (drawing && !e.target.closest('.corner')) { startPen(e, page); return; }
  // na linha em edicao, arrastar sobre o texto seleciona; so a parte vazia da linha vira a folha
  const inp = e.target.closest('.line-input');
  if (inp && inp.value) {
    const cs = getComputedStyle(inp);
    measure.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    if (e.clientX - inp.getBoundingClientRect().left < measure.measureText(inp.value).width + 12) return;
  }
  const dir = page.classList.contains('right') ? 1 : -1;
  const target = state.spread + dir;
  if (target < 0 || target > state.nb.pages / 2 - 1) return;
  drag = { id: e.pointerId, x: e.clientX, y: e.clientY, dir, target, L: null,
           lastX: e.clientX, t: e.timeStamp, vx: 0 };
});
document.addEventListener('pointermove', e => {
  if (pen && e.pointerId === pen.id) { e.preventDefault(); movePen(e); return; }
  if (!drag || e.pointerId !== drag.id) return;
  const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
  if (!drag.L) {
    if (Math.hypot(dx, dy) < DRAG_START) return;
    // movimento vertical ou no sentido contrario: nao e para virar
    if (Math.abs(dx) < Math.abs(dy) * 1.2 || Math.sign(dx) !== -drag.dir) { drag = null; return; }
    beginDrag(e);
  }
  e.preventDefault();
  const dt = e.timeStamp - drag.t;
  if (dt > 0) { drag.vx = (e.clientX - drag.lastX) / dt; drag.lastX = e.clientX; drag.t = e.timeStamp; }
  moveDrag(e);
});
const endPointer = e => { if (pen && e.pointerId === pen.id) endPen(e); else endDrag(e); };
document.addEventListener('pointerup', endPointer);
document.addEventListener('pointercancel', endPointer);

/* ---------- desenho a mao livre ---------- */
// Coordenadas do desenho: a altura da pagina vale U unidades (a largura, PAGE_U),
// entao o desenho acompanha o tamanho da tela sem distorcer.
const SVGNS = 'http://www.w3.org/2000/svg';
const U = 1000;
const PAGE_U = Math.round(RATIO * U);
const LH_U = U / (LINES + 4);              // altura de uma linha da pauta
const BW = 2.6;                            // espessura do traco
const ruleY = i => (3.6 + i) * LH_U;       // risco da pauta embaixo da linha i
let strokeSeq = 0, inkHistory = [], pen = null, wordGroup = null, suppressClickUntil = 0, penSeen = false;

const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1]);
const r1 = v => Math.round(v * 10) / 10;
function pathLen(pts, closed) {
  let s = 0;
  for (let i = 1; i < pts.length; i++) s += dist(pts[i - 1], pts[i]);
  return closed && pts.length > 1 ? s + dist(pts[pts.length - 1], pts[0]) : s;
}
function bboxOf(pts) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const p of pts) { x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]); x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1]); }
  return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
}
function segDist(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1], L = dx * dx + dy * dy;
  const t = L ? clamp(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L, 0, 1) : 0;
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
}
function median(a) {
  const s = a.slice().sort((x, y) => x - y), m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
function quantile(a, q) {
  const s = a.slice().sort((x, y) => x - y);
  return s[clamp(Math.round(q * (s.length - 1)), 0, s.length - 1)];
}
// pontos igualmente espacados ao longo do traco
function resample(pts, step, closed) {
  if (pts.length < 2) return pts.map(p => [p[0], p[1]]);
  const src = closed ? pts.concat([pts[0]]) : pts;
  const out = [[src[0][0], src[0][1]]];
  let acc = 0;
  for (let i = 1; i < src.length; i++) {
    let a = src[i - 1];
    const b = src[i];
    let d = dist(a, b);
    while (acc + d >= step) {
      const t = (step - acc) / d;
      a = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
      out.push(a);
      d = dist(a, b); acc = 0;
    }
    acc += d;
  }
  if (closed) { if (out.length > 1 && dist(out[out.length - 1], out[0]) < step / 2) out.pop(); }
  else if (dist(out[out.length - 1], src[src.length - 1]) > step / 4) out.push([src[src.length - 1][0], src[src.length - 1][1]]);
  return out;
}
function resampleN(pts, n, closed) {
  return resample(pts, Math.max(pathLen(pts, closed) / n, 0.01), closed);
}
// Ramer-Douglas-Peucker: tira pontos que nao mudam o desenho
function simplify(pts, eps) {
  if (pts.length < 3) return pts;
  const keep = new Uint8Array(pts.length); keep[0] = keep[pts.length - 1] = 1;
  const stack = [[0, pts.length - 1]];
  while (stack.length) {
    const [a, b] = stack.pop();
    let best = -1, bd = eps;
    for (let i = a + 1; i < b; i++) { const d = segDist(pts[i], pts[a], pts[b]); if (d > bd) { bd = d; best = i; } }
    if (best > 0) { keep[best] = 1; stack.push([a, best], [best, b]); }
  }
  return pts.filter((_, i) => keep[i]);
}

/* --- escrita: traco mais liso, sem perder o jeito da letra --- */
function smoothInk(raw) {
  let pts = resample(raw, 2);
  if (pts.length < 4) return pts.map(p => [r1(p[0]), r1(p[1])]);
  for (let pass = 0; pass < 3; pass++) {
    const out = [pts[0]];
    for (let i = 1; i < pts.length - 1; i++)
      out.push([(pts[i - 1][0] + 2 * pts[i][0] + pts[i + 1][0]) / 4, (pts[i - 1][1] + 2 * pts[i][1] + pts[i + 1][1]) / 4]);
    out.push(pts[pts.length - 1]);
    pts = out;
  }
  return simplify(pts, 0.3).map(p => [r1(p[0]), r1(p[1])]);
}

/* --- formas: reconhece e entrega a versao "passada a limpo" --- */
const DEG = Math.PI / 180;
function snapAngle(a, tol) {
  const q = Math.round(a / (Math.PI / 4)) * (Math.PI / 4);
  const t = Math.abs(Math.round(q / (Math.PI / 2)) * (Math.PI / 2) - q) < 1e-6 ? tol : tol * 0.75;
  return Math.abs(a - q) < t ? q : a;
}
function fitLine(pts) {   // centro e direcao principal (PCA)
  let mx = 0, my = 0;
  for (const p of pts) { mx += p[0]; my += p[1]; }
  mx /= pts.length; my /= pts.length;
  let sxx = 0, syy = 0, sxy = 0;
  for (const p of pts) { const dx = p[0] - mx, dy = p[1] - my; sxx += dx * dx; syy += dy * dy; sxy += dx * dy; }
  const ang = 0.5 * Math.atan2(2 * sxy, sxx - syy);
  return { c: [mx, my], d: [Math.cos(ang), Math.sin(ang)], sxx, syy, sxy, n: pts.length };
}
function intersect(l1, l2) {
  const det = l1.d[0] * l2.d[1] - l1.d[1] * l2.d[0];
  if (Math.abs(det) < 0.15) return null;   // quase paralelas
  const t = ((l2.c[0] - l1.c[0]) * l2.d[1] - (l2.c[1] - l1.c[1]) * l2.d[0]) / det;
  return [l1.c[0] + t * l1.d[0], l1.c[1] + t * l1.d[1]];
}
function project(p, l) {
  const t = (p[0] - l.c[0]) * l.d[0] + (p[1] - l.c[1]) * l.d[1];
  return [l.c[0] + t * l.d[0], l.c[1] + t * l.d[1]];
}
// cantos = pontos onde a direcao do traco muda de repente
function findCorners(pts, closed) {
  const n = pts.length, k = 2, turn = new Array(n).fill(0);
  for (let i = 0; i < n; i++) {
    if (!closed && (i < k || i >= n - k)) continue;
    const a = pts[(i - k + n) % n], b = pts[i], c = pts[(i + k) % n];
    const a1 = Math.atan2(b[1] - a[1], b[0] - a[0]), a2 = Math.atan2(c[1] - b[1], c[0] - b[0]);
    let d = Math.abs(a2 - a1); if (d > Math.PI) d = 2 * Math.PI - d;
    turn[i] = d;
  }
  const out = [];
  for (let i = 0; i < n; i++) {
    if (turn[i] < 30 * DEG) continue;
    let isMax = true;
    for (let j = -3; j <= 3 && isMax; j++) {
      if (!j) continue;
      const q = closed ? (i + j + n) % n : i + j;
      if (q < 0 || q >= n) continue;
      if (turn[q] > turn[i] || (turn[q] === turn[i] && j < 0)) isMax = false;
    }
    if (isMax) out.push(i);
  }
  return out;
}
// lados retos entre os cantos; os vertices sao os cruzamentos dos lados
function polyFromCorners(pts, corners, closed) {
  const n = pts.length, segs = [];
  const count = closed ? corners.length : corners.length + 1;
  for (let s = 0; s < count; s++) {
    const a = closed ? corners[s] : (s === 0 ? 0 : corners[s - 1]);
    const b = closed ? corners[(s + 1) % corners.length] : (s === corners.length ? n - 1 : corners[s]);
    const len = closed ? (b - a + n) % n || n : b - a;
    const cut = Math.floor(len * 0.18), seg = [];
    for (let t = cut; t <= len - cut; t++) seg.push(pts[(a + t) % n]);
    if (seg.length < 2) { seg.length = 0; seg.push(pts[a], pts[b % n]); }
    segs.push(fitLine(seg));
  }
  const verts = [];
  if (closed) {
    for (let s = 0; s < segs.length; s++) {
      const prev = segs[(s - 1 + segs.length) % segs.length];
      verts.push(intersect(prev, segs[s]) || pts[corners[s]]);
    }
  } else {
    verts.push(project(pts[0], segs[0]));
    for (let s = 1; s < segs.length; s++) verts.push(intersect(segs[s - 1], segs[s]) || pts[corners[s - 1]]);
    verts.push(project(pts[n - 1], segs[segs.length - 1]));
  }
  return verts;
}
function dropFlat(vs) {
  vs = vs.slice();
  for (let i = 0; vs.length > 3 && i < vs.length;) {
    if (interiorAngle(vs, i) > 155 * DEG) vs.splice(i, 1); else i++;
  }
  return vs;
}
function polyError(pts, verts, closed) {
  let sum = 0;
  for (const p of pts) {
    let best = Infinity;
    const m = closed ? verts.length : verts.length - 1;
    for (let i = 0; i < m; i++) best = Math.min(best, segDist(p, verts[i], verts[(i + 1) % verts.length]));
    sum += best;
  }
  return sum / pts.length;
}
function solve(M, y) {   // eliminacao de Gauss com pivoteamento
  const n = y.length, A = M.map((r, i) => r.concat([y[i]]));
  for (let c = 0; c < n; c++) {
    let p = c;
    for (let r = c + 1; r < n; r++) if (Math.abs(A[r][c]) > Math.abs(A[p][c])) p = r;
    if (Math.abs(A[p][c]) < 1e-12) return null;
    [A[c], A[p]] = [A[p], A[c]];
    for (let r = 0; r < n; r++) {
      if (r === c) continue;
      const f = A[r][c] / A[c][c];
      for (let k = c; k <= n; k++) A[r][k] -= f * A[c][k];
    }
  }
  return A.map((r, i) => r[n] / r[i]);
}
function fitEllipse(pts) {
  const f = fitLine(pts), rot = Math.atan2(f.d[1], f.d[0]);
  const co = Math.cos(-rot), si = Math.sin(-rot);
  const loc = pts.map(p => { const x = p[0] - f.c[0], y = p[1] - f.c[1]; return [x * co - y * si, x * si + y * co]; });
  const sc = Math.sqrt(loc.reduce((s, q) => s + q[0] * q[0] + q[1] * q[1], 0) / loc.length) || 1;   // escala para estabilidade
  const M = [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], y = [0, 0, 0, 0];
  for (const [u0, v0] of loc) {
    const u = u0 / sc, v = v0 / sc, r = [u * u, v * v, u, v];
    for (let i = 0; i < 4; i++) { y[i] += r[i]; for (let j = 0; j < 4; j++) M[i][j] += r[i] * r[j]; }
  }
  const sol = solve(M, y);
  if (!sol || sol[0] <= 0 || sol[1] <= 0) return null;
  const [A, B, C, D] = sol, u0 = -C / (2 * A), v0 = -D / (2 * B), K = 1 + A * u0 * u0 + B * v0 * v0;
  if (K <= 0) return null;
  const rx = Math.sqrt(K / A) * sc, ry = Math.sqrt(K / B) * sc;
  const cx = f.c[0] + (u0 * Math.cos(rot) - v0 * Math.sin(rot)) * sc;
  const cy = f.c[1] + (u0 * Math.sin(rot) + v0 * Math.cos(rot)) * sc;
  let err = 0;
  for (const [u, v] of loc) err += Math.abs(Math.hypot((u - u0 * sc) / rx, (v - v0 * sc) / ry) - 1);
  return { cx, cy, rx, ry, rot, err: err / loc.length };
}
// tira o tremido antes de procurar cantos (sem arredondar demais as quinas)
function smoothPts(pts, closed, passes) {
  const n = pts.length;
  for (let k = 0; k < passes; k++) {
    pts = pts.map((p, i) => {
      if (!closed && (i === 0 || i === n - 1)) return p;
      const a = pts[(i - 1 + n) % n], b = pts[(i + 1) % n];
      return [(a[0] + 2 * p[0] + b[0]) / 4, (a[1] + 2 * p[1] + b[1]) / 4];
    });
  }
  return pts;
}
const centroid = vs => [vs.reduce((s, v) => s + v[0], 0) / vs.length, vs.reduce((s, v) => s + v[1], 0) / vs.length];
const rotAround = (p, c, a) => {
  const x = p[0] - c[0], y = p[1] - c[1], co = Math.cos(a), si = Math.sin(a);
  return [c[0] + x * co - y * si, c[1] + x * si + y * co];
};
const cv = a => { const m = a.reduce((s, v) => s + v, 0) / a.length; return Math.sqrt(a.reduce((s, v) => s + (v - m) ** 2, 0) / a.length) / (m || 1); };
function interiorAngle(vs, i) {
  const a = vs[(i - 1 + vs.length) % vs.length], b = vs[i], c = vs[(i + 1) % vs.length];
  const u = [a[0] - b[0], a[1] - b[1]], v = [c[0] - b[0], c[1] - b[1]];
  return Math.acos(clamp((u[0] * v[0] + u[1] * v[1]) / (Math.hypot(...u) * Math.hypot(...v) || 1), -1, 1));
}
// orientacao media dos lados, de 0 a 90 graus (serve para retangulos)
function quarterOrientation(vs) {
  let sx = 0, sy = 0;
  for (let i = 0; i < vs.length; i++) {
    const a = vs[i], b = vs[(i + 1) % vs.length], ang = Math.atan2(b[1] - a[1], b[0] - a[0]), w = dist(a, b);
    sx += w * Math.cos(4 * ang); sy += w * Math.sin(4 * ang);
  }
  return Math.atan2(sy, sx) / 4;
}
function snapEdgesToAxes(vs, closed) {
  vs = vs.map(v => v.slice());
  const m = closed ? vs.length : vs.length - 1;
  for (let i = 0; i < m; i++) {
    const a = vs[i], b = vs[(i + 1) % vs.length], ang = Math.atan2(b[1] - a[1], b[0] - a[0]);
    const off = ((ang % (Math.PI / 2)) + Math.PI / 2) % (Math.PI / 2);
    if (Math.min(off, Math.PI / 2 - off) > 6 * DEG) continue;
    if (Math.abs(Math.sin(ang)) < 0.5) { const y = (a[1] + b[1]) / 2; a[1] = b[1] = y; }
    else { const x = (a[0] + b[0]) / 2; a[0] = b[0] = x; }
  }
  return vs;
}
function regularPolygon(c, R, n, phase) {
  return Array.from({ length: n }, (_, k) => [c[0] + R * Math.cos(phase + k * 2 * Math.PI / n), c[1] + R * Math.sin(phase + k * 2 * Math.PI / n)]);
}
function tidyPolygon(vs) {
  const n = vs.length, c = centroid(vs);
  const sides = vs.map((v, i) => dist(v, vs[(i + 1) % n]));
  if (n === 4 && vs.every((_, i) => Math.abs(interiorAngle(vs, i) - Math.PI / 2) < 16 * DEG)) {
    let th = quarterOrientation(vs);
    if (Math.abs(th) < 8 * DEG) th = 0;
    else if (Math.abs(Math.abs(th) - 45 * DEG) < 6 * DEG) th = Math.sign(th) * 45 * DEG;
    const loc = vs.map(v => rotAround(v, c, -th));
    let w = 0, h = 0;
    for (let i = 0; i < 4; i++) {
      const a = loc[i], b = loc[(i + 1) % 4];
      if (Math.abs(b[0] - a[0]) > Math.abs(b[1] - a[1])) w += Math.abs(b[0] - a[0]) / 2; else h += Math.abs(b[1] - a[1]) / 2;
    }
    if (!w || !h) return snapEdgesToAxes(vs, true);
    if (Math.abs(w - h) / Math.max(w, h) < 0.12) w = h = (w + h) / 2;   // quadrado
    return [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]]
      .map(p => rotAround([c[0] + p[0], c[1] + p[1]], c, th));
  }
  if (n === 3) {
    if (Math.max(...sides) / Math.min(...sides) < 1.18) {   // equilatero
      const R = vs.reduce((s, v) => s + dist(v, c), 0) / 3;
      let ph = Math.atan2(vs[0][1] - c[1], vs[0][0] - c[0]);
      const step = 120 * DEG, base = -90 * DEG;           // ponta para cima = base reta
      for (const t of [base, base + 60 * DEG]) {
        const k = Math.round((ph - t) / step), cand = t + k * step;
        if (Math.abs(ph - cand) < 10 * DEG) { ph = cand; break; }
      }
      return regularPolygon(c, R, 3, ph);
    }
    for (let i = 0; i < 3; i++) {                            // triangulo retangulo
      if (Math.abs(interiorAngle(vs, i) - Math.PI / 2) > 12 * DEG) continue;
      const V = vs[i], A = vs[(i + 2) % 3], B = vs[(i + 1) % 3];
      let th = quarterOrientation([A, V, B, V]);
      if (Math.abs(th) < 8 * DEG) th = 0;
      const d1 = [Math.cos(th), Math.sin(th)], d2 = [-Math.sin(th), Math.cos(th)];
      const pr = (P, d) => { const t = (P[0] - V[0]) * d[0] + (P[1] - V[1]) * d[1]; return [V[0] + t * d[0], V[1] + t * d[1]]; };
      const useA1 = Math.abs((A[0] - V[0]) * d1[0] + (A[1] - V[1]) * d1[1]) > Math.abs((A[0] - V[0]) * d2[0] + (A[1] - V[1]) * d2[1]);
      const out = vs.slice();
      out[(i + 2) % 3] = pr(A, useA1 ? d1 : d2);
      out[(i + 1) % 3] = pr(B, useA1 ? d2 : d1);
      return out;
    }
    return snapEdgesToAxes(vs, true);
  }
  const radii = vs.map(v => dist(v, c));
  if (n >= 5 && cv(radii) < 0.12 && cv(sides) < 0.16) {     // pentagono, hexagono... regulares
    const R = radii.reduce((s, v) => s + v, 0) / n;
    let ph = Math.atan2(vs[0][1] - c[1], vs[0][0] - c[0]);
    const step = 2 * Math.PI / n;
    for (const t of [-90 * DEG, -90 * DEG + step / 2]) {
      const k = Math.round((ph - t) / step), cand = t + k * step;
      if (Math.abs(ph - cand) < 9 * DEG) { ph = cand; break; }
    }
    return regularPolygon(c, R, n, ph);
  }
  return snapEdgesToAxes(vs, true);
}
// pontas de linhas encostam em cantos de formas ja desenhadas, se estiverem perto
function snapEnds(verts, page) {
  const anchors = [];
  for (const s of pageStrokes(page)) {
    if (s.data.kind !== 'shape' || s.data.shape.type !== 'poly') continue;
    anchors.push(...s.data.shape.pts);
  }
  if (!anchors.length) return verts;
  const out = verts.map(v => v.slice());
  for (const i of [0, out.length - 1]) {
    let best = null, bd = 11;
    for (const a of anchors) { const d = dist(a, out[i]); if (d < bd) { bd = d; best = a; } }
    if (best) out[i] = best.slice();
  }
  return out;
}
function recognize(raw, page) {
  if (raw.length < 3) return null;
  const pts = resample(raw, 2.5);
  if (pts.length < 6) return null;
  const bb = bboxOf(pts), diag = Math.hypot(bb.w, bb.h), len = pathLen(pts);
  if (diag < 1.8 * LH_U) return null;                      // pequeno: e escrita, nao forma
  const a = pts[0], b = pts[pts.length - 1], chord = dist(a, b);
  // linha reta
  if (chord > 0.85 * len) {
    let dev = 0, mean = 0;
    for (const p of pts) { const d = segDist(p, a, b); dev = Math.max(dev, d); mean += d; }
    mean /= pts.length;
    if (dev < 0.12 * chord && mean < 0.045 * chord) {
      // direcao media do traco (mais fiel que so as pontas), alinhada a 0/45/90 graus se estiver perto
      const f = fitLine(pts), mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
      let ang = Math.atan2(f.d[1], f.d[0]);
      if (Math.cos(ang - Math.atan2(b[1] - a[1], b[0] - a[0])) < 0) ang += Math.PI;
      ang = snapAngle(ang, 6 * DEG);
      const h = chord / 2, dx = Math.cos(ang) * h, dy = Math.sin(ang) * h;
      return { type: 'poly', closed: false, pts: snapEnds([[mid[0] - dx, mid[1] - dy], [mid[0] + dx, mid[1] + dy]], page) };
    }
  }
  const closed = chord < 0.22 * diag && len > 2 * diag;
  if (closed) {
    // corta o pedaco que passou do ponto de partida
    let cut = pts.length - 1, best = Infinity;
    for (let i = Math.floor(pts.length * 0.75); i < pts.length; i++) { const d = dist(pts[i], a); if (d < best) { best = d; cut = i; } }
    const ring = resampleN(pts.slice(0, cut + 1), 64, true);
    const sm = smoothPts(ring, true, 2);
    const corners = findCorners(sm, true);
    const c0 = centroid(ring), meanR = ring.reduce((s, p) => s + dist(p, c0), 0) / ring.length;
    const e = fitEllipse(ring);
    if (corners.length >= 3 && corners.length <= 8) {
      const verts = dropFlat(polyFromCorners(sm, corners, true));
      const pe = polyError(ring, verts, true) / meanR;
      // so e poligono se os lados retos encaixarem bem melhor que uma elipse (circulo tremido tem "cantos" falsos)
      if (pe < 0.075 && (!e || pe < 0.6 * e.err)) return { type: 'poly', closed: true, pts: tidyPolygon(verts) };
    }
    // com cantos marcados a elipse precisa encaixar melhor (para um quadrado torto nao virar bola)
    if (e && e.err < (corners.length >= 3 ? 0.08 : 0.16)) {
      let { rx, ry, rot } = e;
      if (Math.min(rx, ry) / Math.max(rx, ry) > 0.82) { rx = ry = (rx + ry) / 2; rot = 0; }   // circulo
      else {
        const s = snapAngle(rot, 9 * DEG);
        if (Math.abs(Math.sin(2 * s)) < 1e-6) rot = s;   // so endireita se ficar na horizontal/vertical
      }
      return { type: 'ellipse', cx: e.cx, cy: e.cy, rx, ry, rot };
    }
    return null;
  }
  // linha quebrada (L, zigue-zague, seta)
  const line = smoothPts(resampleN(pts, 64, false), false, 2);
  const corners = findCorners(line, false);
  if (corners.length >= 1 && corners.length <= 4) {
    const verts = polyFromCorners(line, corners, false);
    const segs = verts.slice(1).map((v, i) => dist(v, verts[i]));
    if (Math.min(...segs) > 0.08 * len && polyError(line, verts, false) < 0.025 * len)
      return { type: 'poly', closed: false, pts: snapEnds(snapEdgesToAxes(verts, false), page) };
  }
  return null;
}

/* --- palavras escritas a mao assentam na pauta e ficam retas --- */
function straightenWord(g) {
  const strokes = g.strokes.filter(s => pageStrokes(s.page).includes(s) && s.data.kind === 'ink');
  const pts = strokes.flatMap(s => s.data.pts);
  if (pts.length < 4) return;
  const bb = bboxOf(pts);
  if (bb.h > 2.4 * LH_U || bb.y + bb.h < ruleY(0) - LH_U) return;   // varias linhas ou fora da pauta
  const nb = Math.max(1, Math.round(bb.w / (0.45 * LH_U)));
  const bottoms = new Array(nb).fill(-Infinity), xs = new Array(nb).fill(0);
  for (const p of pts) {
    const i = Math.min(nb - 1, Math.floor((p[0] - bb.x) / (bb.w || 1) * nb));
    if (p[1] > bottoms[i]) { bottoms[i] = p[1]; xs[i] = p[0]; }
  }
  const sm = bottoms.map((y, i) => [xs[i], y]).filter(s => s[1] > -Infinity);
  let slope = 0;
  if (sm.length >= 3 && bb.w > 1.6 * LH_U) {
    const sl = [];
    for (let i = 0; i < sm.length; i++)
      for (let j = i + 1; j < sm.length; j++)
        if (sm[j][0] - sm[i][0] > 0.4 * LH_U) sl.push((sm[j][1] - sm[i][1]) / (sm[j][0] - sm[i][0]));
    if (sl.length) slope = median(sl);
  }
  let ang = Math.atan(slope);
  if (Math.abs(ang) > 12 * DEG) { ang = 0; slope = 0; }    // inclinacao grande: foi de proposito
  const cx = bb.x + bb.w / 2;
  // perto do baseline ficam as letras sem "perna" (g, p, q descem mais)
  const yb = quantile(sm.map(s => s[1] - slope * (s[0] - cx)), 0.4);
  const i = clamp(Math.round(yb / LH_U - 3.6), 0, LINES - 1);
  let dy = ruleY(i) - 1.2 - yb;
  if (Math.abs(dy) > 0.45 * LH_U) dy = 0;
  if (Math.abs(ang) < 0.8 * DEG && Math.abs(dy) < 0.8) return;
  const items = strokes.map(s => [s, s.data]);
  for (const s of strokes) {
    s.data = { ...s.data, pts: s.data.pts.map(p => { const q = rotAround(p, [cx, yb], -ang); return [r1(q[0]), r1(q[1] + dy)]; }) };
  }
  inkHistory.push({ op: 'edit', items });
  for (const s of strokes) {
    const el = strokeEl(s);
    if (el) {
      el.style.transformOrigin = `${cx}px ${yb}px`;
      el.style.transition = 'transform .35s ease';
      el.style.transform = `translate(0px, ${dy}px) rotate(${-ang}rad)`;
      setTimeout(() => refreshStroke(s), 380);
    }
    strokeSave(s);
  }
}
function flushWord() {
  const g = wordGroup; wordGroup = null;
  if (!g) return;
  clearTimeout(g.timer);
  if (prefs.fixWriting) straightenWord(g);
}
function addToWord(s) {
  const bb = bboxOf(s.data.pts);
  const g = wordGroup;
  if (g) {
    const gapX = Math.max(g.bb.x - (bb.x + bb.w), bb.x - (g.bb.x + g.bb.w));
    const dCy = Math.abs((g.bb.y + g.bb.h / 2) - (bb.y + bb.h / 2));
    if (g.page !== s.page || gapX > 1.6 * LH_U || dCy > 1.1 * LH_U) flushWord();
  }
  if (!wordGroup) wordGroup = { page: s.page, strokes: [], bb };
  const w = wordGroup;
  w.strokes.push(s);
  const x0 = Math.min(w.bb.x, bb.x), y0 = Math.min(w.bb.y, bb.y);
  w.bb = { x: x0, y: y0, w: Math.max(w.bb.x + w.bb.w, bb.x + bb.w) - x0, h: Math.max(w.bb.y + w.bb.h, bb.y + bb.h) - y0 };
  clearTimeout(w.timer);
  w.timer = setTimeout(flushWord, 900);
}

/* --- guardar e desenhar os tracos --- */
const prefs = { fixShapes: store.get('fixShapes', true), fixWriting: store.get('fixWriting', true), sound: store.get('sound', true) };
function pageStrokes(p) {
  let a = state.strokes.get(p);
  if (!a) { a = []; state.strokes.set(p, a); }
  return a;
}
function strokeMarkup(s) {
  try { return strokeMarkupUnsafe(s); } catch (e) { return ''; }   // dado corrompido nao quebra a pagina
}
function strokeMarkupUnsafe(s) {
  const c = inkHex(s.ink), d = s.data, k = +s.key, w = (BW * (+d.w || 1)).toFixed(2);
  if (d.kind === 'shape') {
    const sh = d.shape;
    if (sh.type === 'ellipse')
      return `<ellipse data-k="${k}" class="shape" cx="${r1(+sh.cx)}" cy="${r1(+sh.cy)}" rx="${r1(+sh.rx)}" ry="${r1(+sh.ry)}" transform="rotate(${r1(+sh.rot / DEG)} ${r1(+sh.cx)} ${r1(+sh.cy)})" stroke="${c}" stroke-width="${w}"/>`;
    const pts = sh.pts.map(p => r1(+p[0]) + ',' + r1(+p[1])).join(' ');
    return `<${sh.closed ? 'polygon' : 'polyline'} data-k="${k}" class="shape" points="${pts}" stroke="${c}" stroke-width="${w}"/>`;
  }
  const p = d.pts.map(q => [r1(+q[0]), r1(+q[1])]);
  if (p.length === 1) return `<circle data-k="${k}" class="dot" cx="${p[0][0]}" cy="${p[0][1]}" r="${(w / 2 + 0.2).toFixed(2)}" fill="${c}"/>`;
  return `<path data-k="${k}" class="ink-line" d="${inkPathD(p)}" stroke="${c}" stroke-width="${w}"/>`;
}
function inkLayer(p) {
  return `<svg class="ink" viewBox="0 0 ${PAGE_U} ${U}" preserveAspectRatio="none" aria-hidden="true">${pageStrokes(p).map(strokeMarkup).join('')}</svg>`;
}
const pageSvg = p => $(`#spread .slot .page[data-page="${p}"] svg.ink`);
const strokeEl = s => { const svg = pageSvg(s.page); return svg && svg.querySelector(`[data-k="${s.key}"]`); };
function drawStroke(s, cls) {
  const svg = pageSvg(s.page);
  if (!svg) return;
  svg.insertAdjacentHTML('beforeend', strokeMarkup(s));
  if (cls) svg.lastElementChild.classList.add(cls);
}
function refreshStroke(s) {
  s.hit = null;
  const el = strokeEl(s);
  if (el) { el.insertAdjacentHTML('afterend', strokeMarkup(s)); el.remove(); }
}
function addStroke(s, cls) {
  pageStrokes(s.page).push(s);
  drawStroke(s, cls);
  strokeCreate(s);
}
function removeStroke(s) {
  const list = pageStrokes(s.page), i = list.indexOf(s);
  if (i >= 0) list.splice(i, 1);
  const el = strokeEl(s); if (el) el.remove();
  strokeDelete(s);
}
function strokeCreate(s) {
  const nid = state.nb.id, body = { page: s.page, ink: s.ink, data: s.data };
  queueSave(async () => { const r = await api('POST', `/api/notebooks/${nid}/strokes`, body); s.id = r.id; });
}
function strokeSave(s) {
  const nid = state.nb.id;
  queueSave(() => s.id ? api('PUT', `/api/notebooks/${nid}/strokes/${s.id}`, { ink: s.ink, data: s.data }) : null);
}
function strokeDelete(s) {
  const nid = state.nb.id;
  queueSave(() => s.id ? api('DELETE', `/api/notebooks/${nid}/strokes/${s.id}`).then(() => { s.id = null; }) : null);
}
// pontos para a borracha encontrar o traco
function hitPoints(s) {
  if (s.hit) return s.hit;
  const d = s.data;
  if (d.kind === 'ink') s.hit = d.pts.length > 1 ? resample(d.pts, 3) : d.pts;
  else if (d.shape.type === 'ellipse') {
    const sh = d.shape;
    s.hit = Array.from({ length: 72 }, (_, i) => rotAround([sh.cx + sh.rx * Math.cos(i * 5 * DEG), sh.cy + sh.ry * Math.sin(i * 5 * DEG)], [sh.cx, sh.cy], sh.rot));
  } else s.hit = resample(d.shape.pts, 3, d.shape.closed);
  return s.hit;
}

/* --- caneta e borracha --- */
function toUnits(e, rect) {
  return [(e.clientX - rect.left) / rect.height * U, (e.clientY - rect.top) / rect.height * U];
}
function startPen(e, page) {
  e.preventDefault();
  finishEdit();
  if (wordGroup) clearTimeout(wordGroup.timer);
  const p = +page.dataset.page, rect = page.getBoundingClientRect();
  const erase = state.mode === 'erase' || e.button === 5 || (e.buttons & 32) > 0;
  pen = { id: e.pointerId, page: p, rect, erase, raw: [], pressure: [], deleted: [], live: null, d: '' };
  try { $('#spread').setPointerCapture(e.pointerId); } catch (err) {}
  if (!erase) {
    const svg = page.querySelector('svg.ink');
    pen.live = document.createElementNS(SVGNS, 'path');
    pen.live.setAttribute('class', 'ink-line live');
    pen.live.setAttribute('stroke', inkHex(state.ink));
    pen.live.setAttribute('stroke-width', BW);
    svg.appendChild(pen.live);
  }
  movePen(e);
}
function movePen(e) {
  const evs = e.getCoalescedEvents ? e.getCoalescedEvents() : [];
  for (const ev of evs.length ? evs : [e]) {
    const pt = toUnits(ev, pen.rect);
    pt[0] = clamp(pt[0], 0, PAGE_U); pt[1] = clamp(pt[1], 0, U);
    if (pen.erase) { eraseAt(pt); continue; }
    const last = pen.raw[pen.raw.length - 1];
    if (last && dist(last, pt) < 0.6) continue;
    pen.raw.push(pt);
    if (ev.pointerType === 'pen' && ev.pressure > 0) pen.pressure.push(ev.pressure);
    pen.d += (pen.d ? 'L' : 'M') + r1(pt[0]) + ' ' + r1(pt[1]);
  }
  if (pen.live) pen.live.setAttribute('d', pen.raw.length === 1 ? pen.d + 'l0.01 0' : pen.d);
}
function eraseAt(pt) {
  const R = 8 * U / pen.rect.height;   // ~8px na tela, o tamanho do cursor
  for (const s of pageStrokes(pen.page).slice()) {
    const hp = hitPoints(s);
    let hit = hp.length === 1 && dist(hp[0], pt) < R;
    for (let i = 1; i < hp.length && !hit; i++) hit = segDist(pt, hp[i - 1], hp[i]) < R;
    if (s.data.shape && s.data.shape.closed) hit = hit || segDist(pt, hp[hp.length - 1], hp[0]) < R;
    if (hit) { removeStroke(s); pen.deleted.push(s); }
  }
}
function endPen(e) {
  const p = pen; pen = null;
  suppressClickUntil = Date.now() + 350;
  if (p.erase) {
    if (p.deleted.length) inkHistory.push({ op: 'del', strokes: p.deleted });
    return;
  }
  const raw = p.raw;
  if (!raw.length || e.type === 'pointercancel') { if (p.live) p.live.remove(); return; }
  const w = p.pressure.length ? clamp(0.55 + 0.9 * median(p.pressure), 0.6, 1.6) : undefined;
  const smooth = prefs.fixWriting ? smoothInk(raw) : resample(raw, 1.5).map(q => [r1(q[0]), r1(q[1])]);
  const shape = prefs.fixShapes ? recognize(raw, p.page) : null;
  const data = shape ? { kind: 'shape', shape, raw: smooth } : { kind: 'ink', pts: smooth };
  if (w) data.w = r1(w);
  const s = { key: ++strokeSeq, id: null, page: p.page, ink: state.ink, data };
  if (shape) {
    // a forma corrigida aparece suavemente no lugar do rabisco
    p.live.classList.add('fade-out');
    setTimeout(() => p.live.remove(), 300);
    addStroke(s, 'fade-in');
  } else {
    p.live.remove();
    addStroke(s);
    addToWord(s);
  }
  inkHistory.push({ op: 'add', s });
}
function undoInk() {
  const h = inkHistory.pop();
  if (!h) { toast('Nada para desfazer'); return; }
  if (h.op === 'add') {
    const s = h.s;
    if (s.data.kind === 'shape' && !h.unsnapped) {
      // primeiro desfaz so a correcao: volta o rabisco original
      h.unsnapped = true;
      s.data = { kind: 'ink', pts: s.data.raw, ...(s.data.w ? { w: s.data.w } : {}) };
      refreshStroke(s); strokeSave(s);
      inkHistory.push(h);
      toast('Forma original de volta');
      return;
    }
    if (wordGroup) wordGroup.strokes = wordGroup.strokes.filter(x => x !== s);
    removeStroke(s);
  } else if (h.op === 'del') {
    for (const s of h.strokes) { s.hit = null; addStroke(s); }
  } else if (h.op === 'edit') {
    for (const [s, data] of h.items) { s.data = data; refreshStroke(s); strokeSave(s); }
  }
}

/* --- ferramentas: texto, caneta, borracha --- */
const MODES = {
  text: { name: 'Texto', key: 'T', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 6h14M12 6v13"/></svg>' },
  draw: { name: 'Caneta', key: 'D', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>' },
  erase: { name: 'Borracha', key: 'E', icon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M9 20h11"/><path d="M5.6 14.6 14 6.2l4.8 4.8-8.4 8.4a2 2 0 0 1-2.8 0l-2-2a2 2 0 0 1 0-2.8Z"/></svg>' }
};
const SLIDERS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/></svg>';
function renderModes() {
  $('#modes').innerHTML = Object.entries(MODES).map(([k, m]) =>
    `<button class="mode${k === state.mode ? ' active' : ''}" data-mode="${k}" title="${m.name} (${m.key})" aria-pressed="${k === state.mode}">${m.icon}<span>${m.name}</span></button>`).join('');
  $('#fixShapes').checked = prefs.fixShapes;
  $('#fixWriting').checked = prefs.fixWriting;
  $('#sound').checked = prefs.sound;
}
function setMode(m) {
  if (!MODES[m]) return;
  if (m !== 'text') finishEdit();
  flushWord();
  state.mode = m;
  store.set('mode', m);
  const bv = $('#book-view');
  bv.classList.toggle('mode-draw', m === 'draw');
  bv.classList.toggle('mode-erase', m === 'erase');
  $('#toolsIcon').innerHTML = m === 'text' ? SLIDERS : MODES[m].icon;
  $('#toolsBtn').title = 'Configurações do caderno — ferramenta: ' + MODES[m].name;
  renderModes();
}
$('#modes').addEventListener('click', e => { const b = e.target.closest('.mode'); if (b) setMode(b.dataset.mode); });
$('#undoBtn').addEventListener('click', undoInk);
for (const id of ['fixShapes', 'fixWriting', 'sound']) {
  $('#' + id).addEventListener('change', e => { prefs[id] = e.target.checked; store.set(id, e.target.checked); });
}

/* ---------- escrita nas linhas ---------- */
function nextPos(p, l) {
  if (l < LINES - 1) return { page: p, line: l + 1 };
  if (p + 1 < state.nb.pages) return { page: p + 1, line: 0 };
  return null;
}
function prevPos(p, l) {
  if (l > 0) return { page: p, line: l - 1 };
  if (p > 0) return { page: p - 1, line: LINES - 1 };
  return null;
}

function caretFromPoint(el, x, y) {
  let node = null, offset = 0;
  try {
    if (document.caretPositionFromPoint) {
      const c = document.caretPositionFromPoint(x, y);
      if (c) { node = c.offsetNode; offset = c.offset; }
    } else if (document.caretRangeFromPoint) {
      const r = document.caretRangeFromPoint(x, y);
      if (r) { node = r.startContainer; offset = r.startOffset; }
    }
  } catch (e) {}
  return node && node.nodeType === 3 && el.contains(node) ? offset : 'end';
}

function startEdit(p, l, caret, preset) {
  if (state.flipping || !state.nb) return;
  if (state.editing) finishEdit();
  const lineEl = $(`#spread .slot .page[data-page="${p}"] .line[data-line="${l}"]`);
  if (!lineEl) return;
  const d = state.lines.get(key(p, l));
  if (d && INKS[d.ink] && d.ink !== state.ink) setInk(d.ink, false);
  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'line-input';
  input.maxLength = MAX_CHARS;
  input.autocomplete = 'off';
  input.spellcheck = true;
  input.setAttribute('aria-label', `Página ${p + 1}, linha ${l + 1}`);
  input.value = preset != null ? preset : (d ? d.text : '');
  input.style.color = inkHex(state.ink);
  lineEl.querySelector('.txt').replaceWith(input);
  lineEl.classList.add('editing');
  const ed = { p, l, input, lineEl, ink: state.ink, timer: null };
  state.editing = ed;
  input.focus({ preventScroll: true });
  lineEl.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  const len = input.value.length;
  const pos = caret === 'start' ? 0 : typeof caret === 'number' ? clamp(caret, 0, len) : len;
  try { input.setSelectionRange(pos, pos); } catch (e) {}
  input.addEventListener('input', () => { scheduleSave(ed); wrapIfNeeded(ed); });
  input.addEventListener('keydown', e => onLineKey(e, ed));
  input.addEventListener('blur', () => { if (state.editing === ed) finishEdit(); });
  if (preset != null) { scheduleSave(ed); requestAnimationFrame(() => wrapIfNeeded(ed)); }
}

function finishEdit() {
  const ed = state.editing;
  if (!ed) return;
  state.editing = null;
  clearTimeout(ed.timer);
  commitLine(ed.p, ed.l, ed.input.value, ed.ink);
  const d = state.lines.get(key(ed.p, ed.l));
  const span = document.createElement('span');
  span.className = 'txt';
  if (d) { span.textContent = d.text; span.style.color = inkHex(d.ink); }
  if (ed.input.isConnected) ed.input.replaceWith(span);
  ed.lineEl.classList.remove('editing');
}

function scheduleSave(ed) {
  clearTimeout(ed.timer);
  ed.timer = setTimeout(() => { if (state.editing === ed) commitLine(ed.p, ed.l, ed.input.value, ed.ink); }, 450);
}

function commitLine(p, l, raw, ink) {
  const text = String(raw).replace(/\s+$/, '').slice(0, MAX_CHARS);
  const k = key(p, l), cur = state.lines.get(k);
  const same = cur ? (cur.text === text && cur.ink === ink) : text === '';
  if (same) return;
  if (text) state.lines.set(k, { text, ink }); else state.lines.delete(k);
  saveLine(state.nb.id, p, l, text, ink);
}

let saveChain = Promise.resolve();
const wait = ms => new Promise(r => setTimeout(r, ms));
// tudo e salvo em ordem; se a conexao cair (ex.: Tailscale oscilando), tenta de novo algumas vezes
function queueSave(fn) {
  state.pending++;
  setStatus('saving');
  const attempt = async n => {
    try { return await fn(); }
    catch (err) {
      if (n >= 3 || !err.offline) throw err;
      await wait(800 * 2 ** n);
      return attempt(n + 1);
    }
  };
  saveChain = saveChain
    .then(() => attempt(0))
    .then(() => { state.pending--; if (!state.pending) setStatus('saved'); })
    .catch(err => { state.pending--; setStatus('error'); toast('Não foi possível salvar: ' + err.message, true); });
}
function saveLine(id, p, l, text, ink) {
  queueSave(() => api('PUT', `/api/notebooks/${id}/lines`, { page: p, line: l, text, ink }));
}

function setStatus(s) {
  $('#status').className = 'status ' + s;
  $('#nbTools').dataset.status = s;
  $('#statusText').textContent = s === 'saving' ? 'Salvando…' : s === 'error' ? 'Erro ao salvar' : 'Salvo';
}

function moveTo(pos, caret, preset) {
  if (!pos) return;
  const s = Math.floor(pos.page / 2);
  if (s === state.spread) startEdit(pos.page, pos.line, caret, preset);
  else goTo(s).then(() => startEdit(pos.page, pos.line, caret, preset));
}

function onLineKey(e, ed) {
  if (e.isComposing) return;
  const inp = ed.input;
  switch (e.key) {
    case 'Enter': e.preventDefault(); moveTo(nextPos(ed.p, ed.l), 'end'); break;
    case 'ArrowDown': e.preventDefault(); moveTo(nextPos(ed.p, ed.l), inp.selectionStart); break;
    case 'ArrowUp': e.preventDefault(); moveTo(prevPos(ed.p, ed.l), inp.selectionStart); break;
    case 'Tab': e.preventDefault(); moveTo(e.shiftKey ? prevPos(ed.p, ed.l) : nextPos(ed.p, ed.l), 'end'); break;
    case 'Backspace':
      if (inp.value === '') { e.preventDefault(); moveTo(prevPos(ed.p, ed.l), 'end'); }
      break;
    case 'Escape': e.preventDefault(); finishEdit(); break;
  }
}

// Quando a frase passa do fim da linha, a ultima palavra desce para a linha de baixo
const measure = document.createElement('canvas').getContext('2d');
function wrapIfNeeded(ed) {
  if (state.editing !== ed) return;
  const inp = ed.input, v = inp.value;
  const maxW = inp.clientWidth - 2;
  if (maxW <= 0) return;
  const cs = getComputedStyle(inp);
  measure.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
  if (measure.measureText(v).width <= maxW) return;
  if (inp.selectionStart < v.length) return;
  const nxt = nextPos(ed.p, ed.l);
  if (!nxt) return;
  const nd = state.lines.get(key(nxt.page, nxt.line));
  if (nd && nd.text) return;
  let lo = 0, hi = v.length;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (measure.measureText(v.slice(0, mid)).width <= maxW) lo = mid; else hi = mid - 1;
  }
  let cut = v.lastIndexOf(' ', lo);
  if (cut <= 0) cut = lo;
  const head = v.slice(0, cut).replace(/\s+$/, '');
  const tail = v.slice(cut).replace(/^\s+/, '');
  if (!tail) return;
  inp.value = head;
  moveTo(nxt, 'end', tail);
}

/* ---------- canetas ---------- */
function renderPens() {
  $('#pens').innerHTML = Object.keys(INKS).map(k =>
    `<button class="pen${k === state.ink ? ' active' : ''}" data-ink="${k}" style="--ink:${INKS[k].hex}" title="Caneta ${INKS[k].name}" aria-label="Caneta ${INKS[k].name}"></button>`).join('');
}
function setInk(ink, applyToLine) {
  state.ink = ink;
  store.set('ink', ink);
  $$('.pen').forEach(b => b.classList.toggle('active', b.dataset.ink === ink));
  const ed = state.editing;
  if (applyToLine && ed) {
    ed.ink = ink;
    ed.input.style.color = inkHex(ink);
    scheduleSave(ed);
    ed.input.focus();
  }
}
$('#pens').addEventListener('mousedown', e => { if (e.target.closest('.pen')) e.preventDefault(); });
$('#pens').addEventListener('click', e => { const b = e.target.closest('.pen'); if (b) setInk(b.dataset.ink, true); });

/* ---------- tipos de letra ---------- */
function applyFont(k) {
  const f = fontOf(k), s = $('#book-view').style;
  s.setProperty('--nbfont', f.css);
  s.setProperty('--fs', f.size);
  s.setProperty('--fy', f.shift);
}
function renderFontMenu() {
  const cur = state.nb ? state.nb.font : DEFAULT_FONT;
  $('#fontMenu').innerHTML = Object.keys(FONTS).map(k =>
    `<button class="font-opt${k === cur ? ' active' : ''}" role="option" aria-selected="${k === cur}" data-font="${k}">` +
    `<span style="font-family:${esc(FONTS[k].css)}">${esc(FONTS[k].name)}</span><small>${k === cur ? 'em uso' : ''}</small></button>`).join('');
}
function toggleTools(open) {
  const t = $('#nbTools');
  open = open === undefined ? !t.classList.contains('open') : open;
  t.classList.toggle('open', open);
  $('#toolsBtn').setAttribute('aria-expanded', open);
}
async function setFont(k) {
  if (!state.nb || !FONTS[k] || k === state.nb.font) return;
  const nb = state.nb, old = nb.font;
  nb.font = k;
  applyFont(k);
  renderFontMenu();
  store.set('font', k);
  if (state.editing) { state.editing.input.focus(); requestAnimationFrame(() => wrapIfNeeded(state.editing)); }
  try { await api('PATCH', '/api/notebooks/' + nb.id, { font: k }); }
  catch (err) {
    toast('Não foi possível trocar a letra: ' + err.message, true);
    if (state.nb === nb) { nb.font = old; applyFont(old); renderFontMenu(); }
  }
}
// mousedown sem foco: quem esta escrevendo continua na linha
$('#nbTools').addEventListener('mousedown', e => { if (e.target.closest('button')) e.preventDefault(); });
// no mouse o painel abre ao passar por cima; o clique fixa (e serve para telas de toque)
$('#toolsBtn').addEventListener('click', () => toggleTools());
$('#fontMenu').addEventListener('click', e => {
  const b = e.target.closest('.font-opt'); if (!b) return;
  setFont(b.dataset.font);
});
document.addEventListener('pointerdown', e => {
  if ($('#nbTools').classList.contains('open') && !e.target.closest('#nbTools')) toggleTools(false);
});

/* ---------- eventos do caderno ---------- */
$('#spread').addEventListener('click', e => {
  if (state.flipping || e.target.closest('.corner') || state.mode !== 'text' || Date.now() < suppressClickUntil) return;
  const lineEl = e.target.closest('.line');
  if (!lineEl || lineEl.closest('.curl')) return;
  const p = +lineEl.closest('.page').dataset.page, l = +lineEl.dataset.line;
  const ed = state.editing;
  if (ed && ed.p === p && ed.l === l) return;
  const txt = lineEl.querySelector('.txt');
  const caret = txt && txt.textContent ? caretFromPoint(txt, e.clientX, e.clientY) : 'end';
  startEdit(p, l, caret);
});
$('#prevBtn').addEventListener('click', prev);
$('#nextBtn').addEventListener('click', next);
$('#pageRange').addEventListener('input', e => { $('#pageLabel').textContent = pagerLabel(+e.target.value); });
$('#pageRange').addEventListener('change', e => { goTo(+e.target.value).then(ok => { if (!ok) updatePager(); }); });
$('#backBtn').addEventListener('click', () => { location.hash = '#/'; });

document.addEventListener('keydown', e => {
  const modalOpen = !$('#nbModal').hidden || !$('#confirmModal').hidden;
  if (modalOpen) { if (e.key === 'Escape') closeModals(); return; }
  if ($('#nbTools').classList.contains('open') && e.key === 'Escape') { toggleTools(false); return; }
  if (state.view === 'book' && (e.ctrlKey || e.metaKey) && !e.altKey && ['+', '=', '-', '0'].includes(e.key)) {
    e.preventDefault();
    const z = Math.min(state.zoom, state.zoomMax);
    setZoom(e.key === '0' ? 1 : e.key === '-' ? z - 0.1 : z + 0.1);
    return;
  }
  if (state.view === 'book' && !state.editing) {
    if (e.target.matches && e.target.matches('input, textarea')) return;
    const k = e.key.toLowerCase();
    if ((e.ctrlKey || e.metaKey) && k === 'z' && !e.shiftKey) { e.preventDefault(); undoInk(); return; }
    if (!e.ctrlKey && !e.metaKey && !e.altKey) {
      const m = k === 'd' ? 'draw' : k === 'e' ? 'erase' : k === 't' ? 'text' : null;
      if (m) { e.preventDefault(); setMode(m); return; }
    }
    if (e.key === 'ArrowRight' || e.key === 'PageDown') { e.preventDefault(); next(); }
    else if (e.key === 'ArrowLeft' || e.key === 'PageUp') { e.preventDefault(); prev(); }
    else if (e.key === 'Home') { e.preventDefault(); goTo(0); }
    else if (e.key === 'End') { e.preventDefault(); goTo(Infinity); }
    else if (e.key === 'Escape') { location.hash = '#/'; }
  } else if (state.view === 'wall' && e.key === '/' && !(e.target.matches && e.target.matches('input'))) {
    e.preventDefault(); $('#search').focus();
  }
});

window.addEventListener('resize', () => { if (state.view === 'book') layout(); });

document.addEventListener('visibilitychange', () => {
  const ed = state.editing;
  if (document.visibilityState === 'hidden' && ed) { clearTimeout(ed.timer); commitLine(ed.p, ed.l, ed.input.value, ed.ink); }
});
window.addEventListener('pagehide', () => {
  const ed = state.editing;
  if (!ed || !state.nb) return;
  const text = ed.input.value.replace(/\s+$/, '');
  const cur = state.lines.get(key(ed.p, ed.l));
  if (cur ? (cur.text === text && cur.ink === ed.ink) : !text) return;
  try {
    fetch(`/api/notebooks/${state.nb.id}/lines`, {
      method: 'PUT', keepalive: true, headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ page: ed.p, line: ed.l, text, ink: ed.ink })
    });
  } catch (e) {}
});

/* ---------- rotas ---------- */
function route() {
  const m = location.hash.match(/^#\/c\/(\d+)/);
  if (m) openNotebook(+m[1]); else showWall();
}
window.addEventListener('hashchange', route);
renderPens();
route();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    if _running_in_venv():
        main()
    else:
        bootstrap()
