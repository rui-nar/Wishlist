# Review ledger — Design system (Lagoon)

Subject: docs/plans/DESIGN_SYSTEM_PLAN.md
Envelope: plan section "Review envelope", plus REVIEW.md defaults

Approval: under the owner's standing instruction of 2026-11-08 ("proceed
systematically with your recommendations"), the orchestrator approved the
triaged table after enforcing the floors, and answered envelope questions with
its recommendation. No floor finding was rejected.

## Round 1 — 2026-11-08, reviewed at 176b533

Envelope question: must the web client make zero requests to Google, or only
none for its own UI text? Answer (orchestrator, standing instruction): none for
the app's own UI text (bundled fonts plus a `Roboto` alias); Google-hosted
fallback fonts for emoji and non-Latin user-entered characters are accepted for
now and named in the privacy policy. Written into the plan's envelope and D4.

### R1-1 — The web engine fetches Roboto from fonts.gstatic.com whatever the bundled fonts
- Trigger: any user opens the web client → the engine finds no `Roboto` family in the font manifest and downloads it from fonts.gstatic.com → the envelope and DoD claims are false while U1's grep passes
- Scores: trigger=concrete, impact=degraded-ux (triager: was wrong-visible), detect=silent, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: D4 `Roboto` alias, envelope, U1 acceptance, DoD)

### R1-2 — goldens.ps1's bind mount shares client/.dart_tool and build with the Windows SDK
- Trigger: owner runs `.\goldens.ps1`, then `.\dev.ps1` → package_config.json holds Linux paths → the Windows build fails until `flutter pub get` is run by hand
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: container-only volumes, new U4 acceptance)

### R1-3 — U4's "-Check exits 0 with no golden tests" cannot pass
- Trigger: verifier runs `.\goldens.ps1 -Check` in wave 1 → `flutter test --tags golden` selects no test and exits non-zero → U4 fails on its own criterion
- Scores: trigger=concrete, impact=maintainability (triager: was wrong-visible), detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: acceptance uses a throw-away golden test)

### R1-4 — Light metadata grey #64748B on the page background is 4.34:1
- Trigger: U1 implementer writes the contrast test → the light pair fails → the shipped colour differs from D2 and from theme_test
- Scores: trigger=concrete, impact=maintainability, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: `onSurfaceVariant` light is `#475569`)

### R1-5 — gen-l10n output is under client/lib/l10n, not .dart_tool; U2 names the root .gitignore
- Trigger: U2 runs `flutter pub get` → generated files appear in client/lib/l10n → .gitignore entry needed
- Scores: trigger=theoretical (triager: was concrete — U2 step 6 already covers it and the root .gitignore can ignore client paths), impact=maintainability, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Reject (D11)
- Override: —
- Outcome: open

### R1-6 — D2 omits ColorScheme roles that the constructor requires and D6's widgets read
- Trigger: U1 implementer writes the ColorScheme from D2 → secondary, secondaryContainer, inverseSurface, surfaceContainerHighest, outlineVariant are invented → not pinned by theme_test
- Scores: trigger=concrete, impact=cosmetic, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D7)
- Override: —
- Outcome: fixed (in plan: the D2 table lists every role, U1 step 8 checks them)

## Round 2 — 2026-11-08, reviewed at 9ad65ce

Every pair the contrast test lists was recomputed by the reviewer in both
themes and passes. No Fix now: review of the plan complete (§6).

### R2-1 — Dark metadata grey on surfaceContainerHighest is 4.04:1, untested
- Trigger: a filled text field (fill = `surfaceContainerHighest`) in dark mode → hints and labels in `#94A3B8` on `#334155` → below 4.5:1 while the contrast test passes
- Scores: trigger=plausible, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=inferred (arithmetic verified)
- Decision: Defer (D10)
- Revisit when: `InputDecorationTheme` sets `filled: true`, any screen puts `onSurfaceVariant` text on `surfaceContainerHighest`, or the owner's dark-palette check flags low-contrast hints — then add the pair to `contrast_test.dart` and fix the colour if it fails
- Override: —
- Outcome: open

## Round 3 — 2026-11-08, integrated diff (DELIVERY.md §5 point 2), reviewed at 894913a

No Fix now: the review is complete.

### R3-1 — GiftCard's 44 px action area is a layout box, not a hit target
- Trigger: a later screen passes a small tappable as `action` → taps in the 44 px box but off the control go to the card or nowhere
- Scores: trigger=theoretical (triager: was plausible — no caller passes a non-Material action yet), impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Reject (D11) — reword the doc comment or make the box a real hit target when the first screen passes a non-Material action
- Override: —
- Outcome: open

### R3-2 — Golden failure images are not gitignored
- Trigger: owner runs a failing `.\goldens.ps1 -Check`, then `git add -A` → diff images are committed
- Scores: trigger=plausible, impact=maintainability, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: a `failures/` directory under `client/test` appears in a commit, a diff under review or staged files, or a delivery step stages with `git add -A`; then add `failures/` to `client/.gitignore`
- Override: —
- Outcome: open

### R3-3 — R2-1's revisit trigger reads as fired
- Trigger: none today — text fields are filled with `surface`, so the 4.04:1 pair is not drawn
- Scores: trigger=theoretical, impact=maintainability, detect=silent, later=cheap, fix=S/local, confidence=verified
- Decision: Reject (D11). Note on R2-1: its `filled: true` clause was checked at 894913a and is not met (the fill is `surface`); R2-1 stays open on its other clauses.
- Override: —
- Outcome: open

## Delivery

Delivered on `feat/first-version`, 2026-11-08. Checks at integration: `flutter
analyze`, `flutter test` (goldens skipped on Windows with their reason),
`.\goldens.ps1 -Check` (22 goldens), `flutter build web --release
--no-web-resources-cdn`, `actionlint`.

| Unit | Goal | Route | Rule | Attempts | Escalated | Verified first time | Findings traced |
|---|---|---|---|---|---|---|---|
| U1 | Tokens, themes and fonts | Sonnet → Opus | — | 2 | X1 → Opus (no static Space Grotesk 600 upstream; plan amended to 500) | yes (a test gap fixed before integration) | R1-1, R1-4, R1-6 |
| U2 | Localisation scaffolding | Opus | S2 | 1 | — | yes | R1-5 |
| U3 | Shared widgets and goldens | Sonnet | — | 1 | — | yes | R3-1 |
| U4 | Golden tooling | Opus | S3 | 2 | — | no (PowerShell array splat bug) | R1-2, R1-3, R3-2 |
| U5 | Skeleton screen restyled, design reference | Opus | S3 | 1 | — | yes | R2-1, R3-3 |

Notes:
- Implementer agents cannot run `pwsh`; they ran `goldens.ps1`'s Docker steps
  from Git Bash, and every verifier ran `.\goldens.ps1 -Check` itself.
- The web build must keep `--no-web-resources-cdn` (Dockerfile): without it
  CanvasKit is fetched from `www.gstatic.com` (U1's report).
