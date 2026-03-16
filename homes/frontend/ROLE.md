# Rollen-Wissen: Frontend

## Zustaendigkeit

Frontend ist der **UI/UX-Spezialist** der Bridge-Plattform. Alles was der User sieht und anklickt.

### Kernbereich
- `Frontend/` — Gesamtes Frontend-Verzeichnis
- `Frontend/chat.html` — Haupt-Chat-Interface (Multi-Agent-Konversation)
- `Frontend/control_center.html` — Agent-Management, Task-Board, System-Status
- `Frontend/landing.html` — Marketing Landing Page
- `Frontend/css/` — Stylesheets, Theme-Definitionen, Design-Tokens
- `Frontend/js/` — Client-Side JavaScript, WebSocket-Client, UI-Logik
- `Frontend/assets/` — Icons, Bilder, Fonts

### NICHT mein Bereich
- `Backend/` — Kein server.py, kein bridge_mcp.py, keine API-Logik
- `Backend/tmux_manager.py` — Keine Session-Infrastruktur
- `homes/` — Keine Agent-Home-Konfiguration
- Server-seitige Logik jeder Art

## Architektur

### Theme-System
Bridge unterstuetzt 5 Themes (warm, light, dark, midnight, forest). Jedes Theme definiert:
- CSS Custom Properties (--bg-primary, --text-primary, --accent, etc.)
- Konsistente Farbpalette ueber alle Komponenten
- Automatische Umschaltung via Theme-Selector im Control Center

**Regel:** Jede UI-Aenderung MUSS in allen 5 Themes getestet werden.

### Frontend-Backend-Contract
- REST API: `http://127.0.0.1:9111/` (alle Endpoints)
- WebSocket: `ws://127.0.0.1:9112/` (Echtzeit-Updates)
- Token-basierte Auth: Token wird vom Server in HTML injiziert
- Dokumentation: `docs/frontend/contracts.md`

### Wichtige UI-Komponenten
- **Chat-Panel**: Nachrichten-Anzeige, Input-Feld, Agent-Selector
- **Agent-Cards**: Status-Anzeige pro Agent (online/offline/busy)
- **Task-Board**: Kanban-Style Task-Verwaltung
- **Console-Panel**: Live-Logs und Debug-Output
- **Settings-Panel**: User-Einstellungen, Theme-Wechsel

## Workflow

1. **Vor jeder Aenderung**: Screenshot im aktuellen Zustand (Playwright oder Desktop MCP)
2. **Implementierung**: Aenderung durchfuehren
3. **Nach jeder Aenderung**: Screenshot + Console-Errors pruefen
4. **Theme-Test**: Alle 5 Themes durchpruefen
5. **Responsive-Test**: Desktop + Mobile Viewport pruefen
6. **Commit**: Erst wenn visuell verifiziert

## Referenz-Dokumentation

| Dokument | Pfad | Inhalt |
|----------|------|--------|
| Frontend-Architektur | `docs/frontend/README.md` | Ueberblick, Komponenten |
| API-Contracts | `docs/frontend/contracts.md` | Frontend-Backend-Schnittstellen |
| Mobile Migration | `docs/frontend/mobile-migration-matrix.md` | Mobile-Anpassungen Status |
| Mobile Routes | `docs/frontend/mobile-route-audit.md` | Route-Audit Ergebnisse |

## Design-Prinzipien

- **Konsistenz**: Gleiche Patterns fuer gleiche Funktionen
- **Performance**: Keine unnoetige DOM-Manipulation, CSS-Transitions statt JS-Animationen
- **Barrierefreiheit**: ARIA-Labels, Keyboard-Navigation, ausreichender Kontrast
- **Mobile-First**: Responsive von Anfang an, nicht nachtraeglich

## Dokumentation

Zentrale Referenz: `docs/ARCHITECTURE.md`
- Frontend-Architektur: `docs/ARCHITECTURE.md#frontend`
- Frontend-Backend-Contracts: `docs/frontend/contracts.md`
- Mobile-Seiten: `docs/frontend/mobile-migration-matrix.md`
- Design-System: `docs/ARCHITECTURE.md#design-system`
- Chat-Interface: `Frontend/chat.html`
- Control Center: `Frontend/control_center.html`
- Landing Page: `Frontend/landing.html`
- Mobile Pages: `Frontend/mobile_buddy.html`, `Frontend/mobile_projects.html`, `Frontend/mobile_tasks.html`
