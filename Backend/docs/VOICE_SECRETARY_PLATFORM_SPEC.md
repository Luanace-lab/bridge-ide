# VOICE-AGENT & SECRETARY PLATFORM SPEC

Stand: 2026-03-14
Autor: Viktor (Operative Projektleitung BRIDGE)
Revision: R3 — Battle-Review 3 Runden abgeschlossen (18 + 8 Befunde, alle adressiert)
Status: FREIGEGEBEN — Implementierungsgrundlage

---

## 1. Ziel

Die BRIDGE wird um einen Voice-Agent und eine Secretary-Plattform erweitert. Agents nehmen Anrufe entgegen, fuehren Gespraeche, planen Termine, verwalten Emails und koordinieren Aufgaben — lokal orchestriert, mit optionaler Telefonie-Anbindung.

### 1.1 Produkt-Differenzierung

Warum die BRIDGE statt Bland AI, Synthflow ($29/mo), Smith.ai ($140/mo) oder einer menschlichen Sekretaerin:

1. **Lokal orchestriert** — die Agent-Logik laeuft auf dem eigenen Rechner. Nur die Telefonie-Anbindung (SIP/WebRTC) und TTS/STT benoetigen externe Services.
2. **Multi-Agent-Koordination** — der Voice-Agent ist nicht isoliert. Er kann Bridge-Agents beauftragen: "Pruefe den Kalender", "Erstelle eine Aufgabe", "Sende eine Zusammenfassung per Email".
3. **Keine Plattformgebuehr** — keine monatlichen Abo-Kosten fuer die Plattform. Telefonie-Provider-Kosten (z.B. Twilio) fallen pro Minute an.
4. **Kontextbewusst** — der Secretary-Agent kennt das Unternehmen (Knowledge Engine), die laufenden Projekte (Tasks), die Teamstruktur (Agents) und die Kommunikationshistorie (Messages).
5. **Multi-Channel** — nicht nur Telefon. Email-Triage, Kalender-Management, Aufgaben-Delegation, Chat-Antworten — alles ueber eine Secretary-Instanz.
6. **Anpassbar** — Begruessung, Tonalitaet, Eskalationsregeln, Geschaeftszeiten, Weiterleitungslogik — alles konfigurierbar via Knowledge Engine.

### 1.2 Zielgruppen

- Kleine Unternehmen (1-20 Mitarbeiter) ohne dedizierte Rezeption
- Freelancer und Berater, die Anrufe waehrend der Arbeit nicht annehmen koennen
- Agenturen, die Kundenanfragen triagieren und priorisieren muessen
- Teams, die einen AI-Assistenten fuer Termin- und Email-Management brauchen

### 1.3 6-Monats-Vision

In 6 Monaten soll ein User:

1. Eine Telefonnummer konfigurieren (via Twilio, Vonage oder SIP-Provider)
2. Geschaeftszeiten und Begruessung festlegen
3. Der Voice-Agent nimmt Anrufe entgegen, stellt sich vor, fragt nach dem Anliegen
4. Bei Terminwunsch: prueft Kalender (Google Calendar via MCP), schlaegt Zeiten vor, bestaetigt
5. Bei Rueckrufwunsch: erstellt Aufgabe im Bridge-Task-System, benachrichtigt den User
6. Bei dringend: leitet weiter an Mobilnummer oder eskaliert via Telegram/WhatsApp
7. Nach jedem Anruf: Zusammenfassung per Email/Telegram mit Transkript
8. Email-Triage: sortiert Posteingang, beantwortet Standardanfragen, eskaliert Wichtiges

---

## 2. Verifizierter Ist-Zustand

### 2.1 Was die BRIDGE heute hat

