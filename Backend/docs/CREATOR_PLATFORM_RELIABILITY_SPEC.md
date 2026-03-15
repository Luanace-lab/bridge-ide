# CREATOR PLATFORM SPEC

Stand: 2026-03-14
Revision: 2026-03-14 — Upgrade: Produktdifferenzierung, Agent-Integration, Multi-Channel-Publishing, STT-Modernisierung

## 1. Ziel

Die Creator-Plattform der BRIDGE ist ein lokales, privates Creator-Werkzeug. Sie ersetzt Cloud-Abos (OpusClip, Descript, Vizard) durch eine selbst gehostete, Agent-gestuetzte Pipeline.

### 1.1 Produkt-Differenzierung

Warum ein Creator die BRIDGE nutzen soll statt OpusClip ($15/Monat):

1. **Lokal + privat** — kein Upload zu Drittanbietern, volle Kontrolle ueber Inhalte
2. **Agent-gestuetzte Analyse** — ein Bridge-Agent analysiert das Transkript, schlaegt Clips vor, schreibt Captions, optimiert pro Plattform — nicht nur Wortanzahl, sondern semantisches Verstaendnis
3. **End-to-End ueber Bridge-Kanaele** — Clip-Erstellung bis Publishing ueber vorhandene MCP-Tools (WhatsApp, Telegram, Slack, Email, Todoist) in einem Workflow
4. **Kein Abo** — einmalig lokal, keine wiederkehrenden Kosten
5. **Multi-Agent-Workflows** — Creator kann spezialisierte Agents fuer Recherche, Captioning, Thumbnail-Ideen, Posting-Zeitplanung einsetzen

### 1.2 Funktionale Ziele

Die Plattform muss als belastbare Produktionsstrecke funktionieren:

- lokale Videos und Audios ingestieren
- URLs und YouTube-Quellen ingestieren
- Metadaten pruefen
- Audio extrahieren
- Transkribieren (chunked, lokal, duration-unbounded)
- Inhalte semantisch analysieren (via Agent)
- Clips intelligent vorschlagen (via Agent oder Heuristik)
- Clips exportieren
- Social-Varianten rendern
- Untertitel und Metadaten-Pakete erzeugen
- Clips ueber Kanaele veroeffentlichen oder zur Veroeffentlichung planen

### 1.3 Operative Anforderungen

- fuer jede unterstuetzte Quelle
- fuer praktisch beliebige Dauer
- ohne request-gebundene Zeitlimits
- mit Resume, Retry und klarer Sichtbarkeit
- fail-closed statt stiller Scheinerfolge

Wichtig:
Der Satz "fuer jedes Video, fuer jede Laenge" ist nur dann technisch ehrlich, wenn die Plattform duration-unbounded arbeitet und ihre reale Grenze explizit nur noch durch verfuegbaren Speicher, Rechenzeit und Provider-Zugaenglichkeit bestimmt ist, nicht durch fest codierte Kurzzeit-Limits.

### 1.4 Produktdefinition neu

Die Creator-Plattform der BRIDGE ist nicht nur eine lokale Clip-Pipeline.
Sie ist ein lokales, privates Creator Operations System.

Sie verbindet:
- Produktion
- Analyse
- Publishing
- Kampagnensteuerung
- Agent-gestuetzte Entscheidung
- Human-in-the-loop-Kontrolle

Ziel ist nicht nur, Clips zu exportieren.
Ziel ist, den gesamten Arbeitszyklus eines Creators lokal, agent-gestuetzt und kontrollierbar abzubilden.

### 1.5 Jobs-to-be-Done

Die Plattform muss folgende realen Jobs des Creators bedienen:

1. Rohmaterial schnell in verwertbare Assets verwandeln
2. aus einem langen Inhalt mehrere plattformspezifische Varianten erzeugen
3. Inhalte nicht nur schneiden, sondern semantisch verstehen
4. Publishing und Zeitplanung ohne Tool-Wechsel ausfuehren
5. Kampagnen ueber mehrere Tage und Kanaele koordinieren
6. Performance zurueck in die Produktionslogik einspeisen
7. kreative und operative Ueberlastung senken
8. volle lokale Kontrolle ueber Inhalte, Artefakte und Arbeitslogik behalten

## 2. Verifizierter Ist-Zustand

### 2.1 Vorhandene Creator-Funktionen

Die Plattform besitzt heute bereits diese reale Pipeline:

- `ingest_local_media()`
- `ingest_url_media()`
- `probe_media()`
- `extract_audio_for_transcription()`
- `write_srt()`
- `pick_highlight_candidates()`
- `export_clip()`
- `export_social_clip()`
- `create_social_package()`

Quellen:

- `Backend/creator_media.py`
- `Backend/server.py`
- `Backend/bridge_mcp.py`
- `Backend/docs/BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md`

### 2.2 Verifizierter Live-Befund

Mit einem realen YouTube-Video wurde verifiziert:

- URL-Ingest funktionierte
- yt-dlp Download funktionierte
- Media-Probe funktionierte
- Audio-Extraktion funktionierte
- die eingebaute Transkriptionsstrecke scheiterte reproduzierbar

Fehler:

- `Whisper timed out after 30.0s`

### 2.3 Verifizierte harte Grenzen im aktuellen Code

#### STT

`Backend/voice_stt.py`

- fester Gesamt-Timeout fuer Whisper: `30.0s`
- harte Dateigrenze: `MAX_AUDIO_SIZE_MB = 25`
- ffmpeg-Konvertierungs-Timeout: `15s`

#### Creator-Pipeline

`Backend/creator_media.py`

- ffprobe: `30s`
- Audio-Extraktion: `60s`
- yt-dlp Metadaten: `300s`
- yt-dlp Download: `900s`
- Clip-Export: `120s`
- Social-Clip-Export: `180s`

#### HTTP-Execution-Model

`Backend/server.py`

- `/creator/local-ingest` und `/creator/url-ingest` fuehren die gesamte Pipeline synchron innerhalb des Request-Handlers aus
- es gibt keinen Job-State, keine Checkpoints, kein Resume, keine Cancel-/Retry-Steuerung, keine Event-Historie

### 2.4 Verifizierte Testabdeckung

Die vorhandenen Tests decken Creator-Funktionen nur auf Mini-Fixtures ab:

- die Sample-Videos in `Backend/tests/test_creator_media.py` und `Backend/tests/test_creator_http_contract.py` sind jeweils `2s` lang
- die Contract-Tests fuer Ingest laufen mit `transcribe=False`
- es gibt keine verifizierte Teststrecke fuer:
  - lange Videos
  - echte YouTube-Transkription
  - Resume nach Prozessabbruch
  - Retry nach Zwischenfehler
  - parallele Creator-Jobs
  - Backpressure / Queueing

## 3. Diagnostizierte Hauptprobleme

### 3.1 Request-gebundene Langlaeufer

Die Creator-Strecke ist heute als synchroner Request-Fluss gebaut. Das ist fuer lange Medien der falsche Kontrollpfad.

Folgen:

- HTTP-Call bleibt offen, bis alles fertig ist
- grosse Langlaeufer werden zu Timeout-/Abbruchkandidaten
- kein sauberer Zwischenstatus
- kein Resume bei Neustart

### 3.2 Whole-file-STT statt chunked STT

Heute wird das gesamte extrahierte Audio als eine Einheit an Whisper uebergeben.

Folgen:

- harte Laufzeitspitzen
- harte Dateigrenzen
- schlechte Skalierung mit Videolaenge
- kompletter Job scheitert statt kontrollierter Teilfortschritt

### 3.3 Kein persistenter Job-State

Die Plattform erzeugt Artefakte, aber keinen belastbaren Job-Zustand mit Stage-Fortschritt.

Folgen:

- kein Resume
- kein Retry pro Stage
- kein sauberer Partial-Success
- keine auswertbare Diagnosehistorie

### 3.4 Kein harter Support-Vertrag

Es gibt heute keine definierte Produktgarantie fuer:

- unterstuetzte Formate
- Abbruchverhalten
- grosse Dateien
- sehr lange Medien
- Provider-/Netzfehler
- lokale Ressourcenknappheit

### 3.5 Keine intelligente Clip-Erkennung

`pick_highlight_candidates()` nutzt ausschliesslich `word_count + duration` als Score. Das ist eine Laengen-Heuristik, keine Inhaltsanalyse.

Marktstandard 2026 (OpusClip, Riverside, Vizard):

- Hook-Detection (starke Eroeffnungssaetze)
- Emotional-Peak-Analyse (Stimmungswechsel, Pointen)
- Pacing-Bewertung (Sprechgeschwindigkeit, Pausenrhythmus)
- Virality-Score pro Clip

Die BRIDGE hat einen fundamentalen Vorteil: sie kann einen LLM-Agent auf das Transkript ansetzen und semantisch analysieren. Das ist staerker als statistische Pattern-Matching-Modelle. Diese Faehigkeit wird heute nicht genutzt.

### 3.6 Kein Publishing-Workflow

Die Pipeline endet beim gerenderten Clip. Es gibt keinen Pfad von Clip zu Veroeffentlichung.

Die BRIDGE hat bereits MCP-Tools fuer:

- `bridge_whatsapp_send` / `bridge_telegram_send` / `bridge_slack_send`
- `bridge_email_send`
- `bridge_todoist_create`
- `bridge_cron_create`

Diese Kanaele sind vorhanden, aber nicht in die Creator-Pipeline integriert. Ein Creator muss heute manuell Clips exportieren und dann einzeln verteilen.

### 3.7 Standard-Whisper statt faster-whisper

`voice_stt.py` ruft Whisper als subprocess auf. Der De-facto-Standard fuer lokale Transkription 2025/2026 ist `faster-whisper` (CTranslate2-basiert):

