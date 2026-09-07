"""AUSBI — runtime provisório (CLI). Boot + REPL + persistência com confirmação.

Uso:
  python main.py             # inicia o AUSBI (conversa real; requer ANTHROPIC_API_KEY)
  python main.py --selftest  # valida identidade/memória/PMA SEM chamar o modelo
"""
from __future__ import annotations

import shlex
import sys

from ausbi.memory import select_relevant
from ausbi.orchestrator import Orchestrator

HELP = """Comandos:
  (texto)                        conversar com o AUSBI
  /modelo [<perfil>|auto]        ver/fixar o perfil (local_rapido|local_profundo|groq|anthropic; auto=padrão)
  /salvar <tipo> "<conteúdo>"    persistir (tipo: decisao|tarefa|conhecimento|evento|memoria)
  /status                        estado da sessão
  /ajuda                         esta ajuda
  /sair                          encerrar
"""


def _print_boot(info: dict) -> None:
    print("\n🤖 AUSBI v0.1 — runtime próprio")
    print(f"   vault:  {info['vault']}")
    print(f"   modelo: {info['provider']} / {info['model']}  (perfil padrão: {info['profile']})")
    if info.get("profile_override"):
        print(f"   override de sessão ativo: {info['profile_override']}  (use /modelo auto p/ limpar)")
    print(f"   identidade carregada do vault: {'sim' if info['identity_loaded'] else 'NÃO'}")
    if info["missing"]:
        print(f"   ⚠ arquivos de identidade faltando: {info['missing']}")
    if not info["has_api_key"]:
        print(f"   ⚠ {info['api_key_env']} não definida — a conversa real não funcionará até configurá-la.")
    print("   pronto. digite /ajuda para ver os comandos.\n")


def _selftest(orch: Orchestrator) -> int:
    info = orch.boot()
    print("=== SELFTEST (sem chamar o modelo) ===")
    print(f"vault:                 {info['vault']}")
    print(f"identidade carregada:  {info['identity_loaded']}  (faltando: {info['missing']})")
    print(f"Contrato de Identidade: {len(orch.identity)} caracteres")
    _, refs = select_relevant(orch.vault, "como estão os projetos ativos?", orch.cfg["orientation_files"])
    print(f"memória p/ consulta-teste: {refs}")
    prev = orch.preview_persistence("evento", "Selftest do runtime executado")
    print(f"persistência (exemplo) -> nota: {prev['nota']}")
    print("OK: identidade + memória + PMA prontos. (o modelo NÃO foi chamado)")
    return 0


def _handle_save(orch: Orchestrator, line: str) -> None:
    try:
        parts = shlex.split(line)
    except ValueError:
        print('AUSBI> uso: /salvar <tipo> "<conteúdo>"')
        return
    if len(parts) < 3:
        print('AUSBI> uso: /salvar <tipo> "<conteúdo>"  (tipo: decisao|tarefa|conhecimento|evento|memoria)')
        return
    tipo = parts[1].lower()
    conteudo = " ".join(parts[2:])
    prev = orch.preview_persistence(tipo, conteudo)
    if prev is None:
        print(f"AUSBI> tipo inválido: {tipo}")
        return
    print("\n📝 Proposta de escrita")
    print(f"   tipo:   {prev['tipo']}")
    print(f"   nota:   {prev['nota']}")
    print(f"   prévia: {prev['block'].strip()[:200]}")
    if input("Confirmo salvar? (s/n) ").strip().lower() in ("s", "sim", "y"):
        print(f"AUSBI> salvo em: {orch.commit_persistence(prev)}\n")
    else:
        print("AUSBI> não salvo.\n")


def _handle_modelo(orch: Orchestrator, line: str) -> None:
    """Comando de SISTEMA (não vai ao modelo): vê/fixa o perfil da sessão."""
    parts = line.split(maxsplit=1)
    if len(parts) == 1:  # sem argumento -> mostra estado e ajuda
        atual = orch.profile_override or f"{orch.cfg['default_profile']} (padrão)"
        print(f"AUSBI> perfil atual: {atual}")
        print(f"AUSBI> disponíveis: {', '.join(orch.cfg['profiles'])}")
        print("AUSBI> uso: /modelo <perfil>   |   /modelo auto  (voltar ao padrão)\n")
        return
    _ok, msg = orch.set_profile_override(parts[1])
    print(f"AUSBI> {msg}\n")


def main() -> int:
    orch = Orchestrator()
    if "--selftest" in sys.argv:
        return _selftest(orch)
    router_test = "--router-test" in sys.argv
    if router_test:  # liga o router SÓ nesta sessão; config.yaml permanece enabled:false
        orch.cfg.setdefault("router", {})["enabled"] = True
    _print_boot(orch.boot())
    if router_test:
        print("⚙️  MODO DE TESTE DO ROUTER — router.enabled=TRUE só nesta sessão (config.yaml segue false).")
        print("   Cada turno registra: perfil, motivo (route_reason) e tempo — na tela e em logs/turnos.jsonl.")
        print("   ⚠ Perguntas complexas escalam p/ local_profundo (qwen3:8b) e podem levar minutos.\n")
    while True:
        try:
            line = input("você> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAUSBI> até logo.")
            return 0
        if not line:
            continue
        if line in ("/sair", "/quit", "/exit"):
            print("AUSBI> sessão encerrada.")
            return 0
        if line == "/ajuda":
            print(HELP)
            continue
        if line == "/status":
            _print_boot(orch.boot())
            continue
        if line.startswith("/modelo"):
            _handle_modelo(orch, line)
            continue
        if line.startswith("/salvar"):
            _handle_save(orch, line)
            continue
        out = orch.turn(line)
        if out["refs"]:
            print(f"   (memória usada: {', '.join(out['refs'])})")
        if router_test:
            print(f"   [router-test] perfil={out['profile']}  motivo={out.get('route_reason','?')}  "
                  f"tempo={out.get('elapsed_s','?')}s")
        print(f"AUSBI> {out['reply']}\n")


if __name__ == "__main__":
    raise SystemExit(main())
