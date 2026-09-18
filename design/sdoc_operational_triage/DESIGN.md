---
name: SDOC Operational Triage
colors:
  surface: '#fbf8ff'
  surface-dim: '#dad9e3'
  surface-bright: '#fbf8ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f4f2fd'
  surface-container: '#eeedf7'
  surface-container-high: '#e8e7f1'
  surface-container-highest: '#e3e1ec'
  on-surface: '#1a1b22'
  on-surface-variant: '#434655'
  inverse-surface: '#2f3038'
  inverse-on-surface: '#f1effa'
  outline: '#737686'
  outline-variant: '#c3c6d7'
  surface-tint: '#0053db'
  primary: '#004ac6'
  on-primary: '#ffffff'
  primary-container: '#2563eb'
  on-primary-container: '#eeefff'
  inverse-primary: '#b4c5ff'
  secondary: '#712ae2'
  on-secondary: '#ffffff'
  secondary-container: '#8a4cfc'
  on-secondary-container: '#fffbff'
  tertiary: '#46566c'
  on-tertiary: '#ffffff'
  tertiary-container: '#5e6e85'
  on-tertiary-container: '#e9f0ff'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#dbe1ff'
  primary-fixed-dim: '#b4c5ff'
  on-primary-fixed: '#00174b'
  on-primary-fixed-variant: '#003ea8'
  secondary-fixed: '#eaddff'
  secondary-fixed-dim: '#d2bbff'
  on-secondary-fixed: '#25005a'
  on-secondary-fixed-variant: '#5a00c6'
  tertiary-fixed: '#d3e4fe'
  tertiary-fixed-dim: '#b7c8e1'
  on-tertiary-fixed: '#0b1c30'
  on-tertiary-fixed-variant: '#38485d'
  background: '#fbf8ff'
  on-background: '#1a1b22'
  surface-variant: '#e3e1ec'
typography:
  headline-lg:
    fontFamily: Fira Sans
    fontSize: 20px
    fontWeight: '600'
    lineHeight: 28px
  headline-md:
    fontFamily: Fira Sans
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 24px
  headline-sm:
    fontFamily: Fira Sans
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
  body-md:
    fontFamily: Fira Sans
    fontSize: 13px
    fontWeight: '400'
    lineHeight: 18px
  body-sm:
    fontFamily: Fira Sans
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  mono-data-lg:
    fontFamily: JetBrains Mono
    fontSize: 13px
    fontWeight: '500'
    lineHeight: 18px
  mono-data-sm:
    fontFamily: JetBrains Mono
    fontSize: 11px
    fontWeight: '400'
    lineHeight: 14px
  label-badge:
    fontFamily: JetBrains Mono
    fontSize: 10px
    fontWeight: '600'
    lineHeight: 12px
    letterSpacing: 0.04em
  label-header:
    fontFamily: Fira Sans
    fontSize: 11px
    fontWeight: '600'
    lineHeight: 14px
    letterSpacing: 0.05em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 0.75rem
  margin: 1rem
  space-xs: 0.25rem
  space-sm: 0.375rem
  space-md: 0.5rem
  space-lg: 0.75rem
  space-xl: 1rem
---

## Brand & Style

This design system targets high-throughput shipping and document operations personnel processing hundreds of unstructured logistical notices, bills of lading (B/L), shipping instructions (S/I), and customs invoices daily. 

The emotional posture is ultra-calm, unyielding, and utilitarian. It eliminates visual fatigue through rigorous tabular density, zero ambient clutter, and absolute typographic economy. 

The aesthetic is precision-driven **Corporate/Modern with Utilitarian Minimalism**:
- Strict hairline boundaries separate data planes.
- Information layout prioritizes horizontal scannability and structured tabular data over decorative cards or generous padding.
- Micro-interactions are instant (sub-100ms transitions) with crisp state changes, ensuring zero perceived interface latency.

## Colors

The system uses a neutral slate/zinc base paired with targeted semantic tokens to provide high-visibility status monitoring without visual noise.