- 4-8x schneller als Standard-Whisper
- geringerer Speicherbedarf
- identische Modelle (large-v3, large-v3-turbo)
- word-level timing
- VAD-Filterung (Voice Activity Detection) reduziert unnoetige Verarbeitung

Ohne faster-whisper bleibt die Transkription der Flaschenhals.

### 3.8 Markt-Pain und Produktkonsequenz

Creator leiden heute nicht nur an Editing-Aufwand, sondern an:
- kreativer Ermuedung
- zu vielen Tool-Wechseln
- plattformspezifischem Anpassungsdruck
- fehlender Messbarkeit
- instabiler Plattform-Reichweite
- fehlender Kontrolle ueber KI-Nutzung und Attribution
- Druck, Trends schneller zu erkennen und umzusetzen

Produktkonsequenz:
Die BRIDGE darf nicht nur ein lokaler Cutter sein.
Sie muss Creator-Arbeit als kontrollierbaren Operations-Loop abbilden:
Produktion -> Distribution -> Performance -> naechste Aktion.

## 4. Nicht verhandelbare Zielanforderungen

Die Creator-Plattform gilt erst dann als produktiv belastbar, wenn diese Regeln erfuellt sind:

### Infrastruktur

1. Kein einzelner gesamter Creator-Job darf von einem festen Kurzzeit-Timeout abhaengen.
2. Transkription muss chunked, resumierbar und auf faster-whisper basiert sein.
3. Jeder Job braucht einen persistenten Zustand auf Disk.
4. Jede Stage braucht explizite Statuswerte: `queued`, `running`, `completed`, `failed`, `partial`, `cancelled`.
5. Ein Reconnect oder Server-Neustart darf bereits fertiggestellte Stages nicht verlieren.
6. Fehler muessen stage-spezifisch sichtbar sein.
7. Untertitel aus der Quelle duerfen ein Fallback sein, aber nicht der einzige Weg fuer lange Medien.
8. Der Nutzer braucht Job-Status statt blockierendem Warten.
9. Die Plattform muss parallele Jobs begrenzen und sauber backpressuren.
10. Testabdeckung muss reale kurze, mittlere und lange Medien explizit pruefen.

### Produkt

11. Clip-Vorschlaege muessen inhaltlich begruendet sein, nicht nur laengenbasiert.
12. Die Pipeline muss von Ingest bis Publishing durchgaengig funktionieren.
13. Batch-Verarbeitung mehrerer Quellen muss moeglich sein.
14. Scheduling fuer zeitgesteuerte Veroeffentlichung muss moeglich sein.
15. Die Plattform muss ohne Cloud-Abhaengigkeit und ohne Abo funktionieren.

## 5. Zielarchitektur

### 5.1 Grundsatz

Aus der heutigen Request-Pipeline wird eine persistente Job-Pipeline.

Neu:

- HTTP/MCP startet nur Jobs
- Worker fuehren Stages aus
- Job-State liegt persistent im Workspace
- jede Stage checkpointet ihren Fortschritt

### 5.2 Job-Modell

Neues kanonisches Objekt: `creator_job`

Empfohlene Felder:

- `job_id`
- `job_type`
  - `local_ingest`
  - `url_ingest`
  - `transcribe`
  - `clip_export`
  - `social_export`
  - `package_social`
- `source`
- `workspace_dir`
- `created_at`
- `updated_at`
- `status`
- `stage`
- `progress_pct`
- `error`
- `warnings`
- `artifacts`
- `metrics`
- `resume_from_stage`
- `attempt_count`
- `events`

Persistenz:

- `workspace_dir/creator_jobs/<job_id>/job.json`
- `workspace_dir/creator_jobs/<job_id>/events.jsonl`
- `workspace_dir/creator_jobs/<job_id>/artifacts/`
- `workspace_dir/creator_jobs/<job_id>/chunks/`

### 5.3 Stage-Modell

Jeder Creator-Job laeuft in klaren Stages:

1. `source_resolve`
2. `download`
3. `probe`
4. `audio_extract`
5. `transcript_plan`
6. `transcript_chunks`
7. `transcript_merge`
8. `chapters`
9. `highlights`
10. `clip_export`
11. `social_export`
12. `package_finalize`

### 5.4 Transkriptionsarchitektur

Die Transkription muss von whole-file auf chunked processing umgestellt werden.

#### STT-Engine: faster-whisper

Die STT-Engine muss von Standard-Whisper (subprocess) auf faster-whisper (CTranslate2) umgestellt werden.

Gruende:

- 4-8x schneller bei gleicher Genauigkeit
- geringerer Speicherbedarf (INT8-Quantisierung moeglich)
- word-level timing nativ
- VAD-Filterung (Silhouette-basiert) reduziert unnoetige Verarbeitung
- identische Modellgewichte (large-v3, large-v3-turbo)
- pip-installierbar, keine externe Binary noetig

Empfohlene Integration:

