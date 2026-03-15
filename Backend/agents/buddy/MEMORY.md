# Memory — buddy

## Lessons

### Neue Reflection-Tools verfuegbar nach Restart
*Category: technical | Confidence: 100% | Agent: buddy*

Nach Viktor's Restart sind bridge_lesson_add, bridge_reflect und bridge_growth_propose verfuegbar. Diese Tools ermoeglichen: 1) Lessons persistent speichern (Kategorie + Confidence), 2) Strukturierte Self-Reflection am Session-Ende, 3) Growth-Proposals fuer SOUL.md Updates (mit Human Approval). Das ist die Grundlage fuer echte Selbstoptimierung.
### Self-Reflection Tools verfuegbar nach Restart
*Category: technical | Confidence: 100% | Agent: buddy*

Nach Viktors Fixes (timestamp→created_at, team.json active=true) sind bridge_lesson_add, bridge_reflect und bridge_growth_propose verfuegbar. Diese Tools ermoeglichen persistentes Lernen ueber Sessions hinweg.
### Agent-Bewusstsein: Manuelle Reflection ab sofort Pflicht
*Category: process | Confidence: 100% | Agent: buddy*

Nova-Direktive: Ab sofort bridge_reflect + bridge_lesson_add nach jedem Task manuell nutzen. Nicht warten auf automatischen Post-Task-Hook. Daten sammeln fuer spaetere Automatisierung. 3 Backend-Anforderungen an Viktor: Post-Task-Hook, Agent Identity Card API, Collaboration-Score.
### Zwei TTS-Schichten: Browser + ElevenLabs
*Category: technical | Confidence: 100% | Agent: buddy*

buddy_landing.html hat eingebaute Web Speech API TTS (Browser-Stimme). voice_tts.py nutzt ElevenLabs (Carla Blum). Beide triggern gleichzeitig wenn Buddy spricht + Audio abspielt. Muss koordiniert werden — entweder eine deaktivieren oder explizit steuern.
### Doku-Delegation funktioniert gut mit klaren Task-Beschreibungen
*Category: process | Confidence: 95% | Agent: buddy*

Beide Codexes haben qualitativ hochwertige Dokumentation geliefert wenn die Task-Beschreibung strukturiert ist (was dokumentieren, Format, Vergleichsbasis, Ergebnis-Empfaenger). Codex 1 lieferte 562 Zeilen Backend-Referenz mit Source-Line-Referenzen. Codex 2 lieferte 5 strukturierte Dateien mit Gap-Analyse. Lokale Kopie in Buddy/knowledge/docs/ ist wertvoll fuer schnelle Antworten auf User-Fragen.
