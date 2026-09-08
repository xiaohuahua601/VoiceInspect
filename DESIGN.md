---
version: alpha
colors:
  ink: "#16212B"
  paper: "#F4F1EA"
  panel: "#FFFDF8"
  signal: "#0F766E"
  amber: "#B45309"
  danger: "#B42318"
  line: "#D7D2C8"
  muted: "#5C6872"
typography:
  display:
    fontFamily: "'Aptos Display', 'Segoe UI', sans-serif"
    fontSize: "2rem"
    lineHeight: "1.1"
  body:
    fontFamily: "'Aptos', 'Segoe UI', sans-serif"
    fontSize: "1rem"
    lineHeight: "1.55"
  utility:
    fontFamily: "'Cascadia Mono', Consolas, monospace"
    fontSize: "0.75rem"
    lineHeight: "1.4"
rounded:
  panel: "18px"
  control: "10px"
  pill: "999px"
spacing:
  unit: "4px"
components:
  evidence-timeline:
    surface: "var(--panel)"
    accent: "var(--signal)"
  stage-chip:
    shape: "pill"
    motion: "restrained"
  account-security:
    surface: "var(--panel)"
    accent: "var(--signal)"
  security-banner:
    surface: "#FFF8E6"
    accent: "#B45309"
---

## Overview

VoiceInspect is an operational product for industrial equipment operators working beside a machine, often with limited attention and imperfect connectivity. The interface should feel like a field notebook combined with an instrument panel: calm, legible, evidence-led, and explicit about uncertainty.

The product register is utilitarian rather than promotional. The memorable signature is the evidence timeline: every answer is accompanied by visible capability stages, elapsed time, and source quality.

## Colors

Warm paper and ink create a readable work surface. Teal is reserved for verified progress and primary actions. Amber signals review or incomplete evidence. Red is reserved for safety and destructive outcomes. Never use color alone to communicate state.

## Typography

Use the display face only for page titles and major section landmarks. Body copy remains compact and highly readable. Utility text uses a mono face for model names, trace IDs, and latency so operational details look inspectable rather than decorative.

## Layout

The desktop shell uses a narrow navigation rail, a flexible evidence timeline, and a stable composer footer. On narrow screens the rail becomes a top strip and the timeline remains the primary reading order. Avoid dashboard grids that hide the active diagnosis beneath decorative metrics.

## Elevation & Depth

Use thin warm-gray rules and a single low-contrast shadow for raised panels. Evidence blocks may use a colored edge or icon, but not large decorative gradients.

## Shapes

Panels use a generous 18px radius; controls use 10px; status labels use pills. Keep destructive controls visually separate from the normal composer.

## Components

The shared state language is: queued, running, verified, partial, review, failed, and unavailable. Every async stage reserves space for its status and recovery action to avoid layout jumps.

## Do's and Don'ts

- Do name the evidence source and its limits.
- Do preserve the user's draft when a model or network call fails.
- Do use concise Chinese action labels such as “开始诊断”, “重试”, and “查看依据”.
- Do respect reduced motion.
- Do not present model guesses as equipment facts.
- Do not use empty KPI cards or decorative chat bubbles as a substitute for workflow.

## Security surfaces

Account security uses the same panel and control tokens as the rest of the admin shell. Required password changes use a persistent amber banner with a direct “立即修改” action; the banner is not the only indication of the state because the account page also exposes the policy checklist.
