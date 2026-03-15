VERALTET

Diese Audit-Notiz ist nicht mehr die kanonische Referenz. Ihre noch gueltigen Befunde sind in den aktiven Resume-/Projekt-Doku-Satz integriert, insbesondere in:

- `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/W02_UI_Struktur_Interaktionslogik_und_Zustaende.md`
- `Codex_resume-019cdc3e-4534-7f13-9b0b-979a408e9ead/Projekt_Dokumentation/W08_Dokumentationslage_Konsistenzpruefung.md`

# Frontend Design and Theme Consistency Audit

## Scope

This note records verified visual and interaction-consistency findings from the `2026-03-12` browser audit.
It only includes issues that were either reproduced directly in the browser or measured in code-backed runtime probes.

## Verified findings

| Severity | Page | Finding | Verified evidence | Consequence |
| --- | --- | --- | --- | --- |
| high | `chat.html` | Approval panel close button is visually present but not operable in the live layout | A browser click on `#panelClose` timed out while Playwright reported that `<header id="boardHeaderRight">` intercepted pointer events. The panel stayed open with class `approvalPanel approvalPanel--open`. | The approval panel can open but not reliably close through its own close control. |
| high | `chat.html` | Sidebar footer collapses into overlap at narrow sidebar widths | A browser run forced `--sw:88px` and measured `.sidebarBottom` width `56px`, the approval badge at `x=50..80`, and the user-name rect at `x=73..73` with `overlap:true`. User screenshot shows the bell overlapping the user name in the same area. | The dragged sidebar can enter a visually broken state where the footer identity area is no longer legible. |
| medium | `control_center.html` | Total-agent metric is visually mixed with a live-status signal | The footer metric renders `<span id="metricAgents">59</span><span class="metric__pulse"></span>`, while `.metric__pulse` is hard-coded green (`rgb(34, 197, 94)`). In the same pre-restart browser probe, the real live status was separately shown as `4 online` in the top bar. | Inventory count and liveness are visually conflated, so the footer can imply "59 online" even though it is only showing total agents. |
| medium | Cross-page select styling | Visible selection boxes are not harmonized across the current frontend surfaces | Browser style probe found: `task_tracker.html` selects at `28px` height / `6px` radius / opaque warm background, while `project_config.html` selects at `34px` / `8px` / translucent white background. | Selection controls do not present as one coherent product system across the current frontend pages. |
| medium | `control_center.html` | Default dashboard DOM is extremely dense compared with the visible surface | A page inventory pass found `2744` total buttons but only `16` visible on the default state of `control_center.html`. | Large hidden control surfaces make visual consistency and interaction layering harder to reason about and increase the chance of overlap/regression bugs. |

## User-reported issue not reproduced in direct probe

### `control_center.html` black theme showing light automation cards

User-provided screenshot shows the automation area rendered in a light palette while the theme is described as `black`.

Direct browser probes on the workflows tab with `localStorage.bridge_theme = "black"` did not reproduce that exact state:

- `html[data-theme]` was `black`
- body background was black
- in a later stable re-probe, the page still loaded with `data-theme="black"` and black body background, but no visible workflow/automation cards rendered in that exact snapshot

Status: Fehler nicht reproduzierbar.

Verifiziert durch Ausführung:
- direkter Black-Theme-Probe auf `control_center.html?tab=workflows`
- erneuter stabiler Probe-Lauf nach Runtime-Neustart mit schwarzem Theme und schwarzem Body-Hintergrund

## Interpretation

The current visual consistency issues are not random CSS noise.
They cluster around three structural patterns:

- layout collision in dense surfaces with fixed/floating chrome
- visual mixing of state signals and inventory numbers
- page-local form styling without a shared control contract

These findings are design issues, but they are also operational issues because they change how reliably the live runtime state is communicated to the user.
