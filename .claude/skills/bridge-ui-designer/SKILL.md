---
name: bridge-ui-designer
description: "Frontend Designer fuer die Bridge-IDE UI (bridge/ui.html). Verwende diesen Skill bei allen UI-Aenderungen, neuen Komponenten, Icon-Anpassungen, Layout-Korrekturen oder visuellen Verbesserungen der Bridge-Plattform. Kennt das vollstaendige Design-System mit Tokens, Komponenten, Typografie, Spacing und Interaktionsmustern. Aktiviert bei Anfragen wie 'mach den Button kleiner', 'aendere das Icon', 'passe das Design an', jeder UI-Aenderung an bridge/ui.html."
---

# Bridge UI Designer

## Kontext

Zieldatei: `/home/leo/Desktop/CC/bridge/ui.html`
Live unter: `http://127.0.0.1:9111/`
Technologie: Vanilla HTML/CSS/SVG/JS — kein Framework, kein Build-Step.

Vor jeder Änderung: relevante Zeilen mit Read (offset+limit) lesen. Nach jeder Änderung: `http://127.0.0.1:9111/` neu laden und verifizieren.

---

## Design-Sprache

### Themes

3 Modi via `data-theme` auf `<html>`: `warm` (Standard), `light`, `dark`.

**warm** — Claude-like Off-White (primäre Arbeitsumgebung):
- `--bg: #fbf8f1` / `--card: #fff` / `--card2/3: #fbf8f1`
- `--border: #d9d4c9` / `--border2: #e6e1d7`
- `--text: #151a22` / `--muted: #6b7280` / `--muted2: #9aa3ad`
- `--accent: #111827` / `--accentText: #fff`
- `--danger: #e11d48` / `--success: #0e9f6e` / `--warning: #d97706`

**light**: `--accent: #4b5563`
**dark**: `--bg: #0b1220` / `--accent: #38bdf8` / `--accentText: #06101a`

Accent-Transparenz-Skala (nie hardcoded rgba verwenden):
`--accentSoft` → `--accentEdgeWeak` → `--accentEdgeMid` → `--accentEdgeStrong`

### Typografie

```
Font:  ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto
Mono:  ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas
```

| Rolle          | Size  | Weight | Besonderheit                       |
|----------------|-------|--------|------------------------------------|
| Brand/Titel    | 15px  | 700    |                                    |
| Kicker/Label   | 11px  | 700    | uppercase; letter-spacing:.14em    |
| Section title  | 11px  | 700    | uppercase; letter-spacing:.10em    |
| Body/Message   | 13px  | 400    | line-height:1.5                    |
| Input/Button   | 12px  | 700    |                                    |
| Badge          | 10px  | 400    | font-family: var(--mono)           |
| Sub/Meta       | 12px  | 400    | color: var(--muted2)               |

### Spacing (8px-Grid)

```
--gap: 16px        Haupt-Layout-Abstand
Card padding:      12–14px
Panel padding:     12px
Inner gaps:        10px (Standard), 6–8px (eng), 2px (minimal)
Input padding:     10px 10px
Button padding:    11px 12px (.btn)  /  12px 14px (.send)
```

### Border-Radius

```
--r:  16px   → .card
--r2: 14px   → .panel, .btn, input, textarea, .send
14px         → details.agent, .agentGroup, .msg
12px         → .themeSel, .acwLogo
6px          → kleine inline Buttons (send-in-textarea)
999px        → .pill, .dot, .bar, .badge
```

### Schatten & Borders

- Elevation: immer `var(--shadow)` — nie eigene box-shadow für Cards
- Borders: `1px solid var(--border2)` (Standard) / `var(--border)` (Inputs)
- Focus-Ring: `border-color: var(--accentEdgeMid); box-shadow: 0 0 0 4px var(--accentSoft)`

---

## Komponenten-Referenz

### Card (Haupt-Container)
```css
.card     → border + card-bg + r:16px + shadow + overflow:hidden
.cardHead → padding:12px 14px; border-bottom; card3-bg; flex space-between
  .kicker → 11px uppercase letter-spacing:.14em muted 700
  .meta   → 12px muted2 truncate max-width:65%
```

### Panel (Inner-Container)
```css
.panel     → border + card-bg + r:14px + overflow:hidden + flex-col
.panelHead → padding:10px 12px; border-bottom; card3-bg
  b        → 12px 700 text
  .hint    → 11px muted2 truncate
.panelBody → flex:1; overflow:auto; padding:12px; gap:12px; scrollbar-thin
```

