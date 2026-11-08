import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../lists/my_lists_screen.dart';
import '../shared/shared_with_me_screen.dart';

/// The two destinations of the navigation bar.
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
/// (LISTS_GIFTS_SHARING_PLAN D11).
class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key, this.destination = HomeDestination.myLists});

  final HomeDestination destination;

  @override
  Widget build(BuildContext context) {
    // The bar is in each destination's own scaffold: one scaffold per page,
    // so a message shows once.
    final bar = _HomeNavigationBar(selected: destination);
    return switch (destination) {
      HomeDestination.myLists => MyListsScreen(bottomNavigationBar: bar),
      HomeDestination.sharedWithMe =>
        SharedWithMeScreen(bottomNavigationBar: bar),
    };
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
