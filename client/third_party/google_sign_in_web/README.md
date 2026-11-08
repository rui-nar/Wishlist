# google_sign_in_web 1.1.3, patched

A copy of [`google_sign_in_web` 1.1.3](https://pub.dev/packages/google_sign_in_web/versions/1.1.3)
(BSD-3-Clause, see `LICENSE`), wired in through `dependency_overrides` in
`client/pubspec.yaml`. It comes from TraxJourney, which wrote the patch
(TraxJourney #611); Wishlist takes it as it is (`docs/plans/ACCOUNTS_PLAN.md`
D11).

## The patch

Upstream's `GoogleSignInPlugin` constructor starts loading
`https://accounts.google.com/gsi/client`. The constructor runs from the web
plugin registrant, before `main()`, so every page of the web app would fetch
Google's script, share links included, whether or not the visitor signs in.

Here the load starts in `init()` instead, and the app calls
`GoogleSignIn.instance.initialize()` only from the sign-in screen
(`client/lib/src/auth/google_sign_in_init.dart`). Every other plugin API
already waits for `init()`, so nothing else changes. The code comments still
say "TraxJourney patch": that is where it was written.

In TraxJourney's history the patch is the second commit that touched this
folder, after the verbatim upstream copy. Here the first commit is a verbatim
copy of TraxJourney's patched folder; the later ones change only Wishlist
files: this README, `analysis_options.yaml` (the client's lints do not apply
to upstream's code) and `.gitignore` (what a test run writes here). To see the
patch itself, diff this folder against upstream 1.1.3.

Reported upstream as flutter/flutter#194640.

## Upgrading

Drop this folder and the `dependency_overrides` entry once an upstream release
loads the SDK in `init()`. Until then, to take a new upstream version: copy it
here in one commit, re-apply the patch in the next, and run
`flutter test --platform chrome` in this folder.