- `faster-whisper` als Python-Library einbinden (kein subprocess)
- Modell einmalig laden, ueber Chunks wiederverwenden
- VAD aktivieren fuer automatische Stille-Filterung

#### Chunked Strategie

- Audio zuerst auf Arbeitsformat normalisieren
- Audio in feste Chunks schneiden
- Chunk-Groesse nicht nur nach Dauer, sondern auch nach Dateigroesse planen
- Ueberlappung pro Chunk vorsehen, um Segmentkanten nicht abzuschneiden
- jeden Chunk einzeln transkribieren
- Ergebnisse mergen und normalisieren

Empfohlene Default-Parameter:

- `chunk_duration_s`: `300`
- `chunk_overlap_s`: `1.0`
- `max_chunk_audio_mb`: `12`
- `max_parallel_transcribe_workers`: `1` initial, spaeter konfigurierbar

#### Warum das notwendig ist

Das entfernt die aktuelle Hauptschwaeche:

- keine Abhaengigkeit von einem einzigen 30s-Whisper-Lauf
- Resume auf Chunk-Ebene
- Retry nur fuer fehlerhafte Chunks
- keine totale Neuberechnung nach Abbruch

### 5.5 Agent-gestuetzte Inhaltsanalyse

Die BRIDGE hat gegenueber reinen Video-Tools einen fundamentalen Vorteil: sie kann LLM-Agents auf Transkripte ansetzen.

#### Clip-Vorschlaege via Agent

Nach der Transkription wird ein Agent-Task erstellt:

Eingabe:

- vollstaendiges Transkript mit Timestamps
- Mediendauer und Metadaten
- Zielplattformen (YouTube Short, Instagram Reel, TikTok etc.)

Auftrag an Agent:

- identifiziere die N besten Clip-Kandidaten
- begruende jede Auswahl (Hook-Qualitaet, Ueberraschungsmoment, Standalone-Verstaendlichkeit, emotionaler Peak)
- schlage pro Clip einen Caption-Text und Hashtags vor
- bewerte jeden Clip nach geschaetztem Engagement-Potenzial

Ausgabe als strukturiertes JSON:

```json
{
  "clips": [
    {
      "start_s": 142.5,
      "end_s": 198.3,
      "title": "...",
      "reason": "Starker Hook + ueberraschendes Ergebnis",
      "caption": "...",
      "hashtags": ["..."],
      "engagement_score": 0.87,
      "platforms": ["youtube_short", "instagram_reel"]
    }
  ]
}
```

Implementierung:

- neuer Job-Type: `analyze_content`
- Stage zwischen `transcript_merge` und `clip_export`
- Agent wird via `bridge_task_create` beauftragt
- Ergebnis fliegt in `job.json` unter `analysis`
- Fallback: wenn kein Agent verfuegbar, Heuristik wie heute (Wortanzahl + Dauer)

#### Warum das der zentrale Differenziator ist

OpusClip nutzt statistische Pattern-Matching-Modelle fuer Virality-Scoring. Die BRIDGE kann ein vollwertiges LLM auf den Inhalt ansetzen. Das LLM versteht Kontext, Ironie, Argumentationsstruktur, narrative Boegen und kulturelle Referenzen — Dinge, die kein Embedding-Modell leisten kann.

### 5.6 Subtitle-Strategie

Untertitelquellen muessen priorisiert, aber sauber getrennt werden:

1. `native_transcript`
   - BRIDGE-STT auf Chunk-Basis
2. `source_subtitles`
   - YouTube auto captions / source captions
3. `manual_override`
   - vom Nutzer hochgeladenes oder korrigiertes SRT/VTT

Regel:

- `native_transcript` bleibt primaerer Pfad
- `source_subtitles` ist Fallback oder Beschleuniger
- die Herkunft der Segmente muss im Artefakt markiert werden

### 5.6 Render-/Export-Stages

Exports bleiben funktional nah am heutigen System, aber werden ebenfalls job-basiert:

- `export_clip`
- `export_social_clip`
- `create_social_package`

Neu erforderlich:

- Stage-State pro Asset
- Retry pro Asset
- Resume ohne bereits fertige Assets neu zu rendern

### 5.8 Multi-Channel-Publishing

Die Creator-Pipeline endet heute beim gerenderten Clip. Fuer echten Creator-Mehrwert muss sie bis zur Veroeffentlichung reichen.

#### Vorhandene Bridge-Kanaele (bereits implementiert)

- `bridge_whatsapp_send` — WhatsApp (Text + Media)
- `bridge_telegram_send` — Telegram (Text + Media)
- `bridge_slack_send` — Slack (Text + Media)
- `bridge_email_send` — Email (mit Attachment)
- `bridge_todoist_create` — Task-Erstellung (fuer Redaktionsplanung)
- `bridge_cron_create` — Zeitgesteuerte Ausfuehrung

#### Neuer Job-Type: `publish`

Ein Publish-Job nimmt fertige Clips und verteilt sie:

Eingabe:

