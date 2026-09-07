"""Executor com timeout + HARD-CANCEL por SUBPROCESSO (Fase R2.1).

Roda uma geração de modelo num processo-filho isolado. Ao estourar o `timeout_s`,
o filho é ENCERRADO (terminate → kill) — o socket para o modelo local fecha e o
runtime libera a GPU/CPU para o fallback. Não altera Gateway/drivers/PMA: o filho
apenas reconstrói o gateway e roda o código INALTERADO.

Contrato: nada aqui bloqueia por mais que `timeout_s`. Sempre retorna
`(status, payload)` com status em {"ok", "timeout", "error"}.
"""
from __future__ import annotations

import multiprocessing as mp
import queue as _queue


def _hard_cancel(p) -> None:
    """Garante o encerramento do subprocesso (sem deixar órfão)."""
    if p.is_alive():
        p.terminate()          # Windows: TerminateProcess; Unix: SIGTERM
        p.join(5)
    if p.is_alive():
        p.kill()               # SIGKILL / TerminateProcess (último recurso)
        p.join(5)


def run_in_subprocess(target, args, timeout_s):
    """Roda `target(*args, q)` num subprocesso com limite `timeout_s`.

    `target` DEVE chamar `q.put((status, payload))` com o resultado. Retorna esse
    par; ou `("timeout", pid)` se estourar (o filho é encerrado antes de retornar);
    ou `("error", msg)` se o filho terminar sem pôr resultado.
    """
    ctx = mp.get_context("spawn")       # determinístico e seguro no Windows
    q = ctx.Queue()
    p = ctx.Process(target=target, args=(*args, q), daemon=True)
    p.start()
    try:
        result = q.get(timeout=timeout_s)   # espera o resultado OU estoura
    except _queue.Empty:
        pid = p.pid
        _hard_cancel(p)                      # timeout -> encerra o filho (hard-cancel)
        return ("timeout", pid)
    p.join(5)
    if p.is_alive():
        _hard_cancel(p)
    return result


def _gateway_worker(cfg, req, q) -> None:
    """PROCESSO-FILHO: reconstrói o gateway e gera. Nunca fica pendurado sem pôr algo."""
    try:
        from .adapter.gateway import ModelGateway
        q.put(("ok", ModelGateway(cfg).generate(req)))
    except Exception as e:  # qualquer falha vira erro normalizado (não trava o pai)
        q.put(("error", f"{type(e).__name__}: {e}"))


def generate_with_timeout(cfg, req, timeout_s):
    """API usada pelo Orquestrador. Roda `gateway.generate(req)` isolado, com timeout.

    Retorna `(status, payload)`:
      ("ok", PMAResponse) | ("timeout", pid) | ("error", msg)
    """
    return run_in_subprocess(_gateway_worker, (cfg, req), timeout_s)
