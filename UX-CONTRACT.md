# VoiceInspect UX Contract

## Product and locale

- Product surface: authenticated industrial diagnosis console.
- Primary locale: `zh-CN`.
- Default time storage: UTC; render in the browser's local timezone.
- Accessibility target: WCAG 2.2 AA.

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Authentication | `LoginView` + API bearer token | This contract and API authorization | Operator / administrator | API integration + login flow |
| Diagnosis composer | `EvidenceComposer` | This contract and message API | Text now; audio/image additive | Typecheck + E2E |
| Async stage state | `StageTimeline` | This contract and stage state schema | queued / running / verified / partial / failed | Unit + E2E |
| Toast | `StatusBanner` | This contract | success / warning / info / error | Live-region test |
| Citation | `CitationDrawer` | Citation API response | Inline expand / detail route | API + interaction test |
| CRUD | `ConfirmationCard` | Tool confirmation API | Preview / confirm / cancel / expired | Integration + E2E |
| Select/Listbox | Native `select` in `EvidenceContext` | This contract and browser semantics | Native select | Keyboard + narrow viewport |
| Form | Native form fields with shared validation contract | This contract | Login / composer | Typecheck + interaction test |
| Scrollbar | Global stylesheet | `DESIGN.md` | Application document | Static audit + visual review |

## Core behavior ledger

| Operation | Pending | Success | Failure recovery |
|---|---|---|---|
| Login | Button busy, form remains stable | Open workspace | Inline generic error, preserve username |
| Create session | Button busy | Select new session | Keep form usable, show retry |
| Send diagnosis | Stage timeline running | Append evidence answer | Preserve draft and show retry |
| Upload asset | Progress/status reserved | Attach preview | Explain supported type/size |
| Retry stage | Only target stage busy | Replace stage result | Keep all other completed results |

## Interaction rules

- Forms use `novalidate`; errors are owned by the application.
- Enter sends the text composer; Shift+Enter inserts a newline.
- Busy buttons retain their dimensions and expose `aria-busy`.
- All clickable controls are native buttons or links with visible focus.
- Reduced-motion users receive the same status information without animated transitions.
- Server authorization is authoritative. The client may hide irrelevant admin routes, but every protected endpoint enforces its role.