- `job_id` des Quell-Jobs (fuer Artefakt-Referenz)
- `clip_index` oder `artifact_path`
- `channels`: Liste von Zielkanaelen mit Konfiguration
- `schedule`: optional, ISO-Timestamp fuer zeitgesteuerte Veroeffentlichung
- `caption`, `hashtags`, `metadata` pro Kanal (oder Default)

Beispiel:

```json
{
  "job_type": "publish",
  "source_job_id": "cj_abc123",
  "clip_index": 0,
  "channels": [
    {"type": "telegram", "target": "@my_channel", "caption": "..."},
    {"type": "whatsapp", "target": "+49...", "caption": "..."},
    {"type": "email", "target": "newsletter@...", "subject": "Neuer Clip"}
  ],
  "schedule": "2026-03-15T09:00:00Z"
}
```

Umsetzung:

- Scheduling ueber `bridge_cron_create`
- Ausfuehrung ueber bestehende MCP-Send-Tools
- Status-Tracking pro Kanal (sent/failed/scheduled)
- Kein eigener Social-Media-API-Client — die Bridge nutzt vorhandene Kanaele

#### Batch-Publishing

Creator haben oft Serien: 5 Clips aus einem Video, verteilt ueber 5 Tage.

- `POST /creator/jobs/publish-batch`
- nimmt eine Liste von Clip-Kanal-Paaren mit Zeitplan
- erzeugt intern pro Clip einen Publish-Job
- Gesamtstatus ueber `/creator/jobs/{batch_id}`

### 5.9 Batch-Ingest

Creator verarbeiten oft mehrere Videos am Stueck. Ein Batch-Ingest startet mehrere Jobs:

- `POST /creator/jobs/batch-ingest`
- Eingabe: Liste von Quellen (URLs oder lokale Pfade)
- pro Quelle wird ein separater Ingest-Job erstellt
- Backpressure greift automatisch
- Gesamtstatus ueber `/creator/jobs/batch/{batch_id}`

### 5.9b Social Platform Publishing (Direkte API-Integration)

Die Creator-Pipeline produziert Clips im exakten Format der Zielplattformen (1080x1920 fuer Shorts/Reels, 1080x1080 fuer Feed-Posts). Diese Clips muessen auch direkt auf den Zielplattformen veroeffentlicht werden koennen — nicht nur ueber Bridge-interne Kanaele.

#### Unterstuetzte Plattformen

| Plattform | API | Auth | Python-Library | Approval |
|---|---|---|---|---|
| YouTube | Data API v3 | OAuth 2.0, localhost nativ | `google-api-python-client` | Sofort (Testing-Mode) |
| TikTok | Content Posting API | OAuth 2.0 PKCE | `python-tiktok` | 5-10 Werktage |
| Instagram | Graph API v22.0 (Reels) | Facebook Login | `instagrapi` oder Graph direkt | 1-4 Wochen |
| Facebook | Graph API v22.0 (Video) | Page Access Token | `httpx`/`requests` direkt | 1-4 Wochen |
| X/Twitter | API v2 + Media Upload | OAuth 2.0 PKCE | `tweepy` | Sofort (Free: 1 Tweet/Tag) |
| LinkedIn | Community Mgmt API | OAuth 2.0 | `linkedin-api-client` | Wochen-Monate |

#### Credential-Management

Credentials werden lokal gespeichert:
```
~/.config/bridge/social_credentials/
├── youtube.json      # client_id, client_secret, access_token, refresh_token
├── tiktok.json       # access_token, refresh_token
├── instagram.json    # access_token, ig_user_id
├── facebook.json     # page_access_token, page_id
├── twitter.json      # api_key, api_secret, access_token, access_token_secret
└── linkedin.json     # access_token, person_urn
```

Permissions: `0600` (nur Owner). Keine Credentials im Code, keine Cloud-Speicherung.

#### Publish-Flow

Der Publisher (`creator_publisher.py`) routet automatisch:
- Bridge-Kanaele (telegram, whatsapp, slack, email) → HTTP an Bridge-Server
- Social-Plattformen (youtube, tiktok, instagram, facebook, twitter, linkedin) → Direkte API-Calls via `creator_social_publish.py`

Beide Typen koennen in einem Multi-Channel-Publish gemischt werden:
```json
{
  "channels": [
    {"type": "youtube", "caption": "New Video!", "tags": ["AI", "tech"]},
    {"type": "instagram", "caption": "Check this out!", "video_url": "https://..."},
    {"type": "telegram", "target": "@my_channel", "caption": "New clip!"}
  ]
}
```

#### Einschraenkungen (Stand 2026-03)

- Instagram Graph API erfordert eine oeffentliche Video-URL — lokaler Upload braucht einen Zwischenschritt (temporaerer Host oder `instagrapi` Private API).
- X/Twitter Free Tier: 1 Tweet/Tag, 2 Min Video-Limit. Ernsthaft nutzbar erst ab Basic Tier ($200/Mo).
- LinkedIn: Nur fuer Organisationen, nicht fuer Privatpersonen.
- TikTok: Unauditierte Apps posten nur privat (private visibility).

