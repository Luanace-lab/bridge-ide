# System Map
Generated: 2026-03-15T17:26:52.892023+00:00

## Server
- HTTP: 127.0.0.1:9111
- WebSocket: 127.0.0.1:9112
- Auth: strict

## Agents
- assi: Koordinator. Orchestrierung, Onboarding, Qualitaetskontrolle. (L1, claude, reports_to=user, inaktiv)
- ordo: Projektleiter. Koordination, Delegation, Reviews, Qualitaetsschutz. (L1, claude, reports_to=user, aktiv)
- lucy: Persoenliche Assistentin. Strukturiert den Tag des Owners, filtert, priorisiert. (L1, claude, reports_to=user, inaktiv)
- nova: Kreativ-Strategin. Produkt-Vision, Endnutzer-Perspektive, Marketing. (L1, claude, reports_to=user, inaktiv)
- viktor: Systemarchitekt. Architektur-Reviews, Code-Qualitaet, technische Standards. (L1, claude, reports_to=user, aktiv)
- backend: Senior Backend-Entwickler. server.py, API-Endpunkte, WebSocket. (L2, claude, reports_to=viktor, aktiv)
- frontend: Senior Frontend-Designer. UI, CSS, Client-JavaScript, Themes. (L2, claude, reports_to=viktor, aktiv)
- frontend2: Frontend-Entwickler 2. Dashboard Upgrade, Organigramm, UI. (L2, claude, reports_to=viktor, inaktiv)
- techwriter: Technischer Autor. Dokumentation, README, API-Docs. (L2, claude, reports_to=ordo, inaktiv)
- kai: Real-World Integration Specialist. E2E-Tests, externe Services. (L2, claude, reports_to=nova, inaktiv)
- buddy: Persoenlicher Concierge. Breitester alltagspraktischer Aktionsraum. Onboarding, Concierge, Companion. (L1, codex, reports_to=user, aktiv)
- claude: Claude Agent B. Release-Blocker Implementierung. (L2, claude, reports_to=viktor, inaktiv)
- codex: Senior Coder (Codex-Engine). Architekturkritische Implementierungen. (L2, codex, reports_to=viktor, aktiv)
- codex_2: Senior Coder (Codex-Engine). Buddy Knowledge-Architektur. (L2, codex, reports_to=viktor, inaktiv)
- stellexa: Multi-Engine Agent. Bridge-Haertung, CLI-Integration, Tooling. (L2, claude, reports_to=viktor, inaktiv)
- qwen2: Implementierer (Qwen-Engine). UI-Tasks. (L3, qwen, reports_to=viktor, inaktiv)
- qwen3: Tester (Qwen-Engine). E2E-Tests. (L3, qwen, reports_to=viktor, aktiv)
- atlas: Senior Software Engineer. Multi-Task-System Backend-Implementierung. (L2, claude, reports_to=viktor, inaktiv)
- nexus: Senior Software Engineer. Multi-Task-System Koordinationsschicht. (L2, claude, reports_to=viktor, inaktiv)
- echo: Voice Engineer. ElevenLabs + Twilio, Audio-Pipeline. (L3, claude, reports_to=kai, inaktiv)
- iris: Vision Engineer. OpenCV + v4l2loopback, Video-Pipeline. (L3, claude, reports_to=kai, inaktiv)
- jura: Legal Agent / Compliance-Prueferin. Policy-Analyse, Richtlinien-Konformitaet. (L1, claude, reports_to=user, inaktiv)
- aria: Brand Strategist & Growth Lead. Leitet das Marketing-Team. Positionierung von Bridge IDE. (L2, claude, reports_to=nova, inaktiv)
- mira: Social Media & Community Manager. Stimme von Bridge IDE nach aussen. Screenshots und Content. (L3, claude, reports_to=aria, inaktiv)
- finn: Content Creator & DevRel. Technische Inhalte, Tutorials, Developer Docs fuer Bridge IDE. (L3, claude, reports_to=aria, inaktiv)
- sec_all: Security Engineer. Platform security assessments and hardening. (L3, claude, reports_to=atlas, inaktiv)
- mobile: Mobile App (in Arbeit — noch nicht im Release enthalten). (L2, claude, reports_to=viktor, inaktiv)
- mika: Senior UI/UX Designerin & WebApp-Entwicklerin. Design-Systeme, Themes, Component-Libraries, Playwright-Verifikation. (L2, claude, reports_to=viktor, inaktiv)
- scale_lab_alpha: Claude worker for live Bridge task-system probing. Focus: queue, claim/ack, task execution discipline, Bridge-only output. (L2, claude, reports_to=user, inaktiv)
- scale_lab_beta: Claude worker for scalable multi-task architecture. Focus: conflict-free scheduling, concurrency control, backpressure, task-model design. (L2, claude, reports_to=user, inaktiv)
- gemini_agent: Senior Engineer. Gemini-Engine Runtime- und Tooling-Checks. (L2, gemini, reports_to=viktor, aktiv)
- trading_analyst: Market-Analyst. Marktdaten analysieren, Trends erkennen, Reports erstellen. (L3, claude, reports_to=buddy, inaktiv)
- trading_strategist: Trading-Stratege. Handelsstrategien entwickeln, Backtesting, Signal-Generierung. (L3, claude, reports_to=buddy, inaktiv)
- trading_risk: Risk Manager. Portfolio-Risiko bewerten, Limits setzen, Alerts ausloesen. (L3, claude, reports_to=buddy, inaktiv)
- marketing_content: Content Creator. Blog-Posts, Social Media Posts, Newsletter schreiben. (L3, claude, reports_to=buddy, inaktiv)
- marketing_seo: SEO-Spezialist. Keyword-Recherche, On-Page-Optimierung, Ranking-Analyse. (L3, claude, reports_to=buddy, inaktiv)
- marketing_campaign: Kampagnen-Manager. Kampagnen planen, ausfuehren, Performance tracken. (L3, claude, reports_to=buddy, inaktiv)
- legal_contract: Vertragsanalyst. Vertraege pruefen, Risiken identifizieren, Klauseln bewerten. (L3, claude, reports_to=buddy, inaktiv)
- legal_compliance: Compliance Officer. Regulatorische Anforderungen pruefen, Richtlinien durchsetzen. (L3, claude, reports_to=buddy, inaktiv)
- legal_researcher: Rechtsrechercheur. Urteile, Gesetze, Praezedenzfaelle recherchieren. (L3, claude, reports_to=buddy, inaktiv)
- codex_3: Senior Coder (Codex-Engine). Buddy Knowledge-Architektur. (L2, codex, reports_to=viktor, inaktiv)

## Engines
- claude
- codex
- qwen
- gemini

## Knowledge Vault
- Agents/ (1 Eintraege)
- Archiev/ (0 Eintraege)
- Decisions/ (0 Eintraege)
- Projects/ (17 Eintraege)
- Shared/ (2 Eintraege)
- Tasks/ (0 Eintraege)
- Teams/ (0 Eintraege)
- Users/ (7 Eintraege)