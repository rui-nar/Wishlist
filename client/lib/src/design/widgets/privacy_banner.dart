import 'package:flutter/material.dart';

import '../tokens.dart';

/// A teal container with an eye-off icon and a message, for telling someone
/// what is hidden from them. The caller gives the message (a localised
/// string); the banner never decides when it is shown (DESIGN_SYSTEM_PLAN D7).
class PrivacyBanner extends StatelessWidget {
  const PrivacyBanner({super.key, required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    return DecoratedBox(
      decoration: BoxDecoration(
        color: scheme.primaryContainer,
        borderRadius: const BorderRadius.all(Radius.circular(Radii.lg)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(Spacing.s12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // Decorative: the message says it all.
            ExcludeSemantics(
              child: Icon(
                Icons.visibility_off_outlined,
                size: Spacing.s20,
                color: scheme.onPrimaryContainer,
              ),
            ),
            const SizedBox(width: Spacing.s12),
            Expanded(
              child: Text(
                message,
                style: Theme.of(context).textTheme.bodyMedium
                    ?.copyWith(color: scheme.onPrimaryContainer),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
