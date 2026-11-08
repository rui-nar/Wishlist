import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../design/tokens.dart';
import 'common.dart';
import 'lists_repository.dart';

/// The lists the user owns, each opening its detail, and the button creating
/// one (LISTS_GIFTS_SHARING_PLAN D11). The app bar's button opens the
/// account screen.
class MyListsScreen extends StatefulWidget {
  const MyListsScreen({super.key});

  @override
  State<MyListsScreen> createState() => _MyListsScreenState();
}

class _MyListsScreenState extends State<MyListsScreen>
    with ReloadOnReturn<MyListsScreen> {
  late final _repository = ListsRepository.of(context);
  late Future<List<ListSummary>> _lists;

  @override
  void initState() {
    super.initState();
    _lists = _repository.myLists();
  }

  @override
  void reload() {
    setState(() {
      _lists = _repository.myLists();
    });
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.myListsTitle),
        actions: [
          IconButton(
            icon: const Icon(Icons.account_circle_outlined),
            tooltip: l10n.accountTitle,
            onPressed: () => context.push('/account'),
          ),
        ],
      ),
      body: SafeArea(
        child: FutureBuilder<List<ListSummary>>(
          future: _lists,
          builder: (context, snapshot) {
            if (snapshot.hasError) {
              return LoadFailure(error: snapshot.error, onRetry: reload);
            }
            final lists = snapshot.data;
            if (lists == null) {
              return const Center(child: CircularProgressIndicator());
            }
            final newList = FilledButton.icon(
              onPressed: () => context.push('/lists/new'),
              icon: const Icon(Icons.add),
              label: Text(l10n.newList),
            );
            if (lists.isEmpty) return _Empty(button: newList);
            return ListView(
              padding: const EdgeInsets.all(Spacing.s16),
              children: [
                Align(alignment: Alignment.centerLeft, child: newList),
                for (final list in lists) ...[
                  const SizedBox(height: Spacing.s12),
                  _ListCard(
                    list: list,
                    onTap: () => context.push('/lists/${list.id}'),
                  ),
                ],
              ],
            );
          },
        ),
      ),
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty({required this.button});

  final Widget button;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return SingleChildScrollView(
      padding: const EdgeInsets.all(Spacing.s16),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(Spacing.s24),
          child: Column(
            children: [
              ExcludeSemantics(
                child: Icon(
                  Icons.card_giftcard_outlined,
                  size: Spacing.s48,
                  color: Theme.of(context).colorScheme.primary,
                ),
              ),
              const SizedBox(height: Spacing.s16),
              Text(
                l10n.myListsEmpty,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyLarge,
              ),
              const SizedBox(height: Spacing.s24),
              button,
            ],
          ),
        ),
      ),
    );
  }
}

/// A list: its title, who it is for and how many gifts it holds.
class _ListCard extends StatelessWidget {
  const _ListCard({required this.list, required this.onTap});

  final ListSummary list;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(Spacing.s16),
          child: Row(
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      list.title,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleMedium,
                    ),
                    const SizedBox(height: Spacing.s4),
                    Text(
                      l10n.listCardLine(
                        recipientLine(
                          l10n,
                          list.recipientKind,
                          list.recipientName,
                        ),
                        l10n.listGiftCount(list.giftCount),
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.bodySmall?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              ExcludeSemantics(
                child: Icon(
                  Icons.chevron_right,
                  color: theme.colorScheme.onSurfaceVariant,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