| Faehigkeit | Vorhanden | Details |
|---|---|---|
| Telefonie-MCP-Tools | STUBS — kein Backend | `bridge_phone_call`, `bridge_phone_speak`, `bridge_phone_listen`, `bridge_phone_hangup`, `bridge_phone_status` existieren als MCP-Tool-Definitionen, aber proxyen gegen `127.0.0.1:8877` (Voice Gateway). Kein Voice Gateway existiert. Jeder Aufruf liefert Connection Refused. Nur Outbound-Design, kein Inbound-Handling. |
| Voice-Transkription | MCP-Tool vorhanden, Whisper-Installation UNKNOWN | `bridge_voice_transcribe` delegiert an lokalen Whisper-Service. Ob installiert und funktional: UNKNOWN. |
| WhatsApp-Voice | JA | `bridge_whatsapp_voice` |
| Email | JA | `bridge_email_send`, `bridge_email_read`, `bridge_email_execute` |
| Telegram | JA | `bridge_telegram_send`, `bridge_telegram_read` |
| Slack | JA | `bridge_slack_send`, `bridge_slack_read` |
| Google Calendar | JA (MCP) | `gcal_list_events`, `gcal_create_event`, `gcal_find_my_free_time`, `gcal_find_meeting_times` |
| Gmail | JA (MCP) | `gmail_search_messages`, `gmail_read_message`, `gmail_create_draft` |
| Task-System | JA | `bridge_task_create`, `bridge_task_claim`, `bridge_task_done` |
| Knowledge Engine | JA | Persistente Regeln, Kontakte, Praeferenzen |
| Scheduling | JA | `bridge_cron_create` fuer regelmaessige Checks |
| Agent-Kommunikation | JA | `bridge_send`, `bridge_receive` fuer Multi-Agent-Workflows |

### 2.2 Was NICHT vorhanden ist

| Faehigkeit | Status |
|---|---|
| Real-time Voice-Conversation (bidirektional) | NICHT VORHANDEN — `bridge_phone_speak`/`listen` sind sequentiell, nicht real-time |
| TTS-Engine-Integration (Text-to-Speech) | UNKNOWN — Abhaengig von Telefonie-Provider |
| STT-Streaming (live Transkription waehrend Gespraech) | NICHT VORHANDEN |
| Anrufbeantworter-/IVR-Logik | NICHT VORHANDEN |
| Kontakt-Datenbank | NICHT VORHANDEN |
| Anruf-Log mit Transkripten | NICHT VORHANDEN |
| Email-Triage-Pipeline | NICHT VORHANDEN |
| Geschaeftszeiten-/Weiterleitungslogik | NICHT VORHANDEN |
| Kalender-Buchungslogik (Slot-Findung + Bestaetigung) | NICHT VORHANDEN (Calendar MCP existiert, Buchungslogik nicht) |

### 2.3 Externe MCP-Server (Repositories existieren, Produktionsreife UNKNOWN)

| MCP-Server | Faehigkeit | Integration | Verifiziert |
|---|---|---|---|
| **Retell AI MCP** | Voice-Agent-Erstellung, Anrufsteuerung | MCP-Config | UNKNOWN — PoC noetig |
| **Vapi MCP** | Voice-Agent-API, Assistenten-Management, Anrufe | MCP-Config | UNKNOWN — PoC noetig |
| **Vonage Telephony MCP** | Anrufe, SMS, SIP-Integration | MCP-Config | UNKNOWN — PoC noetig |
| **VoiceMode MCP** (mbailey/voice-mcp) | Sprachkonversation mit Claude Code | MCP-Config + OpenAI API Key | Open Source, Community |

Vor Architekturentscheidung: mindestens einen Provider real testen (Slice A1 PoC).

### 2.4 Harte technische Grenzen

- **Latenz**: Natuerliche Gespraeche erfordern <500ms Antwortzeit. Claude API hat typisch 1-3s Latenz fuer eine Antwort. Das ist fuer Telefonie zu langsam ohne Caching/Prefetching oder spezialisierte Voice-AI-Provider.
- **Real-time Audio**: Die Bridge verarbeitet heute kein Streaming-Audio. `bridge_phone_listen` wartet auf Ende des Sprechakts, transkribiert, gibt Text zurueck.
- **TTS-Qualitaet**: Text-to-Speech ueber Telefon erfordert natuerlich klingende Stimmen. Standard-TTS (pyttsx3, gTTS) klingt robotisch. Professionelle TTS (ElevenLabs, OpenAI TTS, Google Cloud TTS) sind Cloud-Services.

---

## 3. Diagnostizierte Hauptprobleme

### 3.1 Latenz-Gap

Claude API (1-3s) ist zu langsam fuer natuerliche Telefongespräche. Loesung: Spezialisierte Voice-AI-Provider (Retell AI, Vapi) uebernehmen die Echtzeit-Konversation. Die Bridge orchestriert die Geschaeftslogik dahinter.

### 3.2 Kein Gespraechs-Workflow

