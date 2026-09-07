"""Driver Anthropic (Claude) — primeiro driver real do Adaptador.

É o ÚNICO arquivo que conhece o SDK da Anthropic. Mapeia PMA -> nativo e
normaliza erros. O segredo (ANTHROPIC_API_KEY) vem do AMBIENTE, nunca do vault.

SDK: client.messages.create(model, max_tokens, system=..., messages=[...]).
Nota de família de modelos: alguns modelos Claude mais recentes REJEITAM
`temperature`/`top_p` (HTTP 400). Este driver deliberadamente não os envia —
esse é um "quirk" do provedor que o driver absorve, não o núcleo.
"""
from __future__ import annotations

from ..base import Capability, ProviderDriver
from ..pma import PMARequest, PMAResponse


class AnthropicDriver(ProviderDriver):
    def __init__(self, model: str = "claude-opus-5"):
        self.model = model

    def describe(self) -> Capability:
        return Capability(
            provider="anthropic",
            model=self.model,
            locality="external",
            context_window=1_000_000,
            max_output_tokens=128_000,
            supports_system=True,
            supports_tools=True,
            privacy_class="external-cloud",
        )

    def _system_from(self, req: PMARequest) -> str:
        # Identidade (estável) + memória relevante (dinâmica) -> `system` nativo.
        parts = [req.identity]
        if req.context:
            parts.append("\n\n# MEMÓRIA RELEVANTE (do vault)\n")
            for item in req.context:
                parts.append(f"\n===== {item.ref} =====\n{item.content}\n")
        return "".join(parts)

    def generate(self, req: PMARequest) -> PMAResponse:
        # Import tardio: o núcleo e o --selftest rodam sem o pacote instalado.
        try:
            import anthropic
        except ImportError:
            return PMAResponse(
                error="DRIVER_INDISPONIVEL",
                stop_reason="error",
                output_text="Pacote 'anthropic' não instalado. Rode: pip install -r requirements.txt",
            )

        client = anthropic.Anthropic()  # lê ANTHROPIC_API_KEY do ambiente
        max_tokens = int(req.params.get("max_tokens", 8192))

        try:
            resp = client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=self._system_from(req),
                messages=req.input,
            )
        except anthropic.AuthenticationError:
            return PMAResponse(error="AUTH", stop_reason="error",
                               output_text="Credencial inválida ou ausente (ANTHROPIC_API_KEY).")
        except anthropic.RateLimitError:
            return PMAResponse(error="RATE_LIMIT", stop_reason="error",
                               output_text="Limite de uso atingido. Tente novamente em instantes.")
        except anthropic.APIConnectionError:
            return PMAResponse(error="PROVIDER_UNAVAILABLE", stop_reason="error",
                               output_text="Falha de rede ao contatar o provedor.")
        except anthropic.APIStatusError as e:
            return PMAResponse(error="UNKNOWN", stop_reason="error",
                               output_text=f"Erro da API (status {getattr(e, 'status_code', '?')}).")
        except anthropic.APIError as e:  # rede/base
            return PMAResponse(error="UNKNOWN", stop_reason="error",
                               output_text=f"Erro: {e}")

        model_used = {"provider": "anthropic",
                      "model": getattr(resp, "model", self.model),
                      "locality": "external"}

        if resp.stop_reason == "refusal":
            return PMAResponse(error="CONTENT_FILTER", stop_reason="filter",
                               model_used=model_used,
                               output_text="O provedor recusou responder a esta solicitação.")

        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        return PMAResponse(
            output_text=text,
            model_used=model_used,
            usage={"tokens_in": resp.usage.input_tokens,
                   "tokens_out": resp.usage.output_tokens},
            stop_reason="complete" if resp.stop_reason in ("end_turn", "stop_sequence")
            else (resp.stop_reason or "complete"),
        )
