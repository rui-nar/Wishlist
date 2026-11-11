import 'package:flutter/material.dart';

import '../tokens.dart';
import '../shushgift_colors.dart';

/// Which colours a [StatusChip] wears.
enum StatusChipVariant {
  /// What invitees did: reserved, bought, pledged. Rose, and only for that
  /// (DESIGN_SYSTEM_PLAN D3). The chip shows it when it is given; it never
  /// decides whether the activity may be shown (D7).
  inviteeActivity,

  /// Hidden from someone: teal container.
  hidden,

  /// Anything else: slate container.
  neutral,
}

/// A pill with a label and an optional leading icon.
class StatusChip extends StatelessWidget {
  const StatusChip({
    super.key,
    required this.label,
    this.variant = StatusChipVariant.neutral,
    this.icon,
  });

  final String label;
  final StatusChipVariant variant;
  final IconData? icon;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final colors = context.shushGiftColors;
    final (background, foreground) = switch (variant) {
      StatusChipVariant.inviteeActivity => (
        colors.inviteeActivityContainer,
        colors.onInviteeActivityContainer,
      ),
      StatusChipVariant.hidden => (
        scheme.primaryContainer,
        scheme.onPrimaryContainer,
      ),
      StatusChipVariant.neutral => (
        scheme.secondaryContainer,
        scheme.onSecondaryContainer,
      ),
    };

    return DecoratedBox(
      decoration: BoxDecoration(
        color: background,
        borderRadius: const BorderRadius.all(Radius.circular(Radii.pill)),
      ),
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: Spacing.s8,
          vertical: Spacing.s4,
        ),
        child: Row(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (icon != null) ...[
              Icon(icon, size: TypeSizes.bodyMedium, color: foreground),
              const SizedBox(width: Spacing.s4),
            ],
            Flexible(
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.labelMedium
                    ?.copyWith(color: foreground),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