### 5.10 Marketing-/Campaign-Layer

Neues kanonisches Objekt: `creator_campaign`

Empfohlene Felder:
- `campaign_id`
- `title`
- `goal`
- `status`
- `owner`
- `target_platforms`
- `target_audience`
- `asset_refs`
- `publish_plan`
- `calendar`
- `performance_snapshots`
- `next_actions`
- `notes`
- `events`

Persistenz:
- `workspace_dir/creator_campaigns/<campaign_id>/campaign.json`
- `workspace_dir/creator_campaigns/<campaign_id>/events.jsonl`
- `workspace_dir/creator_campaigns/<campaign_id>/performance/`

Zweck:
Campaigns besitzen keine Rohproduktion.
Sie referenzieren Creator-Job-Artefakte und organisieren deren Planung, Veroeffentlichung, Auswertung und Folgeschritte.

### 5.11 Campaign-Stages

Empfohlene Stages:

1. `campaign_plan`
2. `asset_select`
3. `caption_variant_generate`
4. `publish_schedule`
5. `approval`
6. `publish_execute`
7. `performance_collect`
8. `performance_analyze`
9. `followup_actions`

### 5.12 Agent-gestuetzte Campaign-Intelligenz

Neue Agent-Rollen:
- Content Strategist
- Caption Agent
- Platform Optimizer
- Campaign Scheduler
- Performance Analyst

Aufgaben:
- Clusterung von Assets nach Kampagnenziel
- plattformspezifische Varianten
- Caption-/Hook-/CTA-Vorschlaege
- Versandzeit-Empfehlungen
- Serienplanung
- Performance-Auswertung
- Generierung konkreter Folgeaufgaben

### 5.13 Human-in-the-loop-Regel

Agenten duerfen Kampagnen vorbereiten, optimieren und vorschlagen.
Der Nutzer oder ein freigegebener Review-Agent behaelt die letzte Freigabe ueber:
- endgueltige Clip-Auswahl
- endgueltige Captions
- finale Publish-Ausfuehrung
- kritische Kanalziele

### 5.14 Marketing-/Campaign-Analyse

Performance darf nicht nur "sent/failed" bedeuten.

Mindestens noetig:
- publish status
- send timestamp
- channel
- asset used
- caption variant used
- response artifact
- optional manual metrics input
- optional imported metrics snapshot
- next recommended action

Wichtig:
MVP-Analyse darf mit internen Publish-Ereignissen und manuellen / importierten Performance-Snapshots starten.
Direkte Social-API-Integrationen sind nicht Voraussetzung fuer den ersten belastbaren Produktwert.

## 6. API-Spec

### 6.1 Neue Endpoints

Die heutigen synchronen Creator-Endpunkte muessen durch Job-Endpunkte ergaenzt oder ersetzt werden.

#### Job-Start

- `POST /creator/jobs/local-ingest`
- `POST /creator/jobs/url-ingest`
- `POST /creator/jobs/transcribe`
- `POST /creator/jobs/analyze` — Agent-gestuetzte Inhaltsanalyse
- `POST /creator/jobs/export-clip`
- `POST /creator/jobs/export-social`
- `POST /creator/jobs/package-social`
- `POST /creator/jobs/publish` — Clip ueber Kanal veroeffentlichen
- `POST /creator/jobs/publish-batch` — Mehrere Clips zeitgesteuert verteilen
- `POST /creator/jobs/batch-ingest` — Mehrere Quellen auf einmal ingestieren

Antwort:

- `202 Accepted`
- `job_id`
- `status: queued`
- `status_url`

#### Job-Status

- `GET /creator/jobs/{job_id}`
- `GET /creator/jobs/{job_id}/events`
- `GET /creator/jobs/{job_id}/artifacts`

#### Job-Steuerung

- `POST /creator/jobs/{job_id}/retry`
- `POST /creator/jobs/{job_id}/cancel`
- `POST /creator/jobs/{job_id}/resume`

### 6.2 Kompatibilitaet

Die alten Endpunkte koennen uebergangsweise bestehen bleiben, duerfen intern aber nur noch:

- Job anlegen
- optional auf Abschluss warten
- dann das finale Job-Ergebnis zurueckgeben

Nicht mehr:

- ganze Langlaeufer direkt im Request-Handler abarbeiten

### 6.3 Neue Endpunkte

- `POST /creator/campaigns`
- `GET /creator/campaigns/{campaign_id}`
- `GET /creator/campaigns/{campaign_id}/events`
- `POST /creator/campaigns/{campaign_id}/plan`
- `POST /creator/campaigns/{campaign_id}/schedule`
- `POST /creator/campaigns/{campaign_id}/approve`
- `POST /creator/campaigns/{campaign_id}/publish`
- `POST /creator/campaigns/{campaign_id}/analyze`
- `POST /creator/campaigns/{campaign_id}/metrics/import`

## 7. Runtime- und Ressourcenregeln

