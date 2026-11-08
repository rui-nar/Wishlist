import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../design/tokens.dart';
import '../lists/my_lists_screen.dart';
import '../shared/shared_with_me_screen.dart';

/// The two destinations of home's navigation.
enum HomeDestination {
  /// `/`
  myLists('/'),

  /// `/shared`
  sharedWithMe('/shared');

  const HomeDestination(this.location);

  final String location;
}

/// Home: the user's lists (`/`) and the occasions shared with them
/// (`/shared`), with a navigation bar between the two
/// (LISTS_GIFTS_SHARING_PLAN D11), or a navigation rail on its left from
/// [Breakpoints.expanded] (WEB_LAYOUT_PLAN D3).
class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key, this.destination = HomeDestination.myLists});

  final HomeDestination destination;

  @override
  Widget build(BuildContext context) {
    final expanded =
        MediaQuery.sizeOf(context).width >= Breakpoints.expanded;
    // The bar is in each destination's own scaffold: one scaffold per page,
    // so a message shows once. The rail is beside it, so the destination's
    // app bar spans the rest of the window.
    final bar = expanded ? null : _HomeNavigationBar(selected: destination);
    // The same tree in every window class, the rail only added in front, so
    // crossing the breakpoint keeps the destination's state: its lists are
    // not fetched again and its scroll position stays.
    return Row(
      children: [
        if (expanded) _HomeNavigationRail(selected: destination),
        Expanded(
          key: const ValueKey('destination'),
          child: switch (destination) {
            HomeDestination.myLists =>
              MyListsScreen(bottomNavigationBar: bar),
            HomeDestination.sharedWithMe =>
              SharedWithMeScreen(bottomNavigationBar: bar),
          },
        ),
      ],
    );
  }
}

class _HomeNavigationBar extends StatelessWidget {
  const _HomeNavigationBar({required this.selected});

  final HomeDestination selected;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return NavigationBar(
      selectedIndex: selected.index,
      onDestinationSelected: (index) =>
          context.go(HomeDestination.values[index].location),
      destinations: [
        NavigationDestination(
          icon: const Icon(Icons.list_alt_outlined),
          selectedIcon: const Icon(Icons.list_alt),
          label: l10n.myListsTitle,
        ),
        NavigationDestination(
          icon: const Icon(Icons.group_outlined),
          selectedIcon: const Icon(Icons.group),
          label: l10n.sharedWithMeTitle,
        ),
      ],
    );
  }
}

/// The navigation bar's destinations, as a rail.
class _HomeNavigationRail extends StatelessWidget {
  const _HomeNavigationRail({required this.selected});

  final HomeDestination selected;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return NavigationRail(
      selectedIndex: selected.index,
      onDestinationSelected: (index) =>
          context.go(HomeDestination.values[index].location),
      labelType: NavigationRailLabelType.all,
      destinations: [
        NavigationRailDestination(
          icon: const Icon(Icons.list_alt_outlined),
          selectedIcon: const Icon(Icons.list_alt),
          label: Text(l10n.myListsTitle),
        ),
        NavigationRailDestination(
          icon: const Icon(Icons.group_outlined),
          selectedIcon: const Icon(Icons.group),
          label: Text(l10n.sharedWithMeTitle),
        ),
      ],
    );
  }
}
