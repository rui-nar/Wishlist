import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../design/tokens.dart';
import '../design/widgets/backdrop.dart';
import '../design/widgets/page_frame.dart';
import '../design/wishlist_colors.dart';
import 'intro_seen.dart';

/// The introduction's location: shown once after sign-in by the router's
/// guard, and from the account screen.
const kIntroPath = '/intro';

/// Three pages on how the app works (NEEDS, Constraints, "Introduction"):
/// lists shared for an occasion, the hidden actions and the hidden gifts.
/// General: nothing about the person's own lists or gifts.
///
/// Swiped, or paged with Back and Next, or the arrow keys. Leaving it, by the
/// top button or the last page's one, marks it [seen] and goes back where it
/// was opened from (the account screen), or home when it was not opened on
/// top of anything: the guard sends a first landing on `/` here. The two
/// buttons are named for where they go: Skip and Get started for home, Close
/// and Done for a way back.
class IntroScreen extends StatefulWidget {
  const IntroScreen({super.key, required this.seen});

  final IntroSeen seen;

  @override
  State<IntroScreen> createState() => _IntroScreenState();
}

class _IntroScreenState extends State<IntroScreen> {
  static const _count = 3;

  final _controller = PageController();
  int _page = 0;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _goTo(int page) {
    if (page < 0 || page >= _count) return;
    _controller.animateToPage(
      page,
      duration: const Duration(milliseconds: 250),
      curve: Curves.easeOut,
    );
  }

