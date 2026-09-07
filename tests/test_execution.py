"""Testes da Fase R2.1 — Execution Safety (timeout + hard-cancel + fallback).

Rodar:  python tests/test_execution.py

T1–T6: determinísticos/mockados (sem modelo) — lógica de timeout/fallback/override.
T7:    cancelamento REAL de subprocesso + prova de que não fica órfão.
T8:    end-to-end curto (modelo local real, timeout de 3s no profundo -> fallback real).
T9:    saúde do modelo local depois do cancelamento (chamada normal volta a responder).

T8/T9 exigem um provedor local real rodando (ex.: Ollama) — pulam graciosamente
se o boot falhar.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))       # tests/
ROOT = os.path.dirname(HERE)                             # AUSBI_Runtime/
for _p in (ROOT, HERE):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import psutil                                            # noqa: E402
import timeout_probe                                     # noqa: E402  (workers spawn-safe)
from ausbi import execution                              # noqa: E402
from ausbi.orchestrator import Orchestrator              # noqa: E402
from ausbi.adapter.pma import PMARequest, PMAResponse    # noqa: E402

results = []
def check(cid, ok, detail=""):
    results.append((cid, bool(ok), detail))

# ---------- helpers (sem modelo) ----------
def synth_cfg(profundo_t=45, rapido_t=90, override_t=300, with_profundo=True, with_rapido=True):
    profiles = {}
    if with_rapido:
        profiles["local_rapido"] = {"provider": "ollama", "locality": "local",
                                    "model": "qwen2.5:3b", "max_tokens": 2048, "timeout_s": rapido_t}
    if with_profundo:
        profiles["local_profundo"] = {"provider": "ollama", "locality": "local",
                                      "model": "qwen3:8b", "max_tokens": 3072, "timeout_s": profundo_t}
    return {"profiles": profiles, "default_profile": "local_rapido",
            "router": {"enabled": False, "override_timeout_s": override_t}}

def make_req(profile="local_profundo"):
    return PMARequest(identity="ID", input=[{"role": "user", "content": "oi"}], context=[],
                      params={"max_tokens": 2048}, routing={"profile": profile}, trace_id="test")

def rsp(text="RESP", model="mX"):
    return PMAResponse(output_text=text, model_used={"model": model}, stop_reason="complete", error=None)

class Stub:
    """Substitui execution.generate_with_timeout: devolve resultados em sequência e grava as chamadas."""
    def __init__(self, seq):
        self.seq = list(seq); self.calls = []
    def __call__(self, cfg, req, timeout_s):
        self.calls.append({"profile": req.routing.get("profile"), "timeout_s": timeout_s})
        return self.seq.pop(0) if self.seq else ("error", "sem-resultado")

# ---------- T1–T6: lógica (mockada) ----------
def tests_logica():
    _real = execution.generate_with_timeout
    o = Orchestrator()
    try:
        # T1 — rapido normal (sucesso, sem timeout)
        o.cfg = synth_cfg()
        execution.generate_with_timeout = Stub([("ok", rsp("rapido-ok", "qwen2.5:3b"))])
        r, s = o._generate_with_safety(make_req("local_rapido"), "local_rapido", "default")
        check("T1 rapido normal", r.output_text == "rapido-ok" and s == {"timeout": False, "fallback": None})

        # T2 — profundo-auto estoura -> fallback p/ local_rapido
        o.cfg = synth_cfg()
        st = Stub([("timeout", 111), ("ok", rsp("fb-rapido", "qwen2.5:3b"))])
        execution.generate_with_timeout = st
        r, s = o._generate_with_safety(make_req("local_profundo"), "local_profundo", "auto-complexo")
        check("T2 profundo->fallback rapido",
              r.output_text == "fb-rapido" and s == {"timeout": True, "fallback": "local_rapido"}
              and len(st.calls) == 2 and st.calls[0]["timeout_s"] == 45
              and st.calls[1]["profile"] == "local_rapido" and st.calls[1]["timeout_s"] == 90)

        # T3 — profundo-auto conclui a tempo (sem fallback)
        o.cfg = synth_cfg()
        execution.generate_with_timeout = Stub([("ok", rsp("profundo-ok", "qwen3:8b"))])
        r, s = o._generate_with_safety(make_req("local_profundo"), "local_profundo", "auto-complexo")
        check("T3 profundo conclui", r.output_text == "profundo-ok" and s == {"timeout": False, "fallback": None})

        # T4 — fallback também estoura -> mensagem graciosa, nunca trava
        o.cfg = synth_cfg()
        execution.generate_with_timeout = Stub([("timeout", 1), ("timeout", 2)])
        r, s = o._generate_with_safety(make_req("local_profundo"), "local_profundo", "auto-complexo")
        check("T4 fallback tbm estoura -> gracioso",
              r.error == "TIMEOUT" and s == {"timeout": True, "fallback": "local_rapido"} and bool(r.output_text))

        # T5 — override explícito: teto 300s, SEM fallback silencioso
        o.cfg = synth_cfg()
        st = Stub([("timeout", 5)])
        execution.generate_with_timeout = st
        r, s = o._generate_with_safety(make_req("local_profundo"), "local_profundo", "override-sessao")
        check("T5 override bypass (teto 300, sem fallback)",
              r.error == "TIMEOUT" and s == {"timeout": True, "fallback": None}
              and "300s" in r.output_text and len(st.calls) == 1 and st.calls[0]["timeout_s"] == 300)

        # T6 — timeout_s=0 -> chamada DIRETA (reversível, comportamento atual)
        o.cfg = synth_cfg(profundo_t=0)
        seen = {"sub": 0}
        def _boom(*a, **k):
            seen["sub"] += 1; return ("timeout", 0)
        execution.generate_with_timeout = _boom
        o.gateway.generate = lambda rq: rsp("direct-ok", "qwen3:8b")
        r, s = o._generate_with_safety(make_req("local_profundo"), "local_profundo", "auto-complexo")
        check("T6 timeout_s=0 -> direto (reversível)",
              r.output_text == "direct-ok" and s == {"timeout": False, "fallback": None} and seen["sub"] == 0)
    finally:
        execution.generate_with_timeout = _real   # restaura p/ os testes reais

# ---------- T7: cancelamento REAL + sem órfão ----------
def test_cancel_real():
    md = tempfile.mkdtemp(prefix="ausbi_r21_")
    t0 = time.time()
    status, pid = execution.run_in_subprocess(timeout_probe.slow_marker_worker, (md, 30), 1.0)
    dt = time.time() - t0
    started = os.path.exists(os.path.join(md, "started"))
    done = os.path.exists(os.path.join(md, "done"))
    hb = os.path.join(md, "heartbeat")
    hb1 = os.path.getmtime(hb) if os.path.exists(hb) else None
    time.sleep(1.5)                                  # janela p/ detectar órfão
    hb2 = os.path.getmtime(hb) if os.path.exists(hb) else None
    alive = psutil.pid_exists(pid) if pid else True
    check("T7 cancel real (subprocesso encerrado)", status == "timeout" and started and not done and dt < 6)
    check("T7 sem órfão (heartbeat parou + pid morto)", hb1 is not None and hb1 == hb2 and not alive)

# ---------- T8/T9: end-to-end real (provedor local) ----------
def tests_e2e():
    try:
        o = Orchestrator(); o.boot()
    except Exception as e:
        check("T8 e2e (setup)", False, f"boot falhou: {e}"); return
    # T8 — timeout curto real no profundo -> fallback real p/ rapido
    try:
        o.cfg["router"]["enabled"] = True
        o.cfg["profiles"]["local_profundo"]["timeout_s"] = 3
        t0 = time.time()
        out = o.turn("Planeje uma estratégia detalhada de estudos para o mês, passo a passo.")
        dt = round(time.time() - t0, 1)
        ok = out.get("timeout") is True and out.get("fallback") == "local_rapido" \
            and out.get("error") is None and bool(out.get("reply"))
        check("T8 e2e timeout curto -> fallback real", ok,
              f"{dt}s profile={out.get('profile')} timeout={out.get('timeout')} "
              f"fallback={out.get('fallback')} reply={str(out.get('reply'))[:40]!r}")
    except Exception as e:
        check("T8 e2e", False, f"erro: {e}")
    # T9 — provedor local saudável depois do cancelamento (chamada normal responde)
    try:
        o.cfg["router"]["enabled"] = False   # volta ao default (local_rapido)
        t0 = time.time()
        out2 = o.turn("Quanto é 2 + 2? Responda só o número.")
        dt = round(time.time() - t0, 1)
        check("T9 provedor saudável pós-cancel", out2.get("error") is None and bool(out2.get("reply")),
              f"{dt}s profile={out2.get('profile')} reply={str(out2.get('reply'))[:30]!r}")
    except Exception as e:
        check("T9 saúde pós-cancel", False, f"erro: {e}")

def run():
    print(">>> R2.1 — Execution Safety: T1–T9\n")
    tests_logica()
    test_cancel_real()
    tests_e2e()
    fails = [r for r in results if not r[1]]
    for cid, ok, detail in results:
        print(f"  [{'PASS' if ok else 'FALHOU'}] {cid}" + (f"   {detail}" if detail else ""))
    print(f"\n{len(results) - len(fails)}/{len(results)} OK.")
    if fails:
        print("FALHAS:", [f[0] for f in fails]); sys.exit(1)
    print("TODOS OS TESTES R2.1 PASSARAM.")

if __name__ == "__main__":
    run()