Die Bridge hat `bridge_phone_call` und `bridge_phone_speak`, aber keinen Workflow, der einen Anruf von Begruessung bis Verabschiedung steuert, Entscheidungen trifft und Aktionen ausloest.

### 3.3 Kein Email-Triage-System

Die Bridge kann Emails lesen und senden (Gmail MCP), aber es gibt keinen automatisierten Workflow, der Emails klassifiziert, priorisiert und beantwortet.

### 3.4 Keine Kontakt-Datenbank

Anrufer werden nicht erkannt. Es gibt kein Mapping von Telefonnummer zu Name, Firma, Historie.

---

## 4. Zielarchitektur

### 4.1 Grundsatz: Bridge als Orchestrator, Voice-Provider als Runtime

Die Bridge baut KEINE eigene Echtzeit-Voice-Engine. Die Bridge orchestriert:

- **Voice-Provider** (Retell AI, Vapi, oder Vonage + eigene Logik) fuer Echtzeit-Telefonie
- **Calendar MCP** fuer Terminbuchung
- **Gmail MCP** fuer Email-Management
- **Task-System** fuer Aufgaben-Delegation
- **Knowledge Engine** fuer Geschaeftsregeln und Kontakte
- **Multi-Channel** fuer Benachrichtigungen

### 4.2 Voice-Agent-Architektur

#### Option A: Externer Voice-Provider (empfohlen fuer V1)

```
Anruf eingehend
  → Twilio/Vonage routet an Retell AI / Vapi
  → Voice-Provider fuehrt Echtzeit-Gespraech (TTS + STT + LLM)
  → Bei Aktion (Termin, Rueckruf, Weiterleitung):
    → Webhook an Bridge-Server
    → Bridge fuehrt Aktion aus (Kalender, Task, Weiterleitung)
    → Ergebnis zurueck an Voice-Provider
  → Nach Gespraech:
    → Transkript an Bridge
    → Bridge erstellt Zusammenfassung + Aktionen
    → Benachrichtigung an User
```

Vorteile: 300-800ms Latenz je nach Provider (Retell AI ~600ms, Vapi 500-800ms), professionelle TTS-Stimmen, skalierbar.
Kosten: Retell AI ~$0.07-0.15/Min, Vapi ~$0.05-0.10/Min, Twilio ~$0.02/Min fuer Telefonie.

#### Option B: Bridge-native Voice (spaeter, experimentell)

```
Anruf eingehend
  → SIP/WebRTC an Bridge-Server
  → Bridge-eigene STT (faster-whisper, lokal)
  → Claude API fuer Antwort-Generierung
  → Bridge-eigene TTS (Coqui TTS oder lokal)
  → Audio zurueck an Anrufer
```

Vorteile: Vollstaendig lokal, keine Cloud-Abhaengigkeit.
Nachteile: 1-3s Latenz (nicht natuerlich), TTS-Qualitaet geringer, komplexe Audio-Pipeline.

V1-Empfehlung: Option A. Option B als Forschungsprojekt fuer spaeter.

### 4.3 Secretary-Funktionen

#### Anrufbearbeitung

| Anliegen | Agent-Aktion |
|---|---|
| Terminwunsch | Kalender pruefen (gcal_find_my_free_time), Slot vorschlagen, bei Bestaetigung buchen (gcal_create_event) |
| Rueckrufwunsch | Task erstellen (bridge_task_create), User benachrichtigen |
| Allgemeine Frage | Antwort aus Knowledge Engine, bei Unsicherheit: "Ich leite weiter" |
| Beschwerde | Eskalation: Weiterleitung an Mobilnummer oder sofortige Benachrichtigung |
| Spam/Werbung | Hoeflich beenden, nicht weiterleiten, im Log markieren |

#### Email-Triage

1. Cron-Job prueft Posteingang alle 15 Minuten (gmail_search_messages)
2. Agent klassifiziert jede neue Email: `urgent` / `action_required` / `informational` / `spam`
3. `urgent`: sofortige Benachrichtigung via Telegram/WhatsApp
4. `action_required`: Task erstellen, in taeglicher Zusammenfassung auflisten
5. `informational`: archivieren, in woechentlicher Zusammenfassung
6. `spam`: markieren, nicht weiterleiten
7. Standard-Antworten: Agent beantwortet haeufige Anfragen (Oeffnungszeiten, Preisliste, Terminbuchungs-Link)

#### Kalender-Management

