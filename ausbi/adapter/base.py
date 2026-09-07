"""Contrato do Driver de Provedor + Descritor de Capacidades.

Para plugar um modelo novo (ex.: Ollama), implemente ProviderDriver e registre-o
no gateway. É a ÚNICA peça que muda ao adicionar um provedor — o núcleo não muda.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from .pma import PMARequest, PMAResponse


@dataclass
class Capability:
    provider: str
    model: str
    locality: str = "external"             # external | local
    context_window: int = 0
    max_output_tokens: int = 0
    supports_system: bool = True
    supports_tools: bool = False
    privacy_class: str = "external-cloud"  # external-cloud | local-only


class ProviderDriver(ABC):
    """Traduz PMA (neutro) <-> API nativa. Isola o provedor do resto do sistema."""

    @abstractmethod
    def describe(self) -> Capability:
        ...

    @abstractmethod
    def generate(self, req: PMARequest) -> PMAResponse:
        ...

    def healthcheck(self) -> dict:
        return {"status": "unknown"}
