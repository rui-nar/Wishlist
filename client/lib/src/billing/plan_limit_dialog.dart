import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../lists/lists_repository.dart';
import 'billing_repository.dart';

/// Says the free plan refused to grow a list (PREMIUM_PLAN D18), and on the
/// web and in the phone apps (Apple IAP plan D8, Android release plan D8)
/// offers the plan page, opened
/// above the screen so that coming back finds it as it was. Done once the dialog is closed, not the plan page.
Future<void> showPlanLimitDialog(
  BuildContext context,
  PlanLimitReached refused,
) async {
  final seePremium = await showDialog<bool>(
    context: context,
    builder: (context) {
      final l10n = AppLocalizations.of(context);
      return AlertDialog(
        title: Text(l10n.planLimitTitle),
        content: Text(switch (refused.resource) {
          PlanLimitResource.lists => l10n.planLimitLists(refused.limit),
          PlanLimitResource.gifts => l10n.planLimitGifts(refused.limit),
        }),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: Text(l10n.planNotNow),
          ),
          if (onTheWeb || appStore != null)
            TextButton(
              onPressed: () => Navigator.of(context).pop(true),
              child: Text(l10n.planSee),
            ),
        ],
      );
    },
  );
  if (seePremium == true && context.mounted) context.push(kPlanPath);
}