- Morgen-Briefing: taegliche Zusammenfassung der Termine (per Telegram/Email)
- Erinnerungen: 30 Minuten vor jedem Termin
- Konflikterkennung: wenn zwei Termine ueberlappen → sofortige Warnung
- Slot-Verwaltung: definierbare Verfuegbarkeitsfenster, die der Voice-Agent fuer Buchungen nutzt

#### Aufgaben-Delegation

- Voice-Agent oder Email-Agent kann Tasks erstellen
- Tasks werden an den User oder an andere Bridge-Agents delegiert
- Taegliche Zusammenfassung offener Tasks

### 4.4 Kontakt-Datenbank

```json
{
  "contact_id": "ct_abc123",
  "name": "Max Mustermann",
  "company": "Musterfirma GmbH",
  "phone": "+4915112345678",
  "email": "max@musterfirma.de",
  "category": "customer",
  "notes": "Bestandskunde seit 2024. Bevorzugt Rueckruf vormittags.",
  "last_contact": "2026-03-10",
  "call_count": 5
}
```

- Lookup bei eingehendem Anruf: Telefonnummer → Kontakt
- Agent passt Begruessung an: "Guten Tag Herr Mustermann" statt generisches "Guten Tag"
- Persistenz in Knowledge Engine unter `Shared/Contacts/` (als Markdown-Notes mit YAML-Frontmatter, da Knowledge Engine `.md`-Suffix erzwingt)

### 4.5 Geschaeftszeiten und Regeln

```json
{
  "business_hours": {
    "monday-friday": {"start": "09:00", "end": "18:00"},
    "saturday": {"start": "10:00", "end": "14:00"},
    "sunday": null
  },
  "greeting": "Guten Tag, hier ist [Firmenname]. Wie kann ich Ihnen helfen?",
  "after_hours_message": "Unser Buero ist aktuell nicht besetzt. Moechten Sie eine Nachricht hinterlassen?",
  "escalation_number": "+4915198765432",
  "escalation_keywords": ["dringend", "notfall", "sofort", "urgent"],
  "max_call_duration_s": 600,
  "language": "de"
}
```

Persistenz in Knowledge Engine unter `Shared/Config/secretary.md` (als Markdown mit YAML-Frontmatter, da Knowledge Engine `.md`-Suffix erzwingt).

### 4.6 Agent-Modi

#### Default: Single-Agent-Modus

Ein Agent uebernimmt alle Secretary-Funktionen: Anrufbearbeitung, Email-Triage, Kalender.

#### Kostenmodell

| Funktion | Geschaetzte Kosten | Basis |
|---|---|---|
| Eingehender Anruf (3 Min) | $0.20 - $0.50 | Voice-Provider ($0.07-0.15/Min) + Claude API |
| Email-Triage (1 Email) | $0.01 - $0.03 | Claude Sonnet |
| Email-Triage (20 Emails, 1 Batch) | $0.05 - $0.10 | Header-Only-Pre-Filter + Claude fuer neue Emails |
| Email-Triage pro Tag (96 Checks) | $5 - $10 | Bei 15-Min-Intervall. Reduktion durch Header-Only-Filter moeglich. |
| Morgen-Briefing | $0.05 - $0.10 | Calendar + Task Check + Report |
| Termin-Buchung | $0.10 - $0.20 | Calendar API + Bestaetigungs-Email |

#### Fehlerbehandlung

| Parameter | Default |
|---|---|
| `max_call_duration_s` | 600 (10 Min) |
| `voice_provider_timeout_s` | 30 |
| `action_timeout_s` | 15 (Kalender-Lookup, Task-Erstellung) |
| `email_triage_batch_size` | 20 |

| Fehler | Verhalten |
|---|---|
| Voice-Provider nicht erreichbar | Anruf wird an Voicemail/Anrufbeantworter geleitet |
| Kalender-API Timeout | Agent sagt: "Ich kann gerade nicht auf den Kalender zugreifen. Darf ich Sie zurueckrufen?" |
| Claude API Timeout | Fallback auf vorbereitete Standardantworten aus Knowledge Engine |
| Unbekannter Anrufer | Standardbegruessung, keine personalisierten Informationen preisgeben |

---

## 5. Nicht verhandelbare Anforderungen

### Datenschutz (DSGVO / BDSG / TTDSG)

#### Aufzeichnung und Einwilligung

