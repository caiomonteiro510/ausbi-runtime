"""Memória do vault: leitura, seleção de relevância (O4) e escrita (append-only).

Seleção v0.1 = estrutural + palavra-chave (busca semântica local vem depois).
Escrita = acrescenta um bloco datado ao fim da nota-alvo (não reescreve histórico).
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from .identity import read_note
from .adapter.pma import ContextItem

# Escopos citados na mensagem -> nota-hub a puxar como contexto.
# (Exemplo genérico — em uso real, cada projeto/área do vault ganha uma entrada aqui.)
SCOPE_HINTS = {
    "projeto-a": "03 - Projetos/Projeto A.md",
    "projeto-b": "03 - Projetos/Projeto B.md",
}


def load_orientation(vault_dir: str, files: list[str]) -> list[ContextItem]:
    items: list[ContextItem] = []
    for rel in files:
        c = read_note(vault_dir, rel)
        if c:
            items.append(ContextItem(ref=rel, content=c.strip()))
    return items


def select_relevant(vault_dir: str, query: str, orientation: list[str]) -> tuple[list[ContextItem], list[str]]:
    """Retorna (itens_de_contexto, refs_usadas)."""
    items = load_orientation(vault_dir, orientation)
    q = query.lower()
    for key, rel in SCOPE_HINTS.items():
        if key in q and all(it.ref != rel for it in items):
            c = read_note(vault_dir, rel)
            if c:
                items.append(ContextItem(ref=rel, content=c.strip()))
    return items, [it.ref for it in items]


def append_note(vault_dir: str, rel: str, block: str) -> str:
    """Acrescenta um bloco ao fim de uma nota (cria se não existir). Retorna o caminho."""
    p = Path(vault_dir) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = p.read_text(encoding="utf-8") if p.exists() else ""
    sep = "" if existing == "" or existing.endswith("\n") else "\n"
    p.write_text(existing + sep + block + "\n", encoding="utf-8")
    return str(p)


def format_persistence_block(tipo: str, conteudo: str, trace_id: str) -> str:
    hoje = date.today().isoformat()
    if tipo == "tarefa":
        return f"\n- [ ] {conteudo}  <!-- ausbi {hoje} {trace_id} -->"
    if tipo == "evento":
        return (f"\n---\n\n## {conteudo}\n\nData:\n\n{hoje}\n\n"
                f"Registrado pelo AUSBI (runtime) — trace {trace_id}.")
    if tipo == "decisao":
        return (f"\n---\n\n# {hoje} — {conteudo}\n\n"
                f"Registrado pelo AUSBI (runtime) — trace {trace_id}. Revisável.")
    if tipo == "conhecimento":
        return (f"\n---\n\n## {conteudo}\n\n"
                f"Registrado pelo AUSBI (runtime) em {hoje} — trace {trace_id}.")
    # memoria
    return f"\n\n> ({hoje}) {conteudo}  <!-- ausbi {trace_id} -->"
