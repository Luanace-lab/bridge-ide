# BRIDGE Working Copy

This working copy contains the live local orchestration platform under `Backend/` and `Frontend/`, not a clean release-only wrapper package.

## Verifizierter Ist-Zustand

- `Backend/server.py` is the active HTTP/WebSocket entry point.
- `GET /` and `GET /ui` serve `Frontend/control_center.html`.
- `Frontend/chat.html` is the second major UI surface.
- The current codebase contains live paths for agent registration, messaging, tasks, scope locks, whiteboard, workflows, automations, approvals, runtime configuration, and restart handling.
- The frontend is a static multi-page setup without a build step; `chat.html` and `control_center.html` are both large single-file application surfaces.

## Root-Struktur

The repository root currently mixes several classes of artifacts:

- active product code in `Backend/` and `Frontend/`
- live/session state in `.agent_sessions/` and `Backend/*` runtime stores
- archived material in `Archiev/`
- personal or parallel-work areas such as `Frontend_persönlich/`
- analysis and resume material such as `Dokumentation_Bridge/` and the repo-internal `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/`

## Dokumentation

- Root-level operational documents currently visible here: `README.md`, `CLAUDE.md`, `LAUNCH_CHECKLIST.md`, `TEAM_FINDINGS.md`
- Root `docs/` exists and currently holds the active frontend and gap-audit notes for this working copy.
- Detailed archived copies live in `Archiev/docs/`; backend infrastructure reference lives in `Backend/docs/`.
- Creator-Reliability-Spec fuer die produktive Härtung der Media-/Creator-Strecke liegt in `Backend/docs/CREATOR_PLATFORM_RELIABILITY_SPEC.md`.
- WhatsApp bootstrap and release prerequisites for this working copy are documented in `docs/whatsapp-setup.md`.
- Telegram bootstrap and release prerequisites for this working copy are documented in `docs/telegram-setup.md`.
- Der kanonische Resume-/Projekt-Doku-Satz fuer diese Working Copy liegt innerhalb des Repositories unter `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/`.

## Wichtige Abweichung

Packaging metadata in `pyproject.toml` and `setup.py` points at `bridge_ide.cli`, and the active root package `bridge_ide/` is present again in this working copy.

Verifiziert durch Ausführung:
- `python3 setup.py bdist_wheel`
- `python3 -m pip install --no-deps --target /tmp/bridge_pkg_target dist/bridge_ide-0.1.0-py3-none-any.whl`
- `env PATH=/tmp/bridge_pkg_venv3/bin:$PATH bridge-ide stop`
- `env PATH=/tmp/bridge_pkg_venv3/bin:$PATH bridge-ide start`

Der dokumentierte CLI-Pfad ist damit operabel. Verifiziert durch Ausfuehrung: der zusaetzliche UI-Server auf `8787` wird nach Orphan-Bereinigung wieder sauber gestartet. `ordo` bleibt grundsaetzlich extern credential-abhaengig, startete in den zuletzt verifizierten Direktlaeufen aber erfolgreich.
