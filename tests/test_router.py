"""Testes do Router (Fases R1/R2) — matriz determinística `entrada -> perfil`.

Roda standalone (sem pytest):  python tests/test_router.py
Cobre: privacidade (vault->local), complexidade (rapido<->profundo), ausência de
credencial/offline (externos barrados), override (hint>sessão), e fallbacks.
NÃO chama modelo, Groq ou Anthropic — valida só a LÓGICA (pura/determinística).
"""
from __future__ import annotations
import os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # .../AUSBI_Runtime
from ausbi.router import select_profile, is_strong_complexity
from ausbi.orchestrator import Orchestrator

# ---- perfis sintéticos p/ os testes (independem do config real) ----
LOCAL_BOTH = {
    "local_rapido":   {"provider": "ollama", "locality": "local"},
    "local_profundo": {"provider": "ollama", "locality": "local"},
    "groq":           {"provider": "groq", "locality": "external", "api_key_env": "GROQ_API_KEY"},
    "anthropic":      {"provider": "anthropic", "locality": "external"},
}
NO_PROFUNDO = {k: v for k, v in LOCAL_BOTH.items() if k != "local_profundo"}
NO_RAPIDO = {k: v for k, v in LOCAL_BOTH.items() if k != "local_rapido"}

LONG = "resuma " * 90  # >= 80 palavras -> sinal de tamanho

def _cfg(profiles=LOCAL_BOTH, enabled=True, default="local_rapido", **router):
    r = {"enabled": enabled, "escalate_min_words": 80}
    r.update(router)
    return {"profiles": profiles, "default_profile": default, "router": r}

results = []
def check(cid, got, exp_profile, exp_reason=None):
    gp, gr = got
    ok = (gp == exp_profile) and (exp_reason is None or gr == exp_reason)
    results.append((cid, ok, f"got=({gp},{gr}) exp=({exp_profile},{exp_reason or '*'})"))

# ===================== A) select_profile (PURO) =====================
def test_select_profile_puro():
    check("A1 simples->rapido", select_profile("Qual a capital da França?", [], _cfg()), "local_rapido", "auto-rapido")
    check("A2 keyword planeje->profundo", select_profile("Planeje uma estratégia de lançamento", [], _cfg()), "local_profundo", "auto-complexo")
    check("A3 keyword compare->profundo", select_profile("Compare as duas abordagens", [], _cfg()), "local_profundo", "auto-complexo")
    check("A4 texto longo->profundo", select_profile(LONG, [], _cfg()), "local_profundo", "auto-complexo")
    check("A5 conversa->rapido", select_profile("Bom dia, tudo bem?", [], _cfg()), "local_rapido", "auto-rapido")
    check("A6 complexo sem profundo->rapido", select_profile("Planeje tudo", [], _cfg(profiles=NO_PROFUNDO)), "local_rapido", "auto-rapido")
    check("A7 sem rapido->default", select_profile("oi", [], _cfg(profiles=NO_RAPIDO, default="local_profundo")), "local_profundo", "auto-fallback-default")
    # limiar configurável: min_words alto impede escalar por tamanho
    check("A8 min_words alto barra tamanho", select_profile(LONG, [], _cfg(escalate_min_words=999)), "local_rapido", "auto-rapido")

def test_is_strong_complexity():
    assert is_strong_complexity("planeje isso") is True
    assert is_strong_complexity("oi") is False
    assert is_strong_complexity("x " * 80) is True
    assert is_strong_complexity("x " * 80, {"escalate_min_words": 999}) is False

# ===================== B) _route (Orchestrator, com sinais controlados) =====================
def _mk():
    o = Orchestrator()  # carrega config real, mas vamos substituir o.cfg em cada caso
    return o

def _route(o, cfg, text="oi", hint=None, sticky=None, signals=None):
    o.cfg = cfg
    o.profile_override = sticky
    o._router_signals = lambda: signals or {"online": True, "cred": {"groq": True, "anthropic": True}}
    return o._route(text, [], turn_override=hint)