### Buttons
```css
.btn          → flex:1; border(--border); card2; r2; 11px 12px; 12px 700
.btn.primary  → accentEdgeStrong border; accent-bg; accentText
  (warm override: bg:#efece4; color:#2f3741; border:#e5dfd2)
.btn:hover    → filter:brightness(1.02); border-color:accentEdgeWeak
.btn:active   → translateY(1px)

.send         → accent border+bg; accentText; r2; 12px 14px; 12px 700
.send:hover   → filter:brightness(1.03)
```

### Inline Send-Button (in Textarea)
```css
position:absolute; bottom:8px; right:8px
width:26px; height:26px; border:none; border-radius:6px
background:var(--accent); color:var(--accentText)
cursor:pointer; display:grid; place-items:center
opacity:0.85; transition:opacity .15s
```
Hover: `onmouseenter="this.style.opacity='1'"` / `onmouseleave="this.style.opacity='0.85'"`

### Message Card
```css
.msg       → flex gap:10px; padding:10px 12px; r:14px; border(--border); card3-bg
.msg:hover → border-color: var(--accentSoft)
.bar       → width:3px; r:999px; height:18px; flex:0 0 auto  (linker Akzentstreifen)
  .bar.user  → rgba(107,114,128,.65)
  .bar.lead  → var(--accent)
  .bar.agent → var(--agentBar)
.mMeta     → flex gap:8px; 11px muted2; flex-wrap; margin-bottom:6px
.mText     → 13px line-height:1.5; pre-wrap; word-break:break-word
```

### Badge
```css
.badge         → mono 10px; padding:2px 8px; r:999px; border(border2); card2; muted
.badge.control → orange: rgba(217,119,6,...) border/bg/color
```

### Status-Dots (3-State)
```css
.sd         → 7px circle; opacity:.28; transition scale+opacity
running     → .run (success) scale(1.55) opacity:1
waiting     → .wait (warning)
disconnected→ .off (danger)
```

### Composer (Bottom-Chat-Eingabe)
```css
.composer   → border-top(border2); padding:12px 14px; card3-bg; flex gap:10px; align-end
.inputWrap  → flex:1; border(border); card-bg; r2; padding:10px
  :focus-within → accentEdgeMid + 4px accentSoft
textarea    → no border; transparent; 13px; min:44px max:140px
```

---

## SVG-Icons

Alle Icons: `viewBox="0 0 24 24"`. Stil: stroke-basiert, fill:none, stroke-width:2, stroke-linecap:round, stroke-linejoin:round.

| Icon           | SVG-Inhalt                                                                          |
|----------------|-------------------------------------------------------------------------------------|
| Paper-Plane    | `<line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>` |
| Checkmark      | `<path d="M5 13l4 4L19 7" stroke-width="2" fill="none"/>`                          |
| Chevron down   | `<polyline points="6 9 12 15 18 9"/>`                                               |

Größen: 13px in Inline-Buttons, 16–18px in Panel-Headers, 20px dekorativ.
Niemals gefüllte Play-Dreiecke (`M8 5v14l11-7z`) für Send-Aktionen verwenden.

---

## Interaktionsmuster

| Zustand   | CSS                                                              |
|-----------|------------------------------------------------------------------|
| Hover     | `filter:brightness(1.02–1.03)` oder `border-color:accentEdgeWeak` |
| Active    | `transform:translateY(1px)`                                      |
| Focus     | `border-color:accentEdgeMid; box-shadow:0 0 0 4px accentSoft`   |
| Disabled  | `opacity:.45; cursor:not-allowed`                                |
| Transition| `filter .12s ease, transform .08s ease, border-color .12s ease` |
| Fade      | `opacity:.85` → `1` on hover via `transition:opacity .15s`      |

---

## Arbeitsregeln

1. **Niemals hardcoded Farben** — ausschließlich `var(--...)`
2. **Alle 3 Themes** — Änderungen müssen in warm/light/dark konsistent sein
3. **Radius nur aus Tabelle** — keine neuen Werte einführen
4. **Typografie-Skala einhalten** — keine neuen Font-Sizes
5. **Icons: stroke-only** — fill nur für semantisch gefüllte Elemente
6. **Vor Edit: Zeilen lesen** — Read mit offset+limit
7. **Nach Edit: Browser-Reload** — `http://127.0.0.1:9111/`

## Checkliste vor Präsentation

- [ ] Nur CSS-Variablen, keine Hartwerte?
- [ ] Radius aus Tabelle?
- [ ] Icon stroke-konsistent?
- [ ] Hover/Active/Focus vorhanden?
- [ ] Alle 3 Themes kompatibel?
