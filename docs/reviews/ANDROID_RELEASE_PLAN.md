# Review ledger — Android release

Subject: docs/plans/ANDROID_RELEASE_PLAN.md
Envelope: the plan's `## Review envelope`, with APPLE_IAP_PLAN's, IOS_APP_PLAN's and REVIEW.md defaults

Decisions approved as triaged, floors enforced, under the owner's standing
instruction of 2026-11-11. Envelope questions answered with the
recommendation: a Google subscription is cancelled before deletion like
Stripe's; VAL refuses purchases not flagged as test purchases; an out-of-app
resubscription is resolved through its expired token's stored row.

## Round 1 — 2026-11-11, reviewed at the plan's first draft (uncommitted)

### R1-1 — A Play Store resubscription carries no account id
- Trigger: an expired subscriber resubscribes in Play → no account resolved → charged, Free, then refunded.
- Scores: trigger=concrete (corrected from plausible), impact=silent-wrong, detect=logged, later=cheap, fix=M/local, confidence=inferred
- Decision: Fix now (D3)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D6, Account)

### R1-2 — Google's selling state does not require the notification settings
- Trigger: the owner sets the product but not the Pub/Sub settings → every push refused, renewals and refunds unrecorded.
- Scores: trigger=plausible, impact=silent-wrong, detect=silent, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D3)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D6, Selling on Android)

### R1-3 — Only the client's report acknowledges a purchase
- Trigger: the app dies before posting → the notification records Premium, nothing acknowledges → Google refunds on day 3.
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible (corrected from logged), later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: the Play Console shows an order refunded for not being acknowledged, or the client does not re-post unacknowledged purchases at launch
- Guard: —
- Override: —
- Outcome: open

### R1-4 — A voided notification ends the row without a re-read
- Trigger: a refund without revoking → the row ends while Play still renews → deletion escapes cancelling, or Restore brings Premium back.
- Scores: trigger=plausible, impact=silent-wrong, detect=silent, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D3)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D6, Notifications)

### R1-5 — Purchase tokens may not fit `external_id`
- Trigger: a token over 255 characters → the insert fails, nothing recorded → refund.
- Scores: trigger=plausible, impact=wrong-visible, detect=logged, later=expensive, fix=S/shared, confidence=inferred
- Decision: Fix now (D5)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D6, Storage; Boundaries: one migration)

### R1-6 — The first Play upload must be manual
- Trigger: the owner pushes the validation tag first → the API refuses an app with no manual upload.
- Scores: trigger=concrete, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Fix now (D7)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (plan D4, U5)

## Round 2 — 2026-11-11, unit review of U3, reviewed at 65bf7c4

The orchestrator signed off one deviation of U3: `external_id` is each
purchase's current token, and a replacing token ends the old row (Google reads,
acknowledges and cancels by the current token only). Plan D6 updated.

### R2-1 — A purchase recorded by a notification alone is never acknowledged
- Trigger: an expired subscriber resubscribes in the Play Store and does not open the app for 3 days → Google refunds, Premium disappears after a charge.
- Scores: trigger=concrete (corrected from plausible), impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Fix now (D6)
- Revisit when: —
- Guard: —
- Override: —
- Outcome: fixed (8f25feb)

### R2-2 — A Google subscription renewed after its account was deleted is not cancelled
- Trigger: a subscriber cancels, deletes the account, then resubscribes the running subscription in Play → "of no known account", Google keeps renewing.
- Scores: trigger=plausible, impact=wrong-visible, detect=logged, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: PROD logs "google: purchase … of no known account" for a purchase that can still charge, a deleted-account user asks for a Google refund, or the owner states D15 must hold after a renewal the person restarted
- Guard: —
- Override: —
- Outcome: open

### R2-3 — A cancel answered 400 refuses the deletion
- Trigger: a pending-payment purchase reads as chargeable and Google's cancel answers 400 → 502 on every retry.
- Scores: trigger=plausible, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: PROD logs "google: cancel: not found (HTTP 4xx)" during a deletion, or a user reports a deletion that keeps failing
- Guard: —
- Override: —
- Outcome: open

## Round 3 — 2026-11-11, integrated review, reviewed at 061c9cc

### R3-1 — The runbook's "deletion refused" section does not cover Google
- Trigger: a Google gateway misconfigured while an account has a renewing Google row → 409; the section's SQL does not unblock it, and BILLING.md says 409 where the code answers 502.
- Scores: trigger=plausible, impact=degraded-ux, detect=user-visible, later=cheap, fix=S/local, confidence=verified
- Decision: Defer (D10)
- Revisit when: a server refuses a deletion for an account with a Google row, GOOGLE_* variables are unset on a server holding Google rows, or the owner opens that section for a Google refusal
- Guard: —
- Override: —
- Outcome: open

### R3-2 — A purchase refused for a configuration error is set aside on the phone
- Trigger: a wrong package or product id on a selling server → the token is set aside; after the fix it is never re-posted, and Google refunds.
- Scores: trigger=plausible, impact=wrong-visible, detect=user-visible, later=cheap, fix=S/local, confidence=inferred
- Decision: Defer (D10)
- Revisit when: a selling server logs unknown_purchase or other_product for a Google purchase, a Play order is refunded for non-acknowledgement after a configuration change, or the package or product id changes on a selling server
- Guard: —
- Override: —
- Outcome: open

### R3-3 — Duplicate of APPLE_IAP_PLAN IAP-R3-2
- Decision: Duplicate (D2)
- Outcome: fixed with IAP-R3-2

## Delivery

Delivered under the owner's standing instruction of 2026-11-11, with the two
iOS plans on one branch.

| Unit | Goal | Route | Rule | Attempts | Escalated | Verified first time | Findings traced |
|---|---|---|---|---|---|---|---|
| U1 | The Android project: flavours, signing, name, icon | Opus | S5 | 1 | — | yes | — |
| U2 | CI: the Android build and internal-track release | Opus | S5 | 1 | — | yes (the Android CI build) | R1-6 |
| U3 | Server: the Google translator, routes, cancelling at deletion | Opus | S4 | 1 (+ review fix) | — | yes | R1-1–R1-5, R2-1–R2-3 |
| U4 | Client: buying on Android | Opus | S5 | 1 | X3: pubspec, main.dart | yes | R3-2, R3-3 |
| U5 | Runbook | Sonnet | — | 1 | — | yes | R3-1 |

U3 deviates from D6 as signed off by the orchestrator: `external_id` is the
current purchase token. U2 keeps the signed bundle as an artefact only when
Play refuses the upload (the repository is public).