def test_route_disabled_preserva_R1():
    o = _mk()
    # com router desligado: sem seleção automática, override honrado como na R1
    check("D1 off,sem override,complexo->rapido(default)", _route(o, _cfg(enabled=False), "planeje estratégia"), "local_rapido", "default")
    check("D2 off,sticky profundo", _route(o, _cfg(enabled=False), sticky="local_profundo"), "local_profundo", "override-sessao")
    # off: override externo SEM credencial ainda é honrado (comportamento R1)
    check("D3 off,hint groq sem cred->groq", _route(o, _cfg(enabled=False), hint="groq",
          signals={"online": True, "cred": {"groq": False}}), "groq", "override-turno")
    check("D4 off,sticky inexistente->default", _route(o, _cfg(enabled=False), sticky="xxx"), "local_rapido", "override-sessao-invalido")

def test_route_enabled_R2():
    o = _mk()
    # privacidade + padrão local
    check("E1 on,sem override,simples->rapido", _route(o, _cfg(), "Qual a capital da França?"), "local_rapido", "auto-rapido")
    check("E2 on,sem override,complexo->profundo", _route(o, _cfg(), "Planeje uma estratégia detalhada"), "local_profundo", "auto-complexo")
    # override vence (regra 1)
    check("E3 on,hint profundo (texto simples)", _route(o, _cfg(), "oi", hint="local_profundo"), "local_profundo", "override-turno")
    check("E4 on,sticky profundo", _route(o, _cfg(), "oi", sticky="local_profundo"), "local_profundo", "override-sessao")
    check("E5 on,hint>sticky", _route(o, _cfg(), "oi", hint="groq", sticky="local_profundo"), "groq", "override-turno")
    # externos: precisam online + credencial (regra 3)
    check("E6 on,sticky groq online+cred->groq", _route(o, _cfg(), sticky="groq"), "groq", "override-sessao")
    check("E7 on,sticky groq SEM cred->rapido", _route(o, _cfg(), sticky="groq",
          signals={"online": True, "cred": {"groq": False}}), "local_rapido", "override-sessao-indisponivel")
    check("E8 on,sticky anthropic OFFLINE->rapido", _route(o, _cfg(), sticky="anthropic",
          signals={"online": False, "cred": {"anthropic": True}}), "local_rapido", "override-sessao-indisponivel")
    check("E9 on,hint anthropic online+cred->anthropic", _route(o, _cfg(), hint="anthropic"), "anthropic", "override-turno")
    # fallbacks (regra 6)
    check("E10 on,sticky inexistente->rapido", _route(o, _cfg(), sticky="zzz"), "local_rapido", "override-sessao-inexistente")
    check("E11 on,hint inexistente->rapido", _route(o, _cfg(), hint="zzz"), "local_rapido", "override-turno-inexistente")
    check("E12 on,complexo sem profundo->rapido", _route(o, _cfg(profiles=NO_PROFUNDO), "planeje tudo"), "local_rapido", "auto-rapido")
    # privacidade: conteúdo citando 'groq/anthropic' NÃO roteia p/ externo no automático
    check("E13 on,auto nunca externo (conteúdo)", _route(o, _cfg(), "compare groq e anthropic detalhadamente"), "local_profundo", "auto-complexo")

def run():
    for fn in (test_select_profile_puro, test_is_strong_complexity,
               test_route_disabled_preserva_R1, test_route_enabled_R2):
        fn()
    fails = [r for r in results if not r[1]]
    for cid, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FALHOU'}] {cid:42s} {detail}")
    print(f"\n{len(results)-len(fails)}/{len(results)} casos OK.")
    if fails:
        print("FALHAS:", [f[0] for f in fails]); sys.exit(1)
    print("TODOS OS TESTES DO ROUTER PASSARAM.")

if __name__ == "__main__":
    run()