### Functional Roles & Statuses
- **Primary Accent (`#2563eb`)**: High-priority interactive elements, selection focus, active triage counters, and `BL_COMPARISON` classification badges.
- **Secondary Accent (`#7c3aed`)**: Reserved specifically for `SI_REQUEST` categorization.
- **Neutral Core (`#71717a` / Zinc-Slate gamut)**: Structural frames, borders, subtle surface fills, and low-priority `GENERAL` metadata.

### Semantic Triage Accents
- **OK / Complete**: `#16a34a` (Light Mode text/border) / `#22c55e` (Dark Mode text/fill).
- **Mismatch / Critical Failure**: `#dc2626` (Light Mode text/border) / `#ef4444` (Dark Mode text/fill), also mapped to `SPAM`.
- **Needs Review / Warning**: `#d97706` (Light Mode text/border) / `#f59e0b` (Dark Mode text/fill), shared with `INVOICE_QUERY`.

### Surface Tones & Tokens
- **Light Mode**: Default canvas `#ffffff`, table surface alternate `#f8fafc`, sub-pane surface `#f1f5f9`, crisp hairline borders `#e2e8f0`.
- **Dark Mode**: Default canvas `#09090b`, table surface alternate `#18181b`, sub-pane surface `#27272a`, crisp hairline borders `#3f3f46`.
- High semantic contrast must always be maintained; badges utilize a 10% tinted background of their respective hex paired with a full-contrast border and foreground label.

## Typography

The typographical hierarchy is calibrated for dense scanning and rapid operational pattern recognition. 

- **Fira Sans** delivers high-legibility interface copy, thread subjects, preview summaries, and control affordances.
- **JetBrains Mono** (monospaced alternative to Fira Code) is deployed across all shipping identifiers (e.g., Container numbers, Booking references, B/L codes, HS codes), timestamps, triage statuses, and operational chips.

Rules of application:
- Tabular figures (`tnum`) must be strictly enforced on numeric and monospaced variants to prevent horizontal jitter during live sorting.
- Body sizes are calibrated small (12px–13px) to maximize data yield within the standard 40px row constraint.
- Monospaced badge text enforces uppercase casing with a `0.04em` track expansion to preserve legibility at micro sizes.

## Layout & Spacing

This design system uses a master-detail three-pane operational shell:
1. **Collapsible Navigation Rail**: Fixed width (48px collapsed, 200px expanded).
2. **Dense Triage Grid**: Responsive width (min 480px, max 800px), dedicated to continuous high-throughput scanning.
3. **Inspector & Diff Pane**: Flex-grow right pane for document comparison, extracted metadata, and automated mismatch analysis.

### Spacing & Grid Metrics
- **Row Height Target**: The core triage email/item row is hard-capped at 40px vertical height with a strict vertical padding of `0.375rem` (`space-sm`) and horizontal padding of `0.75rem` (`space-lg`).
- **Data Alignment**: Strict vertical grid alignment. Checkbox (24px width) -> Status Indicator (16px width) -> Identifier (120px fixed mono) -> Sender/Vessel (160px truncate) -> Subject & Snippet (flex) -> Category Chip (auto) -> Time (64px right-aligned mono).
- **Breakpoints**:
  - `Desktop Extended` (≥1440px): 3 full operational panes visible side-by-side.
  - `Desktop Standard` (1024px–1439px): 2 panes (Triage Queue + Inspector drawer).
  - `Mobile / Small Tablet` (<1024px): Single pane view with modal-level document inspection.

## Elevation & Depth

Visual hierarchy is maintained through **crisp hairline borders and surface tonal shifts**, completely eschewing traditional drop shadows or ambient blurs.

