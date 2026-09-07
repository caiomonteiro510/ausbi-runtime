"""Orquestrador (M4) — cérebro operacional.

Implementa o fluxo de turno da arquitetura congelada v0.1:
  intake -> identidade -> memória -> (modelo via Adaptador) -> resposta
         -> persistência com confirmação -> log.

Fala apenas dois "idiomas": arquivos do vault + PMA. Zero conhecimento de provedor.
"""
from __future__ import annotations

import time
import uuid

from .config import load_config
from .identity import assemble_identity
from .memory import append_note, format_persistence_block, select_relevant
from .logger import TurnLogger
from .adapter.gateway import ModelGateway
from .adapter.pma import PMARequest, PMAResponse


class Orchestrator:
    def __init__(self):
        self.cfg = load_config()
        self.vault = self.cfg["_vault_dir"]
        self.gateway = ModelGateway(self.cfg)
        self.logger = TurnLogger(self.cfg["_runtime_dir"], self.cfg["log_file"])
        self.identity = ""
        self.missing: list[str] = []
        self.messages: list[dict[str, str]] = []  # histórico da sessão (O10)
        self.profile_override: str | None = None   # R1: override fixo de sessão (/modelo); None = router/default

    # ---- B1–B4: boot (carrega identidade do vault) ----
    def boot(self) -> dict:
        self.identity, self.missing = assemble_identity(self.vault, self.cfg["identity_files"])
        prof = self.cfg["profiles"][self.cfg["default_profile"]]
        return {
            "vault": self.vault,
            "profile": self.cfg["default_profile"],
            "provider": prof.get("provider"),
            "model": prof.get("model"),
            "identity_loaded": bool(self.identity) and not self.missing,
            "missing": self.missing,
            "has_api_key": self.cfg.get("_has_api_key", False),
            "api_key_env": self.cfg.get("_api_key_env", "ANTHROPIC_API_KEY"),
            "profile_override": self.profile_override,
        }

    # ---- T1–T8: um turno de conversa ----
    def turn(self, user_text: str, profile: str | None = None) -> dict:
        # `profile` = hint de override POR TURNO (opcional; tratado pelo sistema).
        t0 = time.perf_counter()
        trace_id = uuid.uuid4().hex[:8]
        context, refs = select_relevant(self.vault, user_text, self.cfg["orientation_files"])
        self.messages.append({"role": "user", "content": user_text})
        chosen, route_reason = self._route(user_text, context, turn_override=profile)
        prof = self.cfg["profiles"][chosen]
        req = PMARequest(
            identity=self.identity,
            input=self.messages,
            context=context,
            params={"max_tokens": prof.get("max_tokens", 8192)},
            routing={"profile": chosen, "sensitivity": "normal"},
            trace_id=trace_id,
        )
        resp, safety = self._generate_with_safety(req, chosen, route_reason)  # R2.1: timeout + fallback
        if resp.error:
            reply = f"[{resp.error}] {resp.output_text}"
            self.messages.pop()  # turno de erro não fica preso no histórico (evita bola de neve em CONTEXT_OVERFLOW)
        else:
            reply = resp.output_text
            if reply:  # não empilha turno de assistant vazio (alguns provedores rejeitam no histórico)
                self.messages.append({"role": "assistant", "content": reply})
        elapsed_s = round(time.perf_counter() - t0, 2)
        self.logger.log({
            "trace_id": trace_id, "type": "turn", "refs": refs,
            "profile": chosen, "route_reason": route_reason, "elapsed_s": elapsed_s,
            "timeout": safety["timeout"], "fallback": safety["fallback"],
            "model": resp.model_used, "usage": resp.usage,
            "stop_reason": resp.stop_reason, "error": resp.error,
        })
        return {"reply": reply, "refs": refs, "trace_id": trace_id,
                "profile": chosen, "route_reason": route_reason, "elapsed_s": elapsed_s,
                "timeout": safety["timeout"], "fallback": safety["fallback"],
                "usage": resp.usage, "error": resp.error}

    # ---- Override explícito de perfil (Fase R1) — tratado pelo SISTEMA ----
    _CLEAR_WORDS = {"auto", "none", "limpar", "off", "nenhum"}

    def set_profile_override(self, name: str | None) -> tuple[bool, str]:
        """Fixa (ou limpa) o perfil da SESSÃO. Override explícito do usuário via
        comando `/modelo`; nunca vem do modelo. Palavras de limpeza (auto/limpar/…)
        voltam ao default. Retorna (ok, mensagem)."""
        if name is None or name.strip().lower() in self._CLEAR_WORDS:
            self.profile_override = None
            return True, f"override limpo — usando o padrão ({self.cfg['default_profile']})."
        name = name.strip()
        if name not in self.cfg["profiles"]:
            return False, f"perfil desconhecido: {name!r}. Disponíveis: {', '.join(self.cfg['profiles'])}."
        self.profile_override = name
        return True, f"perfil fixado para a sessão: {name}."

    # ---- Router: escolhe o perfil do turno ----
    def _is_local_profile(self, name: str) -> bool:
        p = self.cfg["profiles"].get(name, {})
        return p.get("locality") == "local" or p.get("provider") == "ollama"

    def _router_signals(self) -> dict:
        """Sinais DETERMINÍSTICOS para o router (sem rede): credencial por perfil
        externo (lida do AMBIENTE) e conectividade (flag de config assume_online —
        sem probe de rede, para manter tudo determinístico e testável)."""
        import os
        router_cfg = self.cfg.get("router") or {}
        cred: dict[str, bool] = {}
        for name, p in self.cfg["profiles"].items():
            if not self._is_local_profile(name):  # só perfis externos têm credencial
                env = p.get("api_key_env") or (
                    "ANTHROPIC_API_KEY" if p.get("provider") == "anthropic" else "OPENAI_API_KEY")
                cred[name] = bool(os.environ.get(env))
        return {"online": bool(router_cfg.get("assume_online", True)), "cred": cred}

    def _route(self, user_text: str, context, turn_override: str | None = None) -> tuple[str, str]:
        """Decide o perfil do turno (determinístico). Prioridade:
          1) override explícito (hint > sessão) — vence tudo;
          2) dados do vault ficam LOCAIS por padrão;
          3) externos (groq/anthropic) só com conectividade + credencial (+ opt-in
             explícito = o próprio override);
          4) local padrão = local_rapido;
          5) local_profundo só com sinal FORTE de complexidade (conservador);
          6) erro/ambiguidade/indisponível => local_rapido.
        Com `router.enabled=false`, mantém o comportamento da R1 (sem seleção
        automática e sem gate de disponibilidade) — reversível por flag."""
        profiles = self.cfg["profiles"]
        router_cfg = self.cfg.get("router") or {}
        override = turn_override or self.profile_override
        which = "override-turno" if turn_override else "override-sessao"

        # ----- router DESLIGADO: comportamento R1 (inalterado) -----
        if not router_cfg.get("enabled"):
            default = self.cfg["default_profile"]
            if override:
                return (override, which) if override in profiles else (default, which + "-invalido")
            return default, "default"

        # ----- router LIGADO: regras completas (R2) -----
        safe = "local_rapido" if "local_rapido" in profiles else self.cfg["default_profile"]
        signals = self._router_signals()

        def available(name: str) -> bool:
            if name not in profiles:
                return False
            if self._is_local_profile(name):
                return True  # regra 2: local sempre disponível
            # regra 3: externo precisa conectividade + credencial
            return bool(signals["online"]) and bool(signals["cred"].get(name))

        # (1) override explícito vence — mas externo indisponível cai p/ rapido (3+6)
        if override:
            if override not in profiles:
                return safe, which + "-inexistente"
            if not available(override):
                return safe, which + "-indisponivel"
            return override, which

        # (2..5) seleção automática — SÓ local (privacidade); import tardio de router.py
        try:
            from .router import select_profile
            profile, reason = select_profile(user_text, context, self.cfg, signals=signals)
        except Exception as e:
            return safe, f"router-error:{type(e).__name__}"  # regra 6
        if profile not in profiles or not available(profile):
            return safe, "auto-indisponivel"  # regra 6
        return profile, reason

    # ---- R2.1: execução com timeout + fallback (subprocesso, hard-cancel) ----
    def _generate_with_safety(self, req, profile: str, route_reason: str) -> tuple[PMAResponse, dict]:
        """Executa a geração com limite de tempo. Retorna (PMAResponse, safety),
        onde safety = {"timeout": bool, "fallback": str|None}.

        - Override explícito (route_reason 'override-*'): teto `override_timeout_s`
          (300s); se estourar, NÃO faz fallback — devolve mensagem clara (escolha
          consciente do usuário).
        - Automático: `timeout_s` do perfil; se estourar, fallback p/ local_rapido.
        - O fallback também tem timeout; se falhar, mensagem graciosa (nunca trava).
        - `timeout_s` ausente/0 => chamada DIRETA (comportamento atual, reversível).
        """
        prof = self.cfg["profiles"][profile]
        router_cfg = self.cfg.get("router") or {}
        is_override = route_reason.startswith("override-")
        timeout_s = router_cfg.get("override_timeout_s", 300) if is_override else prof.get("timeout_s")

        # sem timeout configurado -> chamada direta (idêntico ao comportamento anterior)
        if not timeout_s or timeout_s <= 0:
            return self.gateway.generate(req), {"timeout": False, "fallback": None}

        try:
            from .execution import generate_with_timeout
            status, payload = generate_with_timeout(self.cfg, req, timeout_s)
        except Exception:  # executor indisponível -> degrada p/ chamada direta (nunca pior que hoje)
            return self.gateway.generate(req), {"timeout": False, "fallback": None}

        if status == "ok":
            return payload, {"timeout": False, "fallback": None}
        if status == "error":
            return (PMAResponse(error="EXEC_ERROR", stop_reason="error",
                                output_text=f"Falha na execução isolada: {payload}"),
                    {"timeout": False, "fallback": None})

        # status == "timeout"
        if is_override:
            # escolha consciente do usuário: SEM fallback silencioso — mensagem clara.
            msg = (f"O modelo do perfil '{profile}' ({prof.get('model')}) atingiu o limite de "
                   f"execução de {timeout_s}s e foi encerrado. Você o selecionou manualmente "
                   f"(/modelo); tente uma pergunta mais simples ou volte ao automático com /modelo auto.")
            return (PMAResponse(error="TIMEOUT", stop_reason="error", output_text=msg,
                                model_used={"provider": prof.get("provider"), "model": prof.get("model")}),
                    {"timeout": True, "fallback": None})

        # automático: fallback p/ local_rapido
        fb = "local_rapido"
        if profile == fb or fb not in self.cfg["profiles"]:
            return (PMAResponse(error="TIMEOUT", stop_reason="error",
                                output_text="O modelo demorou demais e não há fallback disponível. Tente de novo."),
                    {"timeout": True, "fallback": None})
        fb_prof = self.cfg["profiles"][fb]
        fb_req = PMARequest(identity=req.identity, input=req.input, context=req.context,
                            params={"max_tokens": fb_prof.get("max_tokens", 8192)},
                            routing={"profile": fb, "sensitivity": "normal"}, trace_id=req.trace_id)
        fb_timeout = fb_prof.get("timeout_s") or 90
        try:
            from .execution import generate_with_timeout
            fstatus, fpayload = generate_with_timeout(self.cfg, fb_req, fb_timeout)
        except Exception:
            fstatus, fpayload = "error", "executor indisponível"
        if fstatus == "ok":
            return fpayload, {"timeout": True, "fallback": fb}
        # fallback também falhou -> mensagem graciosa (nunca trava)
        return (PMAResponse(error="TIMEOUT", stop_reason="error",
                            output_text=("Não consegui responder a tempo: o modelo profundo estourou o limite "
                                         "e o rápido também não respondeu. Tente novamente em instantes."),
                            model_used={"provider": fb_prof.get("provider"), "model": fb_prof.get("model")}),
                {"timeout": True, "fallback": fb})

    # ---- T7: persistência com confirmação ----
    def preview_persistence(self, tipo: str, conteudo: str) -> dict | None:
        targets = self.cfg["persistence_targets"]
        if tipo not in targets:
            return None
        trace_id = uuid.uuid4().hex[:8]
        block = format_persistence_block(tipo, conteudo, trace_id)
        return {"tipo": tipo, "nota": targets[tipo], "block": block, "trace_id": trace_id}

    def commit_persistence(self, preview: dict) -> str:
        path = append_note(self.vault, preview["nota"], preview["block"])
        self.logger.log({"trace_id": preview["trace_id"], "type": "write",
                         "tipo": preview["tipo"], "nota": preview["nota"]})
        return path
