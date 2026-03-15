# Bridge IDE — Launch Checklist

Stand: 2026-03-08 04:10 CET

## Leo muss entscheiden

- [ ] **GitHub Repo erstellen** — 6 Dateien haben REPO_URL Platzhalter
- [ ] **Lizenz bestaetigen** — Apache 2.0 (Team-Abstimmung 77.8%)
- [ ] **Launch-Datum festlegen** — Aria, Finn, Mira brauchen Vorlauf

## Dokumentation

- [x] README.md — Feature-Liste, Quick Start, Architecture, Tech Stack
- [x] GETTING_STARTED.md — User-Onboarding (0 Kontext, 10 Minuten)
- [x] ONBOARDING.md — Agent-Referenz (114 MCP Tools, Task-System, Best Practices)
- [x] SETUP.md — Installation, Konfiguration, Troubleshooting
- [x] API.md — REST API Referenz
- [x] ARCHITECTURE.md — System-Architektur
- [x] CONTRIBUTING.md — Contribution Guidelines
- [x] LICENSE — Apache 2.0
- [x] team.json.example — Template fuer neue User

## Code

- [x] Backup erstellt (245MB tar.gz)
- [ ] Code-Sync Source → Release-Clone (Viktor, in Arbeit)
- [ ] Release-Audit (codex_release_audit, in Arbeit)
- [x] Panel UI Bugs fixen (Frontend, 4/4 DONE: Kante, Viewport, Counter, DM-Panels)

## Marketing-Content

- [x] 8 Blog-Artikel (6 sofort publishbar, 2 brauchen REPO_URL)
- [x] Show HN Draft v2 (Leo's Origin Story)
- [x] Elevator Pitch v2 (4h+ autonom, HackerOne Proof)
- [x] Key Messages
- [x] Twitter Threads (Mira, offline)
- [x] Reddit Posts (Mira, offline)
- [x] LinkedIn Posts (Mira, offline)
- [x] Content-Kalender Q1

## Accounts

- [x] Twitter @bridgeace_ide
- [x] Dev.to bridgeace
- [x] Reddit u/BridgeACE_IDE
- [x] Product Hunt
- [x] Substack
- [x] bridgeide.com Domain
- [x] ProtonMail
- [x] TutaMail
- [ ] GitHub Repo (Leo-Blocker)
- [ ] Discord (blocked)

## REPO_URL Platzhalter (5 Dateien)

1. BRIDGE/README.md (1x)
3. Aria/marketing/content/blog-01-build-your-first-agent-team.md (1x)
4. Aria/marketing/content/show-hn-draft.md (1x)
5. Aria/marketing/content/CONTRIBUTING-draft.md (1x)
6. Aria/marketing/content/README-draft.md (1x)

Sobald Leo das Repo erstellt: `grep -rl "REPO_URL\|<repo-url>" . | xargs sed -i 's|REPO_URL|https://github.com/org/bridge-ide|g'`
