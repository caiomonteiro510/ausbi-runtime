"""Router de perfis do AUSBI — seleção AUTOMÁTICA (Fase R2).

Função PURA e DETERMINÍSTICA: sem I/O, sem rede, SEM outro modelo/LLM. Decide,
quando NÃO há override explícito e o router está ligado, qual perfil LOCAL atende
o turno:
  - `local_rapido` por padrão (responsivo);           [regra 4]
  - `local_profundo` só diante de sinais FORTES de complexidade, de forma
    conservadora — porque um modelo maior costuma ser mais lento/instável em
    hardware modesto.  [regra 5]

Privacidade (regra 2): esta função NUNCA seleciona provedores externos
(groq/anthropic). Externos só chegam via override explícito, e o Orquestrador
ainda os condiciona a conectividade + credencial (regra 3). Assim, os dados do
vault ficam locais por padrão.

Fallback seguro para `local_rapido`/`default_profile` (regra 6).

Os critérios (palavras-chave e limiar de tamanho) vêm da config `router:`, com
defaults conservadores embutidos abaixo.
"""
from __future__ import annotations

from typing import Any

# Sinais FORTES de aprofundamento (defaults; a config pode sobrepor).
_DEFAULT_KEYWORDS = (
    "planeje", "planejamento", "planejar", "estratégia", "estrategia",
    "compare", "comparação", "comparacao", "análise detalhada", "analise detalhada",
    "passo a passo", "prós e contras", "pros e contras", "arquitetura",
    "algoritmo", "demonstre", "aprofunde", "detalhadamente",
)
# Alto de propósito: tamanho sozinho raramente escala (conservador).
_DEFAULT_MIN_WORDS = 80

RAPIDO = "local_rapido"
PROFUNDO = "local_profundo"


def is_strong_complexity(text: str, router_cfg: dict | None = None) -> bool:
    """Sinal FORTE e determinístico de complexidade (regra 5). Verdadeiro se houver
    palavra-chave de aprofundamento OU o texto for muito longo. Puro."""
    router_cfg = router_cfg or {}
    t = (text or "").lower()
    keywords = router_cfg.get("escalate_keywords") or _DEFAULT_KEYWORDS
    if any(k.lower() in t for k in keywords):
        return True
    min_words = int(router_cfg.get("escalate_min_words", _DEFAULT_MIN_WORDS))
    return len((text or "").split()) >= min_words


def select_profile(
    user_text: str,
    context: Any,
    cfg: dict,
    override: str | None = None,
    signals: dict | None = None,
) -> tuple[str, str]:
    """Seleção automática LOCAL. Retorna ``(profile_name, reason)``.

    Só é chamada pelo Orquestrador quando NÃO há override e o router está ligado.
    Mantém tudo local (regra 2): escolhe apenas entre local_rapido e local_profundo.
    ``override``/``signals`` fazem parte da assinatura por simetria, mas a decisão
    de override e o gate de disponibilidade de externos moram no Orquestrador.
    """
    profiles = cfg.get("profiles", {}) or {}
    router_cfg = cfg.get("router") or {}

    # regra 5: profundo só com sinal FORTE e se o perfil existir.
    if PROFUNDO in profiles and is_strong_complexity(user_text, router_cfg):
        return PROFUNDO, "auto-complexo"

    # regra 4: padrão local = rapido.
    if RAPIDO in profiles:
        return RAPIDO, "auto-rapido"

    # regra 6: fallback seguro.
    default = cfg.get("default_profile")
    if default in profiles:
        return default, "auto-fallback-default"
    return next(iter(profiles), default), "auto-fallback-primeiro"
