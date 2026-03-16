# BRIDGE Documentation Index

This directory is currently an index for the working-copy documentation layout of `./BRIDGE`.

## Verifizierte Dokumentpfade

- Root notes:
  - [`README.md`](./README.md)
  - [`CLAUDE.md`](./CLAUDE.md)
  - [`LAUNCH_CHECKLIST.md`](./LAUNCH_CHECKLIST.md)
  - [`TEAM_FINDINGS.md`](./TEAM_FINDINGS.md)
  - [`docs/buddy-bridge-gap-register.md`](./docs/buddy-bridge-gap-register.md) - veraltete Audit-Notiz; relevante Befunde sind in den kanonischen Resume-/Projekt-Doku-Satz integriert
  - [`docs/frontend/clickpath-verification-matrix.md`](./docs/frontend/clickpath-verification-matrix.md) - veraltete Clickpath-Snapshot-Notiz; relevante Befunde sind in den kanonischen Resume-/Projekt-Doku-Satz integriert
  - [`docs/frontend/design-theme-consistency-audit.md`](./docs/frontend/design-theme-consistency-audit.md) - veraltete Design-Snapshot-Notiz; relevante Befunde sind in den kanonischen Resume-/Projekt-Doku-Satz integriert
- Resume and gap-analysis package:
  - [`Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/`](./Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation)
  - [`Fragenkatalog.md`](./Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Fragenkatalog.md)
  - [`Antworten.md`](./Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Antworten.md)
- Archived detailed docs:
  - [`Archiev/docs/README.md`](./Archiev/docs/README.md)
  - [`Archiev/docs/config/team-json.md`](./Archiev/docs/config/team-json.md)
  - [`Archiev/docs/frontend/README.md`](./Archiev/docs/frontend/README.md)
  - [`Archiev/docs/frontend/contracts.md`](./Archiev/docs/frontend/contracts.md)
  - [`Archiev/docs/frontend/gap-analysis-vs-release.md`](./Archiev/docs/frontend/gap-analysis-vs-release.md)
  - [`Archiev/docs/specs/SPEC_SIMPLE_SETUP.md`](./Archiev/docs/specs/SPEC_SIMPLE_SETUP.md)
- Backend infrastructure reference:
  - [`Backend/docs/BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md`](./Backend/docs/BRIDGE_BACKEND_INFRASTRUCTURE_REFERENCE.md)

## Aktueller Befund

- The detailed `docs/` tree documented in older material is not present at root in this working copy.
- Root-`docs/frontend/` enthaelt weiterhin Frontend-Notizen, aber die beiden Audit-Snapshots dort sind jetzt nach Integration in den Resume-/Projekt-Doku-Satz veraltet.
- Die drei Root-Auditnotizen sind jetzt nur noch Snapshots; kanonische Befunde liegen in:
  - `02_Gap_Map.md`
  - `W02_UI_Struktur_Interaktionslogik_und_Zustaende.md`
  - `W06_Fehlerbilder_Inkonsistenzen_Bruchstellen_Risiken.md`
  - `W08_Dokumentationslage_Konsistenzpruefung.md`
- Root documentation and detailed documentation are split between root notes, the resume package, `docs/frontend/`, `Archiev/docs/`, and `Backend/docs/`.
- `LAUNCH_CHECKLIST.md` still marks several root documents as complete although the corresponding root files are absent.
- Packaging metadata refers to `bridge_ide.cli`, and the active root package `bridge_ide/` is present again.
- `bridge-ide status`, `bridge-ide stop` and `bridge-ide start` were all executed successfully via the installed CLI path during this audit; current degradation remains in the started platform state, not in the wrapper entry point itself.

## Offene Punkte

- Whether additional external documentation sources exist outside this working copy.