- **Level 0 (App Shell / Background)**: Light `#f8fafc` / Dark `#09090b`.
- **Level 1 (Data Grid Rows & Work Surfaces)**: Light `#ffffff` / Dark `#18181b`. Border: 1px solid `var(--border-subtle)` (`#e2e8f0` / `#27272a`).
- **Level 2 (Hover / Active Rows)**: Light `#f1f5f9` / Dark `#27272a`. Border-left accent: 2px solid `var(--primary)`.
- **Level 3 (Inspector Modals, Drawers & Overlays)**: Surface light `#ffffff` / Dark `#18181b` with a solid 1px perimeter border (`#cbd5e1` / `#3f3f46`). For floating popovers only, use a zero-blur crisp keyline outline: `box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.08), 0 4px 6px -1px rgba(0, 0, 0, 0.05)`.
- **Dividers**: All internal grid, table, and header dividers use absolute 1px hairline rendering with no beveling or pseudo-3D gradients.

## Shapes

The design system employs a **Soft (Level 1)** corner philosophy to preserve a technical, disciplined, space-efficient interface.

- **Primary UI controls, inputs, and buttons**: 4px radius (`0.25rem`). Ensures neat stacking inside tight table headers and command strips.
- **Status & Category Badges**: 2px radius. Maintains a distinct squared, technical "punch-card" feel rather than a consumer rounded-pill aesthetic.
- **Data Tables & Card Panels**: 4px corner radii with outer borders, or square (0px) when flush with the viewport window edges to maximize usable pixels.

## Components

### Triage Table Rows (Dense Item Row)
- Height: Fixed 40px.
- Layout: Monospaced identifiers align left; preview text is clamped to 1 line with truncation ellipsis; status dots and category badges sit inline with strict tabular metrics.
- Interaction States: 
  - Neutral: White background with a hairline bottom border.
  - Hover: Tone switch to neutral slate-50 (`#f8fafc`) / Dark (`#27272a`).
  - Selected / Active: `#eff6ff` (Light) / `#1e293b` (Dark) with a 2px high-visibility `#2563eb` left edge indicator.
  - Focused (via keyboard navigation `J`/`K`): 1px dashed interior outline.

### Category Badges
- Display: Inline-flex, height 20px, font: `label-badge`.
- Variants:
  - `BL_COMPARISON`: Blue text (`#2563eb`), border `#93c5fd`, bg `#eff6ff` (Dark: bg `#172554`, text `#93c5fd`, border `#1e40af`).
  - `SI_REQUEST`: Violet text (`#7c3aed`), border `#c4b5fd`, bg `#f5f3ff` (Dark: bg `#2e1065`, text `#c4b5fd`, border `#5b21b6`).
  - `INVOICE_QUERY`: Amber text (`#d97706`), border `#fcd34d`, bg `#fffbeb` (Dark: bg `#451a03`, text `#fcd34d`, border `#92400e`).
  - `GENERAL`: Slate text (`#64748b`), border `#cbd5e1`, bg `#f8fafc` (Dark: bg `#0f172a`, text `#94a3b8`, border `#334155`).
  - `SPAM`: Red text (`#dc2626`), border `#fca5a5`, bg `#fef2f2` (Dark: bg `#450a0a`, text `#fca5a5`, border `#991b1b`).

### Status Micro-Indicators
- Displayed as a dual state: a 6px solid circular dot paired with a monospaced label (`OK`, `MISMATCH`, `REVIEW`).
- Colors follow the semantic tokens exactly.

### Buttons & Action Bars
- **Primary Action**: 32px height, solid `#2563eb` fill, `#ffffff` text, 4px radius, no drop shadow.
- **Secondary / Utility Action**: 32px or 28px height, transparent fill, 1px border `#cbd5e1` (`#3f3f46` Dark), `#0f172a` text.
- Keyboard shortcut indicators: Embedded inside action buttons via monospaced muted badges (e.g., `E`, `R`, `A`).

### Inputs & Filter Bars
- 32px height, font: `body-sm`.
- Static border: 1px hairline `#cbd5e1` (`#3f3f46` Dark).
- Focus state: Immediate `#2563eb` 1px ring without offset blur.

### Comparison / Diff Viewer (Operational Inspector)
- Split screen side-by-side extracted B/L data vs. internal system record.
- In-line character and value diffing using status-red background highlight for mismatches (`rgba(220, 38, 38, 0.12)`) and status-green for verified matches (`rgba(22, 163, 74, 0.12)`).