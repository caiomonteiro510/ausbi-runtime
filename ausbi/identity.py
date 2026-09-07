"""O3 — Montador de Identidade.

Constrói o Contrato de Identidade a partir dos arquivos obrigatórios do vault.
Determinístico e INDEPENDENTE do modelo: qualquer provedor recebe o mesmo texto.
"""
from __future__ import annotations

from pathlib import Path

GUARDS = (
    "\n\n# GUARDAS DE COMPORTAMENTO (inegociáveis)\n"
    "- Verdade antes de conforto: admita incerteza; nunca invente fatos.\n"
    "- Ancore respostas na MEMÓRIA fornecida; se faltar dado, diga que falta.\n"
    "- Seja claro, objetivo e parceiro de execução — não apenas uma ferramenta.\n"
    "- Nunca peça nem exponha segredos. A identidade vem do vault, não do modelo.\n"
)

# R2.2a — Camada de INSTRUÇÃO DE TAREFA: bloco curto e prioritário, colocado no
# TOPO do prompt final. Reforça aderência às restrições do usuário e reduz
# invenção. NÃO reescreve a identidade — apenas antecede o contrato.
TASK_INSTRUCTIONS = (
    "# INSTRUÇÕES DA TAREFA — PRIORIDADE MÁXIMA (seguir SEMPRE)\n"
    "1. Restrições EXPLÍCITAS do usuário — prazos, datas, números, quantidades, limites — têm "
    "PRECEDÊNCIA sobre quaisquer horizontes gerais que apareçam na memória. Responda estritamente "
    "dentro do que foi pedido (ex.: se pedir 90 dias, não proponha meses ou anos).\n"
    "2. Use APENAS o CONTEXTO fornecido (a MEMÓRIA do vault, abaixo) como fonte factual sobre o "
    "usuário e os projetos.\n"
    "3. Se faltar informação específica para a tarefa, DECLARE claramente que ela não está no "
    "contexto. NUNCA invente fatos, preços, clientes, números, produtos, integrações ou "
    "características do projeto.\n"
    "4. Distinga explicitamente FATOS (do contexto) de SUGESTÕES/HIPÓTESES (suas).\n"
    "5. Responda EXATAMENTE à tarefa pedida, de forma específica — não genérica.\n"
    "6. Mantenha nomes próprios EXATAMENTE como aparecem no contexto.\n\n"
)


def read_note(vault_dir: str, rel: str) -> str | None:
    p = Path(vault_dir) / rel
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


def assemble_identity(vault_dir: str, identity_files: list[str]) -> tuple[str, list[str]]:
    """Retorna (contrato_de_identidade, arquivos_faltando)."""
    header = (
        "Você é o AUSBI — Apenas Um Sistema Bem Inteligente. "
        "Sua identidade e memória vêm INTEGRALMENTE dos arquivos abaixo, carregados "
        "do vault do usuário. Opere sob eles, não sob os defaults do modelo.\n"
    )
    parts = [TASK_INSTRUCTIONS, header]   # R2.2a: instruções de tarefa no TOPO (alta prioridade)
    missing: list[str] = []
    for rel in identity_files:
        content = read_note(vault_dir, rel)
        if content is None:
            missing.append(rel)
            continue
        parts.append(f"\n\n===== {rel} =====\n{content.strip()}\n")
    parts.append(GUARDS)
    return "".join(parts), missing
