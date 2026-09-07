"""Configuração do runtime: defaults embutidos + override opcional em config.yaml,
mais o ambiente (.env). Resolve o caminho do vault.

Roda sem dependências: se pyyaml/python-dotenv não estiverem instalados, usa os
defaults embutidos e o os.environ direto (permite o --selftest funcionar já).
"""
from __future__ import annotations

import os
from pathlib import Path

RUNTIME_DIR = Path(__file__).resolve().parent.parent  # .../AUSBI_Runtime

DEFAULTS: dict = {
    "vault_path": "../AUSBI_CORE",
    "default_profile": "padrao",
    "profiles": {
        "padrao": {"provider": "anthropic", "model": "claude-opus-5", "max_tokens": 8192},
    },
    # Arquivos obrigatórios — Protocolo Operacional §3.
    "identity_files": [
        "00 - Identidade/AUSBI Genesis.md",
        "07 - Sistema/Core Principles.md",
        "01 - Memória/Preferências.md",
        "01 - Memória/Usuario.md",
    ],
    "orientation_files": [
        "01 - Memória/Projetos.md",
        "01 - Memória/Objetivos.md",
        "04 - Tarefas/Tarefas Atuais.md",
    ],
    # Destino de persistência por tipo — Protocolo Operacional §6.
    "persistence_targets": {
        "decisao": "05 - Decisões/Decisões AUSBI.md",
        "tarefa": "04 - Tarefas/Tarefas Atuais.md",
        "conhecimento": "02 - Conhecimento/Base de Conhecimento.md",
        "evento": "01 - Memória/Eventos Importantes.md",
        "memoria": "01 - Memória/Usuario.md",
    },
    "log_file": "logs/turnos.jsonl",
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv(RUNTIME_DIR / ".env")
    except ImportError:
        pass  # sem python-dotenv: usa os.environ direto


def _resolve_vault(vault_path: str) -> Path:
    p = Path(vault_path)
    return p if p.is_absolute() else (RUNTIME_DIR / p).resolve()


def _api_key_env_for(profile: dict) -> str:
    # Anthropic não passa api_key_env explícito no perfil (driver dedicado);
    # provedores OpenAI-compatíveis (groq/ollama/openai) declaram o próprio.
    return profile.get("api_key_env") or {"anthropic": "ANTHROPIC_API_KEY"}.get(
        profile.get("provider", "anthropic"), "OPENAI_API_KEY"
    )


def load_config() -> dict:
    _load_env()
    cfg = dict(DEFAULTS)
    yaml_path = RUNTIME_DIR / "config.yaml"
    if yaml_path.exists():
        try:
            import yaml
            with open(yaml_path, encoding="utf-8") as f:
                cfg = _merge(DEFAULTS, yaml.safe_load(f) or {})
        except ImportError:
            pass  # sem pyyaml: mantém defaults embutidos
    cfg["_vault_dir"] = str(_resolve_vault(cfg["vault_path"]))
    cfg["_runtime_dir"] = str(RUNTIME_DIR)
    active_profile = cfg["profiles"].get(cfg["default_profile"], {})
    cfg["_api_key_env"] = _api_key_env_for(active_profile)
    cfg["_has_api_key"] = bool(os.environ.get(cfg["_api_key_env"]))
    return cfg