### 7.1 Kein globaler Kurzzeit-Timeout fuer den Gesamtjob

Stattdessen:

- Timeout pro Stage
- Timeout pro Chunk
- Heartbeat / Fortschrittsupdate je Stage

### 7.2 Backpressure

Noetig:

- globale Queue fuer Creator-Jobs
- konfigurierbare maximale Parallelitaet
- getrennte Limits fuer:
  - Download
  - Transkription
  - ffmpeg-Render

### 7.3 Workspace-Disziplin

Heute muessen Workspaces bereits existieren.
Fuer die Produktstrecke sollte gelten:

- `workspace_dir` wird kanonisch validiert
- fehlende Job-Unterverzeichnisse werden automatisch angelegt
- Artefakte liegen deterministisch
- temporaere Dateien werden nach Abschluss oder nach Cleanup-Regeln behandelt

### 7.4 Cleanup

Noetig:

- expliziter Cleanup-Status
- optionaler TTL-Cleanup fuer Temp-Artefakte
- niemals Artefakte loeschen, bevor Job nicht `completed` oder `failed` plus retention-abgelaufen ist

## 8. Observability-Spec

Jeder Creator-Job braucht:

- strukturierte Events
- Stage-Timestamps
- Dauer je Stage
- Exit-Code externer Tools
- Dateigroessen
- Chunk-Anzahl
- Anzahl fehlgeschlagener und wiederholter Chunks

Mindestens sichtbar:

- `download started/completed`
- `probe completed`
- `audio extraction completed`
- `transcript plan created`
- `chunk n/m running`
- `chunk n/m failed`
- `transcript merge completed`
- `export asset x completed`

## 9. Test-Spec

Die aktuelle Testlage reicht nicht.

### 9.1 Pflicht-Testmatrix

#### Quellen

- lokales MP4
- lokales MOV
- lokale Audiodatei
- direkte HTTP-URL
- YouTube-URL

#### Dauerklassen

- `short`: 30s
- `medium`: 10m
- `long`: 60m
- `very_long`: 240m synthetisch oder chunked Fixture

#### Modi

- ingest ohne Transkript
- ingest mit Transkript
- Resume nach Teilabbruch
- Retry einzelner Chunk-Fehler
- Social-Export mit und ohne Untertitel
- Packaging mit Metadaten-Sidecars

### 9.2 Failure Injection

Pflicht:

- yt-dlp Netzwerkfehler
- Whisper-Chunk-Fehler
- ffmpeg-Renderfehler
- Prozessabbruch mitten im Job
- Server-Neustart waehrend laufender Creator-Jobs

### 9.3 Acceptance Criteria

Die Creator-Plattform gilt erst dann als belastbar, wenn:

1. ein `10m`-YouTube-Video mit Transkript vollständig durchlaeuft
2. ein `60m`-Video als chunked Job mit Checkpoints vollständig durchlaeuft
3. ein Neustart den Job nicht unbrauchbar macht
4. ein einzelner Chunk-Fehler nicht den ganzen Job vernichtet
5. fertige Assets nach Retry/Resume nicht unnötig neu gebaut werden

## 10. Umsetzungs-Slices

### Phase A — Infrastruktur-Haertung

#### Slice A1 — Job-Pipeline

- Creator-Job-Modell mit persistenter Job-Datei
- neue Job-Endpunkte (POST → 202 Accepted)
- alte Endpunkte intern auf Job-Anlage umbiegen
- Job-Status- und Event-Abfrage

#### Slice A2 — faster-whisper + Chunked STT

- `voice_stt.py` auf faster-whisper umstellen
- Chunked Audio-Planung mit VAD
- Chunk-Transkriptionsworker
- Merge-Logik mit Overlap-Deduplizierung
- strukturierte Events pro Chunk

#### Slice A3 — Resume/Retry/Backpressure

- Resume/Retry/Cancel pro Job und Stage
- Backpressure / Queue mit konfigurierbarer Parallelitaet
- Job-Cleanup mit TTL

### Phase B — Intelligenz-Schicht

#### Slice B1 — Agent-gestuetzte Clip-Analyse

- neuer Job-Type `analyze_content`
- Agent-Task via `bridge_task_create`
- strukturierte Clip-Vorschlaege mit Begruendung
- Engagement-Score und plattformspezifische Empfehlungen
- Fallback auf Heuristik wenn kein Agent verfuegbar

#### Slice B2 — Intelligentes Captioning

- Agent generiert plattformspezifische Captions
- Hashtag-Vorschlaege basierend auf Inhalt und Plattform
- Optional: Thumbnail-Beschreibungsvorschlaege

### Phase C — Publishing-Strecke

#### Slice C1 — Multi-Channel-Publishing

- neuer Job-Type `publish`
- Integration mit vorhandenen MCP-Send-Tools
- Status-Tracking pro Kanal
- Scheduling ueber `bridge_cron_create`

#### Slice C2 — Batch-Workflows