1. Anrufaufzeichnungen nur mit expliziter Einwilligung des Anrufers (Art. 6(1)(a) DSGVO). Agent MUSS vor jeder Aufzeichnung informieren UND Einwilligung einholen.
2. Bei Widerspruch: Gespraech wird OHNE Aufzeichnung weitergefuehrt. Kein Transkript, keine Zusammenfassung. Nur Anruf-Metadaten (Zeitstempel, Dauer, Kontakt) werden gespeichert.

#### Auftragsverarbeitung (AVV)

3. Voice-Provider (Retell AI, Vapi) verarbeitet Audio-Daten im Auftrag. Ein AVV-Vertrag nach Art. 28 DSGVO ist PFLICHT vor Produktivbetrieb.
4. Cloud-TTS/STT (OpenAI, ElevenLabs) erfordert ebenfalls AVV.

#### Drittlandtransfer

5. Retell AI und Vapi sind US-Unternehmen. Audio-Daten werden in die USA uebertragen. EU-US Data Privacy Framework (DPF) muss geprueft werden. Wenn Provider nicht DPF-zertifiziert: Standardvertragsklauseln (SCCs) erforderlich.

#### Loeschfristen

6. Transkripte: 90 Tage, dann automatische Loeschung (konfigurierbar).
7. Anruf-Logs (Metadaten): 12 Monate.
8. Kontaktdaten: auf Anfrage des Betroffenen loeschbar (Art. 17 DSGVO).

#### Informationspflichten

9. Bei erstem Kontakt: Verweis auf Datenschutzerklaerung (Art. 13/14 DSGVO). Agent nennt URL oder bietet Zusendung an.
10. Kontaktdaten bleiben lokal in der Knowledge Engine.

#### Vor Produktivbetrieb erforderlich

- AVV mit Voice-Provider abschliessen
- Datenschutzerklaerung erstellen (Verarbeitung von Anrufdaten)
- Verarbeitungsverzeichnis nach Art. 30 DSGVO fuehren
- Empfehlung: Datenschutz-Folgenabschaetzung (DSFA) nach Art. 35 DSGVO, da systematische Ueberwachung von Kommunikation

### Qualitaet

5. Jeder Anruf wird transkribiert und zusammengefasst, sofern Einwilligung vorliegt. Bei Verweigerung: nur Metadaten (Zeitpunkt, Dauer, Kontakt-ID, Anliegen-Kategorie vom Agent notiert).
6. Jede Aktion (Terminbuchung, Task-Erstellung, Weiterleitung) wird im Anruf-Log dokumentiert.
7. Bei Unsicherheit: Agent leitet weiter statt falsche Informationen zu geben.
8. Eskalationsregeln sind konfigurierbar und werden strikt befolgt.

### Technisch

9. Voice-Provider-Anbindung via Webhook (Bridge empfaengt Events, sendet Aktionen).
10. Voice-Provider ist austauschbar innerhalb der Webhook-basierten Provider-Klasse (Retell AI, Vapi). SIP-native Provider erfordern Architekturanpassung.
11. Anruf-Log mit Transkript, Zusammenfassung, Aktionen und Ergebnis.
12. Email-Triage ist konfigurierbar (welche Labels, welche Absender, welche Regeln).

---

## 6. API-Spec

### 6.1 Voice/Anrufe

- `POST /secretary/calls/webhook` — Webhook-Endpoint fuer Voice-Provider (eingehender Anruf, Aktion angefordert, Anruf beendet)
- `GET /secretary/calls` — Anruf-Log (gefiltert nach Datum, Kontakt, Status)
- `GET /secretary/calls/{id}` — Anruf-Details mit Transkript und Aktionen

Authentifizierung: Alle `/secretary/*`-Endpoints ausser `/secretary/calls/webhook` sind NUR ueber `127.0.0.1:9111` erreichbar. Der Tunnel exponiert ausschliesslich den Webhook-Pfad. Webhook wird via HMAC + Timestamp verifiziert.
- `POST /secretary/calls/outbound` — Ausgehenden Anruf starten (Rueckruf)

### 6.2 Kontakte

- `POST /secretary/contacts` — Kontakt erstellen
- `GET /secretary/contacts` — alle Kontakte
- `GET /secretary/contacts/{id}` — Kontakt-Details
- `PUT /secretary/contacts/{id}` — Kontakt aktualisieren
- `GET /secretary/contacts/lookup?phone={number}` — Kontakt per Telefonnummer suchen

### 6.3 Email-Triage

