---
name: Argus Estate Control
description: A private orbital operations plot for workload topology and guarded action.
colors:
  void: "#070A12"
  deep-field: "#0D1324"
  instrument: "#141D33"
  hairline: "#2A3550"
  text: "#F3F6FC"
  text-muted: "#9AA8BF"
  spectral-blue: "#68A7FF"
  photon-gold: "#F5C85B"
  denial-red: "#FF6B72"
typography:
  display:
    fontFamily: "Arial, Helvetica, sans-serif"
    fontSize: "clamp(2rem, 4vw, 4.75rem)"
    fontWeight: 700
    lineHeight: 0.96
    letterSpacing: "-0.03em"
  body:
    fontFamily: "Arial, Helvetica, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 400
    lineHeight: 1.5
  label:
    fontFamily: "Arial, Helvetica, sans-serif"
    fontSize: "0.6875rem"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0.08em"
rounded:
  control: "6px"
  panel: "14px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "16px"
  lg: "24px"
  xl: "40px"
components:
  button-primary:
    backgroundColor: "{colors.photon-gold}"
    textColor: "{colors.void}"
    rounded: "{rounded.control}"
    padding: "10px 14px"
  button-secondary:
    backgroundColor: "{colors.instrument}"
    textColor: "{colors.text}"
    rounded: "{rounded.control}"
    padding: "10px 14px"
---

# Design System: Argus Estate Control

## Overview

**Creative North Star: "Orbital Operations Plot"**

Argus behaves like a tracking table for a private system: stable trust domains
form orbital bands, workloads are known objects, and drift is a trajectory that
must be understood before action. The surface is dense but calm, designed for a
single operator working under low ambient light without turning infrastructure
into theatrical sci-fi chrome.

**Key Characteristics:**

- Topology is the primary instrument, not a decorative graph.
- Every glow, ring, and vector encodes real state.
- Lists and tables preserve keyboard access and exact values.
- Mutation controls remain visually and technically separate from observation.

## Colors

Void and deep navy establish depth; spectral blue identifies observed state,
photon gold marks selection and deliberate action, and denial red is reserved
for blocked or dangerous conditions.

**The Signal Scarcity Rule.** Gold and red never decorate. They appear only when
the operator must focus or stop.

## Typography

Arial and Helvetica keep the instrument familiar and highly legible. Large type
is limited to the product title and estate totals; data and labels remain compact
without adopting monospace as a technical costume.

**The Measurement Rule.** Use tabular numerals for quantities and timestamps,
not a different font family.

## Layout

The first viewport divides into a persistent 72px navigation rail, a fluid
orbital plot, and a 360px inspection drawer. Detail sections use aligned rows and
tables below the plot. At narrow widths the drawer becomes inline, the plot
becomes a horizontally scrollable instrument, and every topology object remains
available in the workload list.

## Elevation & Depth

Depth comes from nested dark fields and one soft offset shadow on the active
inspection surface. Resting rows and controls use tonal separation rather than
shadows.

## Shapes

Orbit geometry is circular. Operational surfaces use restrained 14px panels and
6px controls. Pills are reserved for compact state labels; content containers
never become a field of identical rounded cards.

## Components

### Buttons

Primary buttons use photon gold only for the next deliberate action. Secondary
buttons use the instrument field. Focus is a solid blue outline; disabled state
removes contrast and never relies on opacity alone.

### Topology Plot

Concentric domain paths use distinct dash patterns and text labels. Workload
objects carry names, not anonymous dots. A selected object reveals one direct
trajectory line to its inspection drawer.

### State Rows

Declared and effective state occupy aligned columns. Drift adds a text label and
a visible vector; color reinforces but never carries the meaning alone.

## Do's and Don'ts

### Do:

- **Do** make every orbital mark correspond to canonical topology data.
- **Do** keep blocked, unavailable, and stale states readable without color.
- **Do** show exact target, policy status, and rollback availability before action.

### Don't:

- **Don't** add decorative stars, fake telemetry, or invented operator data.
- **Don't** use gradients or glow outside the topology instrument.
- **Don't** make a domain operation appear available without its backend agent.
