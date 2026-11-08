import 'package:flutter/material.dart';

import 'design/tokens.dart';

/// Why something failed, in the `error` colour behind an error icon. Drawn
/// on `surface` (in a card or a dialog), the pair the contrast test checks.
class ErrorLine extends StatelessWidget {
  const ErrorLine(this.message, {super.key});

  final String message;

  @override
  Widget build(BuildContext context) {
    final error = Theme.of(context).colorScheme.error;
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        // Decorative: the message says it all.
        ExcludeSemantics(
          child: Icon(Icons.error_outline, size: Spacing.s20, color: error),
        ),
        const SizedBox(width: Spacing.s8),
        Expanded(
          child: Text(
            message,
            style: Theme.of(context).textTheme.bodyLarge?.copyWith(
              color: error,
            ),
          ),
        ),
      ],
    );
  }
}
