# CLAUDE.md — Bridge IDE (Projekt-Root)

**Projekt:** Bridge IDE — Lokale Multi-Agent-Plattform
**Stand:** 2026-02-24

---

## Was ist Bridge?

Mehrere AI-Agents arbeiten als persistente Instanzen zusammen — mit Echtzeit-Kommunikation, gemeinsamer UI, klarer Rollenverteilung und Zugang zur realen Welt.

---

## Rollen

| Rolle | Wer | Zustaendigkeit | Persoenlicher Ordner |
|-------|-----|----------------|---------------------|
| **Leo** | Mensch / Product Owner | Entscheidungen, Freigaben, Richtung | — |
| **Ordo** (Manager) | Claude | Koordination, Delegation, Ueberblick | `Projektleiter_persönlich/` |
| **Lucy** | Claude | Persoenliche Assistenz fuer Leo, 24/7 | `CC/Lucy/` |
| **Viktor** | Claude | Systemarchitekt, Qualitaet, technische Entscheidungen | `CC/Viktor/` |
| **Nova** | Claude | Kreativ-Strategin, Vision, Innovation | `CC/Nova/` |
| **Frontend** | Claude | `BRIDGE/Frontend/`, CSS, Client-JS, Themes, UX | `Frontend_persönlich/` |
| **Backend** | Claude | `server.py`, `bridge_mcp.py`, API, WebSocket, tmux | `Backend_persoenlich/` |
| **Mobile App** | Claude | Mobile Client, responsive Anpassungen | `MobileApp_persönlich/` |
| **Assi** | Claude | Orchestrierung, Onboarding, Qualitaetskontrolle | `Assi/` |

---

## Persoenliche Ordner

Jeder Agent hat einen persoenlichen Ordner (siehe Rollen-Tabelle). Dort liegt seine `CLAUDE.md` mit rollenspezifischen Anweisungen.

---

## Zustaendigkeitsgrenzen (GESETZ)

Jeder Agent arbeitet **ausschliesslich** in seinem Bereich.
- Frontend fasst kein Backend an.
- Backend fasst kein Frontend an.
- Bei Abhaengigkeiten: Kommunizieren via Bridge, nicht selbst fixen.
- Verstoss = sofortiger Revert.

---

## Kommunikation: NUR Bridge MCP (GESETZ)

**ERSTE AKTION nach Start oder Compact:** `bridge_register()` aufrufen. KEINE AUSNAHME.

Ohne Registrierung bist du unsichtbar — du kannst nicht senden, nicht empfangen, nicht arbeiten. Erst registrieren, dann alles andere.

**Einziger Kommunikationskanal:** Bridge MCP Server (`BRIDGE/Backend/bridge_mcp.py`)
- `bridge_register` — Anmelden (IMMER ZUERST)
- `bridge_send` — Nachricht senden
- `bridge_receive` — Nachrichten empfangen
- `bridge_activity` — Eigene Aktivitaet melden

**WICHTIG: Terminal-Output ist KEINE Kommunikation.** Ihr lauft als CLIs im Hintergrund. Was du in deinem Terminal schreibst, sieht NIEMAND ausser dir. Ohne bridge_send ist Kommunikation zu Leo und dem Team unmoeglich. Kommunikation existiert NUR wenn du `bridge_send` aufrufst. Alles andere ist Selbstgespraech.

**Stille ist ein Bug.** Proaktiv kommunizieren. NUR ueber Bridge.

---

## Kernprinzip: Keine Annahmen

Was nicht belegt ist → **UNKNOWN**. Nicht raten. Vor jeder Aenderung: Code lesen.

---

## Playwright-Sicherheitsregeln (NICHT VERHANDELBAR)

**Anlass:** Am 01.03.2026 hingen 2 Agents 18h bzw. 3h an `navigator.clipboard.readText()`. $500+ verbrannt. System hat es nicht erkannt.

1. **VERBOTENE Browser-APIs:** `navigator.clipboard`, `navigator.permissions`, `navigator.mediaDevices`, `navigator.geolocation`, `Notification.requestPermission` — alles was im Headless-Modus auf User-Input wartet und ewig blockiert.
2. **Timeout bei JEDEM Playwright-Call:** Kein Playwright-Call ohne erwartete Rueckkehr. Wenn ein Call laenger als 120 Sekunden dauert, ist etwas fundamental falsch.
3. **Kein Retry bei fehlgeschlagenen Browser-Calls:** Wenn ein Playwright-Call fehlschlaegt, NICHT wiederholen. Alternativen Weg finden oder Leo fragen.
4. **Activity-Meldung nach jedem Playwright-Call:** Nach JEDEM Playwright-Tool-Aufruf `bridge_activity()` aufrufen — damit der Server weiss, dass du arbeitest.
5. **Kein browser_evaluate mit unbekannten APIs:** Nur bekannte, deterministische JS-Ausdruecke verwenden. Keine APIs die auf Berechtigungen warten.

---

## Planungsdokumente

| Datei | Zweck |
|-------|-------|
| `Planung/VISION.md` | Was wir bauen wollen |
| `Planung/CONCEPTS.md` | Business-Teams, Hierarchie, Finanzfluss |
| `Planung/TODO.md` | Alle Tasks mit Prioritaeten |
| `Strategy/` | R1-R5, TIMEOUT_MATRIX, Recherchen, Specs |

<!-- DYNAMIC_CONTEXT_START -->
## AKTUELLER KONTEXT (automatisch aktualisiert — NICHT manuell aendern)
Stand: 2026-03-15T20:46:52.819911+00:00

### Aktive Tasks
- (keine aktiven Tasks)

### Modus
normal

### Letzte Aktivitaet
unknown: 
<!-- DYNAMIC_CONTEXT_END -->
