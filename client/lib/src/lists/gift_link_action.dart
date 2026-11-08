import 'package:flutter/material.dart';

import '../../l10n/app_localizations.dart';
import 'gift_links.dart';

/// The smallest hit area of a control (DESIGN_SYSTEM_PLAN D6).
const double _minHitArea = 44;

/// A gift card's action: a button opening the gift's link, or a menu of them
/// when there are several. Each is itself at least 44 px, on every platform:
/// desktop densities shrink icon buttons below that (DESIGN_SYSTEM_PLAN
/// review R3-1). Null when the gift has no link.
Widget? giftLinkAction(List<String> links) =>
    links.isEmpty ? null : GiftLinkAction(links: links);

class GiftLinkAction extends StatelessWidget {
  const GiftLinkAction({super.key, required this.links});

  /// At least one.
  final List<String> links;

  Future<void> _open(BuildContext context, String link) async {
    final messenger = ScaffoldMessenger.of(context);
    final failed = AppLocalizations.of(context).linkOpenFailed;
    if (!await openGiftLink(link)) {
      messenger.showSnackBar(SnackBar(content: Text(failed)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final style = IconButton.styleFrom(
      minimumSize: const Size.square(_minHitArea),
    );
    if (links.length == 1) {
      return IconButton(
        style: style,
        icon: const Icon(Icons.open_in_new),
        tooltip: l10n.openLink,
        onPressed: () => _open(context, links.single),
      );
    }
    return PopupMenuButton<String>(
      style: style,
      icon: const Icon(Icons.open_in_new),
      tooltip: l10n.openLinks,
      onSelected: (link) => _open(context, link),
      itemBuilder: (context) => [
        for (final link in links)
          PopupMenuItem(
            value: link,
            child: Text(link, maxLines: 1, overflow: TextOverflow.ellipsis),
          ),
      ],
    );
  }
}