  void _leave() {
    unawaited(widget.seen.markSeen());
    context.canPop() ? context.pop() : context.go('/');
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final scheme = Theme.of(context).colorScheme;
    final last = _page == _count - 1;
    final goesBack = context.canPop();
    final pages = [
      _IntroPage(
        icon: Icons.card_giftcard_outlined,
        badge: Icons.share_outlined,
        title: l10n.introYourWishesTitle,
        body: l10n.introYourWishesBody,
      ),
      _IntroPage(
        icon: Icons.visibility_off_outlined,
        badge: Icons.forum_outlined,
        title: l10n.introHiddenActionsTitle,
        body: l10n.introHiddenActionsBody,
      ),
      _IntroPage(
        icon: Icons.volunteer_activism_outlined,
        badge: Icons.lock_outline,
        title: l10n.introHiddenGiftsTitle,
        body: l10n.introHiddenGiftsBody,
      ),
    ];
    return Scaffold(
      body: CallbackShortcuts(
        bindings: {
          const SingleActivator(LogicalKeyboardKey.arrowRight): () =>
              _goTo(_page + 1),
          const SingleActivator(LogicalKeyboardKey.arrowLeft): () =>
              _goTo(_page - 1),
        },
        child: Focus(
          autofocus: true,
          child: PageFrame(
            intensity: BackdropIntensity.bold,
            child: SafeArea(
              child: Column(
                children: [
                  Align(
                    alignment: Alignment.topRight,
                    child: Padding(
                      padding: const EdgeInsets.all(Spacing.s8),
                      // Hidden on the last page, whose own button leaves;
                      // its room is kept, so the page does not move.
                      child: Visibility(
                        visible: !last,
                        maintainSize: true,
                        maintainAnimation: true,
                        maintainState: true,
                        // onSurfaceVariant, not the teal of links: it keeps
                        // 4.5:1 on the motif (WEB_LAYOUT_PLAN D5).
                        child: TextButton(
                          onPressed: _leave,
                          style: TextButton.styleFrom(
                            foregroundColor: scheme.onSurfaceVariant,
                          ),
                          child: Text(
                            goesBack ? l10n.introClose : l10n.introSkip,
                          ),
                        ),
                      ),
                    ),
                  ),
                  Expanded(
                    child: PageView(
                      controller: _controller,
                      onPageChanged: (page) => setState(() => _page = page),
                      children: pages,
                    ),
                  ),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(
                      Spacing.s16,
                      Spacing.s8,
                      Spacing.s16,
                      Spacing.s24,
                    ),
                    child: ConstrainedBox(
                      constraints: const BoxConstraints(
                        maxWidth: ContentWidths.form,
                      ),
                      child: Row(
                        children: [
                          Expanded(
                            child: Align(
                              alignment: Alignment.centerLeft,
                              child: _page == 0
                                  ? const SizedBox.shrink()
                                  // On the surface colour, as on the welcome
                                  // page: the teal label would not keep 4.5:1
                                  // on every motif colour.
                                  : OutlinedButton(
                                      onPressed: () => _goTo(_page - 1),
                                      style: OutlinedButton.styleFrom(
                                        backgroundColor: scheme.surface,
                                      ),
                                      child: Text(l10n.introBack),
                                    ),
                            ),
                          ),
                          _Dots(page: _page, count: _count),
                          Expanded(
                            child: Align(
                              alignment: Alignment.centerRight,
                              child: FilledButton(
                                onPressed: last
                                    ? _leave
                                    : () => _goTo(_page + 1),
                                child: Text(
                                  !last
                                      ? l10n.introNext
                                      : goesBack
                                      ? l10n.introDone
                                      : l10n.introGetStarted,
                                ),
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// One page: the illustration, the title and the text, on a card centred in
/// the page; it scrolls when the window is too short for it.
class _IntroPage extends StatelessWidget {
  const _IntroPage({
    required this.icon,
    required this.badge,
    required this.title,
    required this.body,
  });

  final IconData icon;
  final IconData badge;
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: Spacing.s16),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: ContentWidths.form),
          child: Card(
            child: Padding(
              padding: const EdgeInsets.all(Spacing.s32),
              child: Column(
                children: [
                  _Illustration(icon: icon, badge: badge),
                  const SizedBox(height: Spacing.s32),
                  Semantics(
                    header: true,
                    child: Text(
                      title,
                      style: textTheme.headlineMedium,
                      textAlign: TextAlign.center,
                    ),
                  ),
                  const SizedBox(height: Spacing.s16),
                  Text(
                    body,
                    style: textTheme.bodyLarge?.copyWith(
                      height: 1.5,
                      color: context.wishlistColors.bodyText,
                    ),
                    textAlign: TextAlign.center,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// A large icon on a round teal tile, with a smaller one on its corner.
class _Illustration extends StatelessWidget {
  const _Illustration({required this.icon, required this.badge});

  final IconData icon;
  final IconData badge;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return ExcludeSemantics(
      child: SizedBox.square(
        dimension: 120,
        child: Stack(
          children: [
            Positioned.fill(
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: scheme.primaryContainer,
                  shape: BoxShape.circle,
                ),
                child: Icon(icon, size: 56, color: scheme.onPrimaryContainer),
              ),
            ),
            Positioned(
              right: 0,
              bottom: 0,
              child: DecoratedBox(
                decoration: BoxDecoration(
                  color: scheme.surface,
                  shape: BoxShape.circle,
                  border: Border.all(color: scheme.outline),
                ),
                child: Padding(
                  padding: const EdgeInsets.all(Spacing.s8),
                  child: Icon(badge, size: 24, color: scheme.primary),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Which page is shown, as dots; one label for screen readers.
class _Dots extends StatelessWidget {
  const _Dots({required this.page, required this.count});

  final int page;
  final int count;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      label: AppLocalizations.of(context).introPageOf(page + 1, count),
      child: ExcludeSemantics(
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (var i = 0; i < count; i++)
              AnimatedContainer(
                duration: const Duration(milliseconds: 200),
                margin: const EdgeInsets.symmetric(horizontal: Spacing.s4),
                width: i == page ? Spacing.s24 : Spacing.s8,
                height: Spacing.s8,
                decoration: BoxDecoration(
                  color: i == page ? scheme.primary : scheme.outline,
                  borderRadius: const BorderRadius.all(
                    Radius.circular(Radii.pill),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
