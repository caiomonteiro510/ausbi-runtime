"""PMA — Protocolo de Modelo AUSBI (contratos neutros).

Nenhum provedor conhece isto; nenhum detalhe de provedor vaza acima daqui.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextItem:
    ref: str          # origem no vault (rastreabilidade)
    content: str


@dataclass
class PMARequest:
    identity: str                                     # Contrato de Identidade (texto do vault)
    input: list[dict[str, str]]                       # mensagens [{role, content}]
    context: list[ContextItem] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)    # {max_tokens: int, ...}
    routing: dict[str, str] = field(default_factory=dict)   # {profile, sensitivity}
    trace_id: str = ""


@dataclass
class PMAResponse:
    output_text: str = ""
    model_used: dict[str, Any] = field(default_factory=dict)  # {provider, model, locality}
    usage: dict[str, Any] = field(default_factory=dict)       # {tokens_in, tokens_out}
    stop_reason: str = ""                                     # complete|length|filter|error
    error: str | None = None                                  # código normalizado ou None
    warnings: list[str] = field(default_factory=list)
