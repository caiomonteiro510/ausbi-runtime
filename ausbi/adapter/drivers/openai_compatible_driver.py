"""Driver OpenAI-compatível — cobre Groq, e no futuro Ollama/ChatGPT/Codex.

Reaproveita a mesma tradução PMA <-> nativo para qualquer provedor que fale o
protocolo de chat da OpenAI (`/v1/chat/completions`). Só muda `base_url`,
`api_key_env` e `provider_name` por perfil — o driver em si não muda.
("Economia de engenharia": um único driver OpenAI-compatível cobre vários
provedores.)
"""
from __future__ import annotations

import os
import re

from ..base import Capability, ProviderDriver
from ..pma import PMARequest, PMAResponse


class OpenAICompatibleDriver(ProviderDriver):
    def __init__(
        self,
        model: str,
        base_url: str,
        api_key_env: str,
        provider_name: str,
        locality: str = "external",
        context_window: int = 128_000,
        max_output_tokens: int = 32_768,
    ):
        self.model = model
        self.base_url = base_url
        self.api_key_env = api_key_env
        self.provider_name = provider_name
        self.locality = locality
        self.context_window = context_window
        self.max_output_tokens = max_output_tokens

    def describe(self) -> Capability:
        return Capability(
            provider=self.provider_name,
            model=self.model,
            locality=self.locality,
            context_window=self.context_window,
            max_output_tokens=self.max_output_tokens,
            supports_system=True,
            supports_tools=True,
            privacy_class="local-only" if self.locality == "local" else "external-cloud",
        )

    def _messages_from(self, req: PMARequest) -> list[dict[str, str]]:
        # Identidade (estável) + memória relevante (dinâmica) -> mensagem "system".
        parts = [req.identity]
        if req.context:
            parts.append("\n\n# MEMÓRIA RELEVANTE (do vault)\n")
            for item in req.context:
                parts.append(f"\n===== {item.ref} =====\n{item.content}\n")
        system = "".join(parts)
        return [{"role": "system", "content": system}, *req.input]

    def generate(self, req: PMARequest) -> PMAResponse:
        # Import tardio: o núcleo e o --selftest rodam sem o pacote instalado.
        try:
            from openai import (
                APIConnectionError,
                APIError,
                APIStatusError,
                AuthenticationError,
                OpenAI,
                RateLimitError,
            )
        except ImportError:
            return PMAResponse(
                error="DRIVER_INDISPONIVEL",
                stop_reason="error",
                output_text="Pacote 'openai' não instalado. Rode: pip install -r requirements.txt",
            )

        api_key = os.environ.get(self.api_key_env) or "placeholder"  # alguns provedores locais ignoram a key
        client = OpenAI(api_key=api_key, base_url=self.base_url)
        max_tokens = int(req.params.get("max_tokens", 8192))

        try:
            resp = client.chat.completions.create(
                model=self.model,
                max_tokens=max_tokens,
                messages=self._messages_from(req),
            )
        except AuthenticationError:
            return PMAResponse(error="AUTH", stop_reason="error",
                               output_text=f"Credencial inválida ou ausente ({self.api_key_env}).")
        except RateLimitError:
            return PMAResponse(error="RATE_LIMIT", stop_reason="error",
                               output_text="Limite de uso atingido. Tente novamente em instantes.")
        except APIConnectionError:
            return PMAResponse(error="PROVIDER_UNAVAILABLE", stop_reason="error",
                               output_text="Falha de rede ao contatar o provedor.")
        except APIStatusError as e:
            code = getattr(e, "status_code", "?")
            detail = getattr(e, "message", "") or str(e)  # preserva a mensagem do provedor p/ diagnóstico
            # 413 = requisição grande demais (ex.: free tier de TPM) -> Orquestrador reduz.
            norm = "CONTEXT_OVERFLOW" if code == 413 else "UNKNOWN"
            return PMAResponse(error=norm, stop_reason="error",
                               output_text=f"(status {code}) {detail}")
        except APIError as e:
            return PMAResponse(error="UNKNOWN", stop_reason="error",
                               output_text=f"Erro: {e}")

        model_used = {"provider": self.provider_name,
                      "model": getattr(resp, "model", self.model),
                      "locality": self.locality}

        choice = resp.choices[0]
        finish_reason = choice.finish_reason

        if finish_reason == "content_filter":
            return PMAResponse(error="CONTENT_FILTER", stop_reason="filter",
                               model_used=model_used,
                               output_text="O provedor recusou responder a esta solicitação.")

        # Separa o RACIOCÍNIO INTERNO da RESPOSTA FINAL. Regra: o "pensamento" do
        # modelo nunca deve ser apresentado ao usuário como resposta.
        content = re.sub(r"<think>.*?</think>", "", choice.message.content or "",
                         flags=re.DOTALL).strip()
        if content:
            text = content
        elif self.locality == "local":
            # alguns modelos locais expõem o pensamento em `reasoning` — NÃO é a resposta.
            # Sem resposta final (ex.: orçamento de tokens esgotado): não vaza o raciocínio.
            text = "(sem resposta final — o modelo esgotou o orçamento de tokens; tente de novo)"
        else:
            # Provedores de raciocínio (ex.: modelos "reasoning" na Groq) às vezes trazem a
            # RESPOSTA (não o pensamento) em `reasoning` — só aí usamos esse campo.
            text = getattr(choice.message, "reasoning", None) or ""
        usage = getattr(resp, "usage", None)
        return PMAResponse(
            output_text=text,
            model_used=model_used,
            usage={"tokens_in": usage.prompt_tokens, "tokens_out": usage.completion_tokens} if usage else {},
            stop_reason="complete" if finish_reason in ("stop", "tool_calls") else (finish_reason or "complete"),
        )
