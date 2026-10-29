---
name: Field specific lacuna identifier
description: Compact local research specification and evidence workbench
colors:
  primary: "#B4DFC4"
  background: "#080A0D"
  surface: "#11151B"
  foreground: "#E3E8EF"
  caption: "#A3ADBA"
  divider: "#242B35"
  selection-background: "#294638"
  selection-text: "#F0F5F3"
  scrollbar: "#39424F"
typography:
  display:
    fontFamily: "Times New Roman, Times, serif"
    fontSize: 1.22rem
    fontWeight: 600
    lineHeight: 1.45
    letterSpacing: -.02em
  headline:
    fontFamily: "Times New Roman, Times, serif"
    fontSize: 1.05rem
    fontWeight: 600
    lineHeight: 1.45
  title:
    fontFamily: "Times New Roman, Times, serif"
    fontSize: .92rem
    fontWeight: 600
    lineHeight: 1.45
  body:
    fontFamily: "Times New Roman, Times, serif"
    fontSize: .84rem
  label:
    fontFamily: "Times New Roman, Times, serif"
    fontSize: .84rem
  caption:
    fontFamily: "Times New Roman, Times, serif"
    fontSize: .73rem
  input:
    fontFamily: "Times New Roman, Times, serif"
    fontSize: .82rem
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.background}"
---

# Design System: Field specific lacuna identifier

## Overview

**Creative North Star: "Technical research workbench"**

A compact technical research workbench, pinned explicitly by the user. The exact temporary product name is Field specific lacuna identifier. Near-black surfaces, serif interface text with monospace code, a small heading, and actual schema labels support expert inspection. Authored copy is English; original research content retains its source language.

Authority: explicit user direction, recorded in PRODUCT.md. Mode: Operate. This is a reconciliation of the implemented system in app.py and .streamlit/config.toml, with terminal presentation in lacuna/cli.py.

**Key Characteristics:**
- Compact, schema-oriented expert interface.
- Near-black tonal surfaces with a restrained pale green accent.
- Shared JSON request contract across local web and terminal modes.

## Colors

### Primary
The pale green primary token identifies primary actions, caret, and authored keyboard focus. Primary button text, including nested paragraph and span text, uses the background ink token.

### Neutral
Background and secondary surface establish the dark workspace. Foreground is the main text role; caption remains fully opaque. Divider defines the sidebar rule. Selection and scrollbar tokens retain legibility within dense text.

## Typography

Times New Roman, Times, serif supplies ordinary interface text and headings without remote font requests. Code blocks, JSON editing, and schema field labels use a monospace stack. Frontmatter records authored sizes; unspecified weights and line heights remain framework supplied. The display role maps to H1, headline to H2, and title to H3. Body paragraphs, list items, and labels share the body/label size. Inputs and textareas use the input size; captions use the caption size. H1 tightens to 1.04rem at the compact breakpoint. Caption parent opacity is explicitly 1, avoiding inherited dimming.

## Layout

The wide Streamlit content container has a maximum width of 1280px, top padding of 1.65rem, and bottom padding of 3rem. At viewport widths up to 640px, container padding becomes 1rem .85rem 2rem. The sidebar content top padding is 1.6rem. H1 bottom margin is .1rem; H2 top margin is 1.2rem. Native Streamlit columns arrange form fields and compact actions; wrapping and stacking remain framework behavior.

## Elevation & Depth

Authored depth uses dark tonal surfaces and the sidebar divider. There is no authored shadow scale. Native Streamlit popovers, controls, notifications, and their depth treatments remain framework supplied.

## Shapes

The form wrapper removes its border and padding. The sidebar has a 1px divider. Other control radii, heights, and internal spacing remain native Streamlit geometry; no custom radius scale is defined.

## Components

### Buttons
Primary actions use the primary background and background ink foreground. Secondary buttons and downloads retain native Streamlit styling. Authored keyboard focus uses a 2px primary outline with a 3px offset. Hover and disabled treatments remain native; no custom states are invented.

### Inputs / Fields
Labels expose actual schema names. Input caret uses primary; selection uses the dedicated selection pair. File inputs, JSON editor, form fields, validation errors, and progress indicators use native Streamlit controls. The JSON editor has an authored height of 580px.

### Navigation
The four tabs are Specification, Results, Artifacts, and Runs. Runtime is the sidebar heading. Native Streamlit supplies tab geometry and selection treatment. Surface composition and behavior are documented in .impeccable/surfaces/research.md.

### Evidence ledger
The results table places score before title and uses tabular numerals. A separate study selector exposes full title and evidence details, including original text, actual JSON keys, and physical PDF pages. Horizontal-table guidance is explicit.

### Terminal presentation
Rich panels, tables, prompts, and progress use stderr. Machine-readable run, validation, and request output uses plain JSON on stdout; template prompt output is plain text. Rich controls ANSI presentation based on terminal capability. The terminal accent is bright_cyan and muted text is grey70; these terminal names do not redefine web palette tokens. Menu, paste, wizard, file/stdin, and local web entry paths share the request contract. Reduced-motion preference disables authored web animations and transitions.

## Do's and Don'ts

### Do:
- **Do** preserve the exact user-pinned name and compact technical character.
- **Do** use actual schema keys and inspectable evidence.
- **Do** keep captions fully opaque and primary-action text in the background ink color.

### Don't:
- **Don't** substitute a new identity or enlarge the heading into a hero.
- **Don't** author non-English interface copy.
- **Don't** infer fixed native component geometry from this document.

Typography refinement: the user explicitly requested Times New Roman for all ordinary interface text and the title. Technical code blocks, the request JSON editor, and schema field labels retain a monospace stack.


## Field gaps

A dedicated Field gaps tab accepts a topic, optional keyword groups and thesis sources. Results distinguish quoted author statements from current unresolved status. Physical pages, abstract-only evidence, thesis-type provenance, access limits and follow-up search outcomes stay visible. JSON and Markdown exports support external assistant review. The terminal exposes the same engine through menu option 6 and the `gaps` command.