- `POST /secretary/email/triage` — Triage manuell ausloesen
- `GET /secretary/email/summary` — Zusammenfassung (urgent/action_required/informational/spam)
- `GET /secretary/email/rules` — aktive Triage-Regeln
- `PUT /secretary/email/rules` — Triage-Regeln anpassen

### 6.4 Konfiguration

- `GET /secretary/config` — aktuelle Secretary-Konfiguration
- `PUT /secretary/config` — Geschaeftszeiten, Begruessung, Eskalationsregeln anpassen

### 6.5 MCP-Tools (fuer Agents)

- `bridge_secretary_call_log` — Anruf-Log abrufen
- `bridge_secretary_contact_lookup` — Kontakt per Telefonnummer suchen
- `bridge_secretary_email_triage` — Email-Triage manuell starten
- `bridge_secretary_schedule_callback` — Rueckruf planen

---

## 7. Umsetzungs-Slices

### Phase A — Infrastruktur

#### Slice A0 — Webhook-Infrastruktur + oeffentliche URL

- Oeffentliche URL fuer Webhook-Empfang einrichten (ngrok fuer Dev, Cloudflare Tunnel oder VPS-Proxy fuer Produktion)
- Webhook-Endpoint in server.py: `POST /secretary/calls/webhook` mit HMAC-Signaturpruefung
- Webhook-Event-Modell (eingehender Anruf, Aktion angefordert, Anruf beendet)
- Idempotenz-Schutz (doppelte Events ignorieren)
- Timestamp-Validierung: Webhook-Events aelter als 300 Sekunden werden abgelehnt (Replay-Schutz)
- Health-Check fuer Webhook-Erreichbarkeit

#### Slice A1 — Voice-Provider-Anbindung (Proof of Concept zuerst)

- VORBEDINGUNG: Mindestens einen Provider (Retell AI oder Vapi) real installieren, MCP-Config testen, einen End-to-End-Anruf durchspielen. Ohne diesen PoC ist die gesamte Architektur eine Hypothese.
- Voice-Provider-Account einrichten (Retell AI oder Vapi)
- Telefonnummer konfigurieren (Twilio/Vonage)
- Anruf-Lifecycle: eingehend → aktiv → beendet
- Transkript-Empfang und lokale Speicherung
- Anruf-Log-Modell
- Inbound-Handling implementieren (die bestehenden bridge_phone_* Tools sind nur Outbound)

#### Slice A2 — Kontakt-Datenbank + Geschaeftsregeln

- Kontakt-CRUD in Knowledge Engine
- Telefonnummer-Lookup
- Geschaeftszeiten-/Begrüssungs-Konfiguration
- Secretary-Config-Modell

### Phase B — Secretary-Logik

#### Slice B1 — Anrufbearbeitung

- Anliegen-Erkennung (Termin, Rueckruf, Frage, Beschwerde, Spam)
- Kalender-Integration (gcal_find_my_free_time → gcal_create_event)
- Task-Erstellung bei Rueckrufwunsch
- Weiterleitung bei Eskalation
- Post-Call-Zusammenfassung und Benachrichtigung

#### Slice B2 — Email-Triage

- Cron-basierter Posteingangs-Check
- Klassifikation (urgent/action_required/informational/spam)
- Standard-Antworten fuer haeufige Anfragen
- Taegliche/woechentliche Zusammenfassung
- Task-Erstellung fuer action_required Emails

### Phase C — Proaktive Features

#### Slice C1 — Kalender-Management

- Morgen-Briefing
- Termin-Erinnerungen
- Konflikterkennung
- Verfuegbarkeitsfenster-Verwaltung

#### Slice C2 — Outbound + Follow-Up

- Automatische Rueckrufe (geplant via Task)
- Follow-Up-Emails nach Terminen
- Recurring-Checks fuer offene Tasks

### Phase D — Haertung

#### Slice D1 — Multi-Provider-Support

- Abstraktion ueber Voice-Provider (Retell ↔ Vapi ↔ Vonage)
- Failover bei Provider-Ausfall
- Kosten-Tracking pro Anruf

Bridge-native Voice (lokale STT + TTS + SIP) ist ein eigenstaendiges Forschungsprojekt mit voellig anderem Technologie-Stack. Ausgelagert aus dieser Spec — eigene Forschungs-Spec bei Bedarf.

### Priorisierung

