import 'package:flutter/material.dart';

import '../tokens.dart';

/// A gift in a list: image, title, metadata, chips and an action.
///
/// Takes display values, never a gift model (DESIGN_SYSTEM_PLAN D7): the
/// caller decides what a role may see, the card shows what it is given.
class GiftCard extends StatelessWidget {
  const GiftCard({
    super.key,
    required this.title,
    this.metadata,
    this.image,
    this.chips = const [],
    this.action,
    this.onTap,
  });

  final String title;

  /// One line under the title (price, shop...).
  final String? metadata;

  /// Shown at 64 px; a gift icon on `primaryContainer` stands in when null.
  final ImageProvider? image;

  /// Usually [StatusChip]s.
  final List<Widget> chips;

  /// Trailing control. Gets a hit area of at least 44 px.
  final Widget? action;

  /// Makes the whole card tappable.
  final VoidCallback? onTap;

  static const double _imageSize = 64;
  static const double _padding = 14;
  static const double _minHitArea = 44;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;

    final content = Padding(
      padding: const EdgeInsets.all(_padding),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          ClipRRect(
            borderRadius: const BorderRadius.all(Radius.circular(Radii.md)),
            child: SizedBox.square(
              dimension: _imageSize,
              child: image != null
                  ? Image(image: image!, fit: BoxFit.cover)
                  : ColoredBox(
                      color: scheme.primaryContainer,
                      child: ExcludeSemantics(
                        child: Icon(
                          Icons.card_giftcard_outlined,
                          color: scheme.onPrimaryContainer,
                        ),
                      ),
                    ),
            ),
          ),
          const SizedBox(width: Spacing.s12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: theme.textTheme.titleMedium?.copyWith(
                    color: scheme.onSurface,
                  ),
                ),
                if (metadata != null)
                  Text(
                    metadata!,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: scheme.onSurfaceVariant,
                    ),
                  ),
                if (chips.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: Spacing.s8),
                    child: Wrap(
                      spacing: Spacing.s4,
                      runSpacing: Spacing.s4,
                      children: chips,
                    ),
                  ),
              ],
            ),
          ),
          if (action != null) ...[
            const SizedBox(width: Spacing.s8),
            ConstrainedBox(
              key: const ValueKey('gift-card-action'),
              constraints: const BoxConstraints(
                minWidth: _minHitArea,
                minHeight: _minHitArea,
              ),
              child: Center(child: action),
            ),
          ],
        ],
      ),
    );

    return Card(
      clipBehavior: Clip.antiAlias,
      child: onTap == null ? content : InkWell(onTap: onTap, child: content),
    );
  }
}
