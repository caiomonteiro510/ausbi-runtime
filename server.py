"""Ponte HTTP local entre uma interface web e o AUSBI Runtime REAL.

NÃO contém inteligência: apenas embrulha o Orchestrator já existente (um cérebro só).
    UI  ->  POST /api/turn  ->  Orchestrator.turn()  ->  PMA  ->  Gateway  ->  provedor  ->  resposta  ->  UI

- Uma ÚNICA instância de Orchestrator para toda a sessão -> o contexto (self.messages) é preservado.
- A chave vem SÓ do ambiente (o driver lê a env var configurada). Nada de segredo aqui.
- O CLI (main.py) continua independente; este server é uma interface alternativa sobre o mesmo núcleo.

Uso:
  python server.py                 # sobe o server e abre o navegador
  python server.py --no-browser    # sobe sem abrir o navegador (útil p/ testes)
"""
from __future__ import annotations

import json
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ausbi.orchestrator import Orchestrator

RUNTIME_DIR = Path(__file__).resolve().parent
UI_DIR = (RUNTIME_DIR / "ui").resolve()
HOST, PORT = "127.0.0.1", 8765

_MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ico": "image/x-icon",
}

# ── núcleo real (reusado, não reconstruído) ────────────────────────────────
orch = Orchestrator()
BOOT = orch.boot()
_turn_lock = threading.Lock()  # serializa turnos -> integridade do histórico da conversa


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj: dict) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    # ---- estáticos da UI ('/' -> index.html) ----
    def do_GET(self) -> None:
        rel = self.path.split("?", 1)[0].split("#", 1)[0].lstrip("/")
        target = UI_DIR / "index.html" if rel in ("", "index.html") else UI_DIR / rel
        try:
            target = target.resolve()
            target.relative_to(UI_DIR)  # bloqueia path traversal (../)
        except (ValueError, OSError):
            return self._json(404, {"error": "não encontrado"})
        if not target.is_file():
            return self._json(404, {"error": "não encontrado"})
        self._send(200, target.read_bytes(),
                   _MIME.get(target.suffix.lower(), "application/octet-stream"))

    # ---- ponte de conversa: UI -> Orchestrator real ----
    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/api/turn":
            return self._json(404, {"error": "não encontrado"})
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            text = (payload.get("text") or "").strip()
            profile = payload.get("profile") or None  # R1: hint de override por turno (opcional; do sistema)
        except (ValueError, json.JSONDecodeError):
            return self._json(400, {"error": "JSON inválido"})
        if not text:
            return self._json(400, {"error": "mensagem vazia"})
        with _turn_lock:  # um turno por vez -> preserva self.messages
            out = orch.turn(text, profile=profile)
        self._json(200, {"reply": out["reply"], "refs": out["refs"],
                         "profile": out.get("profile"), "error": out["error"]})

    def log_message(self, fmt: str, *args) -> None:
        print("[server]", fmt % args)


def main() -> int:
    print("AUSBI server — interface sobre o runtime real")
    print(f"  vault:     {BOOT['vault']}")
    print(f"  modelo:    {BOOT['provider']} / {BOOT['model']}  (perfil: {BOOT['profile']})")
    print(f"  identidade:{' OK' if BOOT['identity_loaded'] else ' FALTANDO ' + str(BOOT['missing'])}")
    if not BOOT["has_api_key"]:
        print(f"  AVISO: {BOOT['api_key_env']} não definida — turnos retornam erro amigável (sem crash).")
    url = f"http://{HOST}:{PORT}"
    print(f"  servindo:  {url}   (Ctrl+C encerra)")

    server = ThreadingHTTPServer((HOST, PORT), Handler)
    if "--no-browser" not in sys.argv:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nAUSBI server encerrado.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
