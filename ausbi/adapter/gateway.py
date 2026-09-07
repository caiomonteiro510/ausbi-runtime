"""Adaptador de Modelo (LLM Gateway).

Roteia a requisição PMA para o driver do perfil ativo. Trocar de modelo =
mudar o perfil na config; o núcleo (Orquestrador, memória, identidade) não muda.
"""
from __future__ import annotations

from .base import ProviderDriver
from .drivers.anthropic_driver import AnthropicDriver
from .drivers.openai_compatible_driver import OpenAICompatibleDriver
from .pma import PMARequest, PMAResponse

# Provedores que falam o protocolo de chat da OpenAI (/v1/chat/completions).
# Um só driver cobre todos — muda apenas base_url/api_key_env por perfil.
_OPENAI_COMPATIBLE = {"groq", "openai", "ollama", "openai_compatible"}


def _build_driver(profile: dict) -> ProviderDriver:
    provider = profile.get("provider", "anthropic")
    if provider == "anthropic":
        return AnthropicDriver(model=profile["model"])
    if provider in _OPENAI_COMPATIBLE:
        return OpenAICompatibleDriver(
            model=profile["model"],
            base_url=profile["base_url"],
            api_key_env=profile.get("api_key_env", "OPENAI_API_KEY"),
            provider_name=provider,
            locality=profile.get("locality", "external"),
            context_window=profile.get("context_window", 128_000),
            max_output_tokens=profile.get("max_output_tokens", 32_768),
        )
    raise ValueError(f"Provedor sem driver: {provider!r}")


class ModelGateway:
    def __init__(self, config: dict):
        self.config = config
        self.profiles = config.get("profiles", {})
        self.default_profile = config.get("default_profile", "padrao")

    def _profile(self, name: str | None) -> dict:
        name = name or self.default_profile
        if name not in self.profiles:
            raise ValueError(f"Perfil desconhecido: {name!r}")
        return self.profiles[name]

    def describe(self, profile_name: str | None = None):
        return _build_driver(self._profile(profile_name)).describe()

    def generate(self, req: PMARequest) -> PMAResponse:
        profile_name = req.routing.get("profile") or self.default_profile
        driver = _build_driver(self._profile(profile_name))
        return driver.generate(req)
