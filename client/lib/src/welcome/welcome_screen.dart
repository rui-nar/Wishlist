import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../app_router.dart';
import '../design/tokens.dart';
import '../design/widgets/backdrop.dart';
import '../design/widgets/page_frame.dart';
import '../design/shushgift_colors.dart';

/// What a signed-out visitor at `/` sees (WEB_LAYOUT_PLAN D6, D8): the app's
/// name, a headline, its purpose and the Register and Log in buttons, three
/// cards on what it does, and a footer linking to the version screen. On the
/// bold backdrop, with no app bar.
///
/// Expanded windows put the hero and the cards side by side, narrower ones
/// stack them. Text drawn straight on the backdrop uses the colours D5 keeps
/// readable on the motif; the links among it do too.
class WelcomeScreen extends StatelessWidget {
  const WelcomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final expanded = MediaQuery.sizeOf(context).width >= Breakpoints.expanded;
    final padding = PageFrame.paddingOf(context, ContentWidths.welcome);
    const features = _Features();
    return Scaffold(
      body: PageFrame(
        intensity: BackdropIntensity.bold,
        child: SafeArea(
          child: LayoutBuilder(
            builder: (context, constraints) => SingleChildScrollView(
              padding: padding,
              // At least the window's height, so the content sits in the
              // middle and the footer at the bottom when everything fits.
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  minHeight:
                      math.max(0, constraints.maxHeight - padding.vertical),
                ),
                child: Column(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const SizedBox.shrink(),
                    if (expanded)
                      Row(
                        children: [
                          Expanded(flex: 6, child: _Hero(expanded: expanded)),
                          const SizedBox(width: Spacing.s64),
                          Expanded(flex: 5, child: features),
                        ],
                      )
                    else
                      Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          _Hero(expanded: expanded),
                          const SizedBox(height: Spacing.s40),
                          features,
                        ],
                      ),
                    const Padding(
                      padding: EdgeInsets.only(top: Spacing.s40),
                      child: _Footer(),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// The app's name, the headline, the purpose and the two buttons.
class _Hero extends StatelessWidget {
  const _Hero({required this.expanded});

  final bool expanded;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final textTheme = theme.textTheme;
    final scheme = theme.colorScheme;
    final headline = expanded ? textTheme.displayMedium : textTheme.displaySmall;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const _IconTile(Icons.card_giftcard_outlined),
            const SizedBox(width: Spacing.s12),
            Text(l10n.appTitle, style: textTheme.titleLarge),
          ],
        ),
        SizedBox(height: expanded ? Spacing.s48 : Spacing.s32),
        Semantics(
          header: true,
          child: Text(
            l10n.welcomeHeadline,
            style: headline?.copyWith(
              fontWeight: FontWeight.w700,
              color: scheme.onSurface,
            ),
          ),
        ),
        const SizedBox(height: Spacing.s16),
        // The lead paragraph: the app bar title's size, in the body font.
        Text(
          l10n.welcomePurpose,
          style: textTheme.titleLarge?.copyWith(
            fontFamily: FontFamilies.text,
            fontWeight: FontWeight.w400,
            height: 1.5,
            color: context.shushGiftColors.bodyText,
          ),
        ),
        const SizedBox(height: Spacing.s32),
        Wrap(
          spacing: Spacing.s12,
          runSpacing: Spacing.s12,
          children: [
            FilledButton.icon(
              onPressed: () => context.go(
                Uri(
                  path: kSignInPath,
                  queryParameters: {'mode': kRegisterMode},
                ).toString(),
              ),
              icon: const Icon(Icons.person_add_alt_outlined),
              label: Text(l10n.welcomeRegister),
            ),
            // On the surface colour: the teal label would not keep 4.5:1
            // on every motif colour.
            OutlinedButton.icon(
              onPressed: () => context.go(kSignInPath),
              style: OutlinedButton.styleFrom(backgroundColor: scheme.surface),
              icon: const Icon(Icons.login),
              label: Text(l10n.welcomeLogIn),
            ),
          ],
        ),
      ],
    );
  }
}

/// The three cards on what the app does.
class _Features extends StatelessWidget {
  const _Features();

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        _FeatureCard(
          icon: Icons.list_alt_outlined,
          title: l10n.welcomeListsTitle,
          body: l10n.welcomeListsBody,
        ),
        const SizedBox(height: Spacing.s16),
        _FeatureCard(
          icon: Icons.celebration_outlined,
          title: l10n.welcomeOccasionsTitle,
          body: l10n.welcomeOccasionsBody,
        ),
        const SizedBox(height: Spacing.s16),
        _FeatureCard(
          icon: Icons.visibility_off_outlined,
          title: l10n.welcomeSurpriseTitle,
          body: l10n.welcomeSurpriseBody,
        ),
      ],
    );
  }
}

class _FeatureCard extends StatelessWidget {
  const _FeatureCard({
    required this.icon,
    required this.title,
    required this.body,
  });

  final IconData icon;
  final String title;
  final String body;

  @override
  Widget build(BuildContext context) {
    final textTheme = Theme.of(context).textTheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(Spacing.s20),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _IconTile(icon),
            const SizedBox(width: Spacing.s16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(title, style: textTheme.titleMedium),
                  const SizedBox(height: Spacing.s4),
                  Text(body, style: textTheme.bodyMedium),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// An icon on a rounded teal tile.
class _IconTile extends StatelessWidget {
  const _IconTile(this.icon);

  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return DecoratedBox(
      decoration: BoxDecoration(
        color: scheme.primaryContainer,
        borderRadius: const BorderRadius.all(Radius.circular(Radii.md)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(Spacing.s8),
        child: Icon(icon, color: scheme.onPrimaryContainer),
      ),
    );
  }
}

/// The app's name and the link to the version screen.
class _Footer extends StatelessWidget {
  const _Footer();

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    // onSurfaceVariant, not the teal of links: it keeps 4.5:1 on the motif
    // (D5), and the footer sits over the bottom-left shapes.
    final muted = theme.colorScheme.onSurfaceVariant;
    return Row(
      mainAxisAlignment: MainAxisAlignment.spaceBetween,
      children: [
        Text(l10n.appTitle, style: theme.textTheme.bodySmall),
        TextButton.icon(
          onPressed: () => context.push(kAboutPath),
          style: TextButton.styleFrom(foregroundColor: muted),
          icon: const Icon(Icons.info_outline),
          label: Text(l10n.aboutApp),
        ),
      ],
    );
  }
}
