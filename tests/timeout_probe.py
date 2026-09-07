"""Workers IMPORTÁVEIS para os testes de subprocesso da R2.1 (spawn-safe).

Sem efeitos colaterais em import: o processo-filho (spawn) importa este módulo
limpo. NÃO colocar código de execução no nível do módulo.
"""
from __future__ import annotations

import os
import time


def slow_marker_worker(marker_dir, total_s, q):
    """Escreve 'started', bate 'heartbeat' periódico e só escreve 'done' no fim.

    Usado p/ provar o cancelamento REAL: se o processo for morto no meio, o
    'done' NUNCA aparece e o 'heartbeat' para de avançar (não fica órfão).
    """
    open(os.path.join(marker_dir, "started"), "w").close()
    t0 = time.time()
    while time.time() - t0 < total_s:
        with open(os.path.join(marker_dir, "heartbeat"), "w") as f:
            f.write(str(time.time()))
        time.sleep(0.2)
    open(os.path.join(marker_dir, "done"), "w").close()
    q.put(("ok", "finished"))


def fast_worker(value, q):
    """Termina imediatamente — p/ testar o caminho de sucesso do executor."""
    q.put(("ok", value))
