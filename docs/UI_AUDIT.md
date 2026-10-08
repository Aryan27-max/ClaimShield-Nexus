# UI audit

Captured every page headless at 1440×900 (light) and the Queue / Case at 1280×800 (dark) before the polish pass, then reviewed each screenshot against: user journey, usability, accessibility (WCAG 2.2 AA), visual polish and consistency. Severity: **High** (blocks a first-time user or fails accessibility), **Medium** (slows the user or looks inconsistent), **Low** (polish). Status was updated after the fix pass and a visual QA loop (every page in both themes at 1440×900, Overview / Queue / Case at 1280×800).

| # | Page | Issue | Severity | Fix | Status |
|---|---|---|---|---|---|
| A1 | Sidebar | Brand block (name + tagline) sits below the navigation and the logo is tiny, so the hierarchy is unclear. | Medium | Brand first: logo, name and one-line tagline at the top; navigation after. | fixed |
| A2 | Sidebar | "Public demo · synthetic data · shared state" pill wraps onto two lines. | Low | Shorter label with the detail in a tooltip. | fixed |
| A3 | Sidebar | Long column of controls; "Reset demo" and "Re-run pipeline" are two identical blue buttons stacked against each other. | Medium | Group into "Session" and "Demo tools"; demo tools in an expander; secondary / destructive styles. | fixed |
| A4 | All | No way to choose light or dark mode; dark only via the operating system. | Medium | Light / Dark toggle at the top of the sidebar, persisted in the URL. | fixed |
| A5 | All | Every button is the same filled blue: no primary / secondary / destructive hierarchy. | High | Three button styles; one primary action per section; destructive actions in the danger colour. | fixed |
| A6 | All | Custom-styled buttons and links show no visible keyboard focus. | High | Focus ring token applied to `:focus-visible` on buttons, links, tabs and inputs. | fixed |
| A7 | All | Action badges use white text on orange, green, red and grey fills (white on #34C759 is 2.2:1), failing WCAG AA. | High | Tinted badges with accessible text colours per theme, enforced by a contrast test. | fixed |
| A8 | All | Unexplained jargon: MFCU, PREPAY review, NEEDS_MORE_DATA, evidence class, P(escalation), PPR percentile, mandate, dual control, credible allegation, PHI masking. | High | Help tooltips on the labels plus a glossary popover in the sidebar. | fixed |
| A9 | Overview | A first-time visitor gets numbers but no sense of the flow or what to do next. | High | "How it works" strip (Detect → Fuse → Policy → Queue → Decide + Ledger) linking to pages, and a primary "Open SIU Queue" button. | fixed |
| A10 | Case, Network, info boxes | Raw enums in prose ("REFER_TO_MFCU is allowed…", "case RING-P0007 · REFER_TO_MFCU"). | Low | Human labels ("Refer to MFCU") in prose; enums only in audit tables. | fixed |
| A11 | Overview | Card title "$ at risk by recommended action" wraps to two lines and unbalances the row. | Low | Shorter title. | fixed |
| A12 | Overview | Compliance tiles sit below the fold with no section heading. | Low | "Compliance workflow" section heading with a short explanation. | fixed |
| A13 | Queue | Money format inconsistent: table shows cents ($182,137.55) while tiles round ($182,138). | Medium | Whole dollars with thousands separators everywhere. | fixed |
| A14 | Queue, Case | Confidence shown as 0.94 and P(escalation) as 1.00 next to percentages elsewhere. | Medium | Show both as percentages. | fixed |
| A15 | Queue | The "Open case" control is below a 520 px table, out of view; the row checkboxes do not say they open a case. | High | Primary "Open case" action above the table with the top case preselected; caption explaining row selection. | fixed |
| A16 | Queue | At 1280 px the table scrolls horizontally (Status cut off) and the toggle label truncates. | Medium | Fewer, narrower columns; shorter toggle label. | fixed |
| A17 | Queue | Tile labels wrap at 1280 px ("Over capacity", "Weeks to clear"), giving three-line tiles. | Low | Shorter tile copy. | fixed |
| A18 | Queue | Banner copy "9 must-take case(s) exceed…" reads as a template. | Low | Proper pluralisation and a clearer next step. | fixed |
| A19 | Case, Network | The case / entity selector sits above the page title, so the first thing on the page is a dropdown. | Medium | Title and subtitle first; selector in the header row. | fixed |
| A20 | Case | The decision form is at the very bottom below seven tabs; the main action is hard to find. | High | "Record decision" call to action in the header that jumps to the form; the form explains who can sign. | fixed |
| A21 | Case | Tile labels "P(escalation, 90 d)" and "fused 0.94 × completeness 1.00" are opaque. | Medium | Plain labels with help tooltips. | fixed |
| A22 | Case | Generic blue info box for the MFCU notice. | Low | Styled notice consistent with the design system. | fixed |
| A23 | Case, Policy, Queue | ISO dates (2026-10-09). | Low | "Oct 9, 2026" everywhere a person reads dates. | fixed (Audit Ledger keeps full UTC timestamps: won't-fix, audit precision) |
| A24 | Network | "PPR percentile" is unexplained and the graph renders without any loading indicator. | Medium | Plain label + tooltip; spinner while the graph is built. | fixed |
| A25 | Policy | Threshold labels are technical, there is no hint of what changing them does, and "Preview impact" is disabled without saying why. | Medium | Help per slider; caption "Change a threshold to enable the preview". | fixed |
| A26 | Policy | "Created 2026-10-08" in ISO; the author tile wraps. | Low | Readable date; compact tile. | fixed |
| A27 | Audit Ledger | Subtitle shows the hash formula and the table shows raw JSON payloads: developer-facing. | Medium | Plain subtitle (formula in a tooltip) and a readable "summary" column. | fixed |
| A28 | Audit Ledger | "Simulate tamper" and "Reset demo ledger" are destructive but look like normal actions; tamper has no confirmation. | High | Destructive style and an explicit confirmation for both. | fixed |
| A29 | All | No toasts: sign, approve, save and verify only show inline messages that can be off-screen. | Medium | `st.toast` after each of them. | fixed |
| A30 | Network, cold start | No loading state for the slowest elements. | Low | Spinners with plain-language text. | fixed |
| A31 | Overview, Case, Policy | Charts have no text alternative. | Medium | A one-line caption under each chart stating what it shows. | fixed |
| A32 | All | No consistent spacing scale; card, section and button gaps vary. | Medium | 4/8/12/16/24/32/48 px tokens applied to page padding, sections, cards and button rows. | fixed |
| A33 | All | No page tells the user what they can do there. | Medium | One-line "what you can do here" subtitle on every page. | fixed |
| A34 | All | Empty states are inconsistent (some pages show nothing when there are no decisions, approvals or obligations). | Medium | Friendly empty-state cards with the next step. | fixed |
| A35 | All | Visual QA: the sticky top bar was transparent, so scrolled content showed through the navigation. | Medium | Opaque bar in the page background colour with a hairline border. | fixed |
| A36 | All (light) | Visual QA: primary and form-submit buttons rendered dark text on blue in light mode (markdown colour overrode the button colour). | High | Button labels inherit the button text colour. | fixed |
| A37 | Network, Case (dark) | Visual QA: a white frame and corners around the dark network graph. | Low | Graph card border and background follow the theme. | fixed |
| A38 | Queue, Case | Visual QA: at 1280 px the queue clipped evidence-class chips and the evidence table scrolled sideways. | Medium | Rebalanced column widths; "Next due" header. | fixed |
| A39 | Policy, Overview | Visual QA: raw enums in threshold labels and the dual-control caption; step 5 title clipped at 1280 px. | Low | Plain action names; step title "Decide". | fixed |
| A40 | Case | Evidence table column names (claim_id, field, owner_id …) are raw data field names. | Low | — | won't-fix: every suspicion must cite the exact field and value (principle 3); investigators audit against the data. |
| A41 | All | ui/style.py exceeds the 250-line module guideline. | Low | — | won't-fix: all styling is deliberately kept in one file; theme state and formatting were split out to ui/theme.py and ui/fmt.py. |