Phase A: Ohne Telefonie-Anbindung und Kontakte keine Secretary.
Phase B: Der Kern — Anrufe bearbeiten und Emails triagieren.
Phase C: Der Mehrwert — proaktive Kalender- und Aufgabenverwaltung.
Phase D: Unabhaengigkeit und Haertung.

### Abhaengigkeiten

- Voice-Provider-Account (Retell AI, Vapi oder Vonage) — externer Service, muss vom User eingerichtet werden
- Google Calendar MCP — bereits verfuegbar
- Gmail MCP — bereits verfuegbar
- Gemeinsames Job-Framework (aus Big Data/Finance/Accounting Specs) fuer Pipeline-Management
- Telefonnummer — muss vom User bei Twilio/Vonage gekauft werden

---

## 8. Synergien

| Komponente | Geteilt mit anderen Specs |
|---|---|
| Knowledge Engine | Ja — Kontakte unter `Contacts/`, Regeln unter `Config/` |
| Task-System | Ja — Rueckruf-Tasks, Email-Tasks |
| Job-Framework | Ja — Email-Triage als Job-Typ |
| Multi-Channel | Ja — Benachrichtigungen via Telegram/Email/WhatsApp |
| Calendar MCP | Ja — bereits fuer alle Agents verfuegbar |
| Gmail MCP | Ja — bereits fuer alle Agents verfuegbar |
| Voice-Transkription | Geteilt mit Creator Spec (faster-whisper) |

---

## 9. Abgrenzung

### Was die Plattform NICHT ist

- Kein Call-Center (keine Warteschlange fuer 100 parallele Anrufe)
- Kein CRM (keine Verkaufspipeline, kein Lead-Scoring)
- Kein VOIP-Provider (kein eigener Telefondienst, nutzt externe Provider)
- Keine menschliche Sekretaerin (KI-Grenzen: komplexe Verhandlungen, emotionale Situationen)

### Was sie IST

- Ein lokaler, Agent-gesteuerter Secretary-Service fuer kleine Unternehmen
- Fuer Anrufbearbeitung, Email-Triage, Kalender-Management und Aufgaben-Delegation
- Der die vorhandenen Bridge-Kanaele (Telefon, Email, Telegram, WhatsApp) unter einer einheitlichen Secretary-Intelligenz zusammenfuehrt

---

## 10. Test-Spec

### Acceptance Criteria

1. Eingehender Anruf wird innerhalb von 5s angenommen und Begruessung gesprochen
2. Terminwunsch fuehrt zu Kalender-Lookup und Buchung in <15s
3. Rueckrufwunsch erzeugt Task und Benachrichtigung in <10s
4. Eskalations-Keywords fuehren zu sofortiger Weiterleitung
5. Anruf-Zusammenfassung wird innerhalb von 60s nach Gespraechsende zugestellt
6. Email-Triage klassifiziert 20 Emails in <30s mit <5% False-Positive-Rate bei `urgent`
7. DSGVO-Hinweis zur Aufzeichnung erfolgt in jedem Gespraech
8. Terminbuchung scheitert graceful wenn kein freier Slot vorhanden ("Leider ist kein Termin frei. Darf ich Sie zurueckrufen?")
9. Agent gibt keine Geschaeftsinformationen an unbekannte Anrufer preis (kein Umsatz, keine Mitarbeiterzahl, keine internen Details)

---

## 11. Marktrecherche-Quellen

Recherche durchgefuehrt am 2026-03-14.

- Voice-Agent-Plattformen: Retell AI (~$0.07-0.15/Min, 600ms Latenz, 99.99% Uptime), Vapi (500-800ms Latenz), Bland AI, Synthflow — retellai.com, vapi.ai, bland.ai
- MCP-Integration: Retell AI MCP Server, Vapi MCP Server, Vonage Telephony MCP — retellai.com, mcpmarket.com, developer.vonage.com
- VoiceMode: Open-Source Voice-Konversation mit Claude Code — github.com/mbailey/voicemode
- AI Secretary Markt: AI-Scheduling spart 4-5h/Woche. 40% Enterprise-Apps mit AI-Agents bis Ende 2026. — lindy.ai, zeeg.me
- Latenz: End-to-End <300ms in 2026 erreichbar (GPT-4o Realtime, Gemini 2.0 Flash) — flowful.ai
- Kalender-Integration: Lindy, Reclaim, SchedulerAI — als UX-Referenz