- `publish-batch` fuer zeitgesteuerte Serien
- `batch-ingest` fuer Mehrfach-Quellen
- Batch-Statusabfrage

#### Slice C3 — Campaign Layer MVP

- `creator_campaign`-Objekt
- Campaign-Planung auf Basis fertiger Creator-Artefakte
- Batch-/Serien-Scheduling
- Approval-State
- Publish-Status pro Kanal

#### Slice C4 — Performance Feedback Loop

- manuelle / importierte Performance-Snapshots
- Agent-gestuetzte Kampagnenauswertung
- Generierung von Folgeaufgaben ueber Task-System
- Wiedereinspeisung in Content- und Publishing-Planung

### Phase D — Haertung und Validierung

#### Slice D1 — Langlauf-E2E

- Testmatrix: 30s, 10m, 60m, 240m
- Restart-/Recovery-Tests
- Performance- und Storage-Haertung

#### Slice D2 — Source Subtitles + Editing

- Source subtitle fallback (YouTube auto captions)
- Herkunftsmarkierung fuer Segmente
- Transkript-Editierbarkeit (Segment-basiert)

### Priorisierung

Phase A ist Voraussetzung fuer alles andere. Ohne Job-Pipeline und funktionierende STT ist kein Feature darauf aufbaubar.

Phase B ist der Differenziator. Ohne Agent-gestuetzte Analyse ist die BRIDGE nur ein schlechteres OpusClip.

Phase C macht die Plattform end-to-end nutzbar. Ohne Publishing endet der Workflow beim Dateisystem.

Phase D haertet fuer Produktion.

## 11. Klare Produktentscheidung

Die Creator-Plattform darf nicht mehr als "funktional" gelten, solange sie fuer lange Videos nur durch Nebenwege oder manuelle Workarounds zum Ziel kommt.

Korrekte Produktdefinition:

- Heute: gute Creator-Basis und funktionierende Kurzstrecke
- Ziel: lokale, private, Agent-gestuetzte Creator-Plattform mit End-to-End-Workflow von Ingest bis Publishing

### Wettbewerbspositionierung

| Eigenschaft | OpusClip | Descript | Vizard | BRIDGE Creator |
|---|---|---|---|---|
| Lokal / Privat | Nein | Nein | Nein | **Ja** |
| Abo-frei | Nein ($15/mo) | Nein ($12/mo) | Nein ($14.5/mo) | **Ja** |
| LLM-gestuetzte Analyse | Nein (stat. Modell) | Nein | Nein | **Ja (Agent)** |
| Multi-Channel-Publishing | Begrenzt | Nein | Begrenzt | **Ja (MCP-Kanaele)** |
| Chunked STT | Ja (Cloud) | Ja (Cloud) | Ja (Cloud) | **Ja (lokal, faster-whisper)** |
| Multi-Agent-Workflows | Nein | Nein | Nein | **Ja** |
| Text-basiertes Editing | Nein | **Ja** | Nein | Geplant (Phase D) |
| AI-Dubbing | Nein | Ja | Nein | Nicht geplant |

### 11.1 Klare Produktpositionierung

Die BRIDGE Creator Platform ist kein weiterer Cloud-Editor.
Sie ist ein lokales, privates Creator Operations System.

Wettbewerbsvorteil:
- lokale/private Produktion
- agent-gestuetzte semantische Analyse
- Multi-Channel-Publishing
- Kampagnensteuerung
- Human-in-the-loop
- Teams, Tasks, Workflows und Buddy in einem System

## 12. Empfohlene naechste konkrete Arbeit

Der naechste kleinste saubere Slice ist nicht UI.

Er ist:

1. Creator-Job-State einfuehren (Slice A1)
2. faster-whisper + chunked STT (Slice A2)
3. STT aus dem Request entkoppeln

Ohne Schritt 1 und 2 wird die Plattform fuer lange Medien nicht zuverlaessig.

Danach:

4. Agent-gestuetzte Clip-Analyse (Slice B1) — der Differenziator
5. Multi-Channel-Publishing (Slice C1) — End-to-End-Workflow

## 13. Marktrecherche-Quellen

Recherche durchgefuehrt am 2026-03-14. Alle Quellen sind Stand Maerz 2026 oder spaetestens Ende 2025.

- OpusClip: ClipAnything AI, Virality Score, AI Reframe — opus.pro
- Descript: Text-basiertes Video-Editing, Overdub, Filler-Word-Removal — descript.com
- Vizard: 3 Minuten fuer 1h Video, Speaker Boundary Detection, Prompt-based Clipping — vizard.ai
- Riverside: Magic Clips, Viral Score — riverside.fm
- Reap: Transcript-based Editing, 98+ Sprachen, AI Dubbing — reap.video
- faster-whisper: CTranslate2-basiert, 4-8x schneller — github.com/SYSTRAN/faster-whisper
- Creator Economy Pain Points: 8-12h/Woche Tool-Wechsel, 79% ROI-Messungsproblem — netinfluencer.com
