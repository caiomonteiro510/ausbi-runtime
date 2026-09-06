# AUSBI Runtime

A Python CLI/runtime for a personal AI assistant, built around a strict **adapter/gateway pattern** that keeps the LLM provider completely swappable without touching the core logic.

> AUSBI ("Apenas Um Sistema Bem Inteligente") is a personal-assistant project. This repo is the **runtime** — the engine that boots identity, selects relevant memory, talks to a model through an isolated adapter, and persists results with explicit user confirmation. The assistant's actual knowledge base (a private Obsidian vault) is not part of this repo; the runtime works against any vault that follows the expected file layout.
>
> ## Why this architecture
>
> Most "AI assistant" scripts hardcode a single provider's SDK straight into the business logic. That makes switching models, adding a local fallback, or writing tests without hitting a real API painful. This project inverts that:
>
> - **One contract, many providers.** `ausbi/adapter/base.py` defines a neutral `ProviderDriver` interface. `ausbi/adapter/drivers/anthropic_driver.py` is the *only* file in the codebase that imports the Anthropic SDK; `openai_compatible_driver.py` covers every OpenAI-compatible provider (Groq, Ollama, OpenAI itself) with a single driver, since they all speak the same `/v1/chat/completions` protocol.
> - - **A neutral protocol in between.** `ausbi/adapter/pma.py` defines `PMARequest`/`PMAResponse` — plain dataclasses that carry identity, conversation history, retrieved context and routing hints. Nothing above the adapter layer knows what "Anthropic" or "Groq" even is.
>   - - **Deterministic routing, not another LLM call.** `ausbi/router.py` picks a model profile (fast local model vs. deeper local model vs. an external provider) using pure keyword/length heuristics — no network calls, fully unit-testable, privacy-first (vault data stays local unless the user explicitly overrides).
>     - - **Hard-cancel timeouts.** `ausbi/execution.py` runs generation in an isolated subprocess so a stuck local model can be killed outright (not just abandoned) and control handed to a fallback profile — verified in `tests/test_execution.py` with a real subprocess kill, not just mocks.
>       - - **Confirm-before-write persistence.** The orchestrator never writes to the knowledge base silently: every write is previewed and requires explicit confirmation (`/salvar` in the CLI).
>        
>         - ## Structure
>        
>         - ```
>           AUSBI_Runtime/
>           ├── main.py                     # CLI: boot + REPL + confirm-before-write persistence
>           ├── server.py                   # thin HTTP bridge (same Orchestrator, alternate front-end)
>           ├── config.yaml                 # model profiles — this is the only place you touch to switch models
>           ├── requirements.txt
>           ├── .env.example
>           └── ausbi/
>               ├── config.py               # defaults + config.yaml + .env merge
>               ├── identity.py             # assembles the identity contract from the vault
>               ├── memory.py                # keyword-based relevant-memory selection + append-only writes
>               ├── orchestrator.py         # the turn loop: identity -> memory -> model -> persistence -> log
>               ├── router.py                # deterministic profile selection (no LLM call)
>               ├── execution.py             # subprocess isolation + hard-cancel timeout/fallback
>               ├── logger.py                # append-only JSONL turn log
>               └── adapter/                 # the swappable boundary
>                   ├── pma.py                # neutral request/response contracts
>                   ├── base.py               # driver contract + capability descriptor
>                   ├── gateway.py             # profile -> driver routing
>                   └── drivers/
>                       ├── anthropic_driver.py         # only file that imports the Anthropic SDK
>                       └── openai_compatible_driver.py # Groq / OpenAI / Ollama via one driver
>           └── tests/
>               ├── test_router.py           # ~20 deterministic input->profile cases
>               ├── test_execution.py        # timeout/fallback logic + a real subprocess kill test
>               └── timeout_probe.py         # importable worker processes for the subprocess tests
>           ```
>
> ## Try it without an API key
>
> ```bash
> python main.py --selftest
> ```
>
> Boots identity + memory selection against the configured vault and shows what *would* be sent — without ever calling a model.
>
> ## Run it for real
>
> ```bash
> pip install -r requirements.txt
> cp .env.example .env      # fill in ANTHROPIC_API_KEY (or GROQ_API_KEY / a local Ollama profile)
> python main.py
> ```
>
> ```
> you> texto                        talk to the assistant
> /salvar <tipo> "<conteúdo>"       persist a note (confirmed before writing)
> /modelo [<perfil>|auto]           pin or release the model profile for this session
> /status · /ajuda · /sair
> ```
>
> ## Switching models
>
> Edit `config.yaml` — nothing else changes. Adding a genuinely new provider (not just a new OpenAI-compatible endpoint) means implementing one new driver against `ausbi/adapter/base.py` and registering it in `gateway.py`; the orchestrator, memory and identity layers never change.
>
> ## Tests
>
> ```bash
> pip install psutil   # only needed for the subprocess-kill test
> python tests/test_router.py
> python tests/test_execution.py
> ```
>
> ## Honest limitations (v0.1)
>
> - Memory selection is structural/keyword-based — local semantic search is a planned slice, not implemented yet.
> - - Persistence is explicit (`/salvar`) — automatic classification of what's worth saving is a future slice.
>   - - One provider drives a conversation at a time; multi-model routing across a single turn isn't implemented.
>    
>     - ## License
>    
>     - MIT — see [LICENSE](LICENSE).
