import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../design/tokens.dart';
import '../lists/common.dart';
import 'shared_repository.dart';

/// The occasions the user joined, each opening its read-only view
/// (LISTS_GIFTS_SHARING_PLAN D11). The app bar's button opens the account
/// screen.
class SharedWithMeScreen extends StatefulWidget {
  const SharedWithMeScreen({super.key, this.bottomNavigationBar});

  /// Home's navigation bar.
  final Widget? bottomNavigationBar;

  @override
  State<SharedWithMeScreen> createState() => _SharedWithMeScreenState();
}

class _SharedWithMeScreenState extends State<SharedWithMeScreen>
    with ReloadOnReturn<SharedWithMeScreen> {
  late final _repository = SharedRepository.of(context);
  late Future<List<SharedOccasion>> _occasions;

  @override
  void initState() {
    super.initState();
    _occasions = _repository.shared();
  }

  @override
  void reload() {
    setState(() {
      _occasions = _repository.shared();
    });
  }

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Scaffold(
      appBar: AppBar(
        title: Text(l10n.sharedWithMeTitle),
        actions: [
          IconButton(
            icon: const Icon(Icons.account_circle_outlined),
            tooltip: l10n.accountTitle,
            onPressed: () => context.push('/account'),
          ),
        ],
      ),
      bottomNavigationBar: widget.bottomNavigationBar,
      body: SafeArea(
        child: FutureBuilder<List<SharedOccasion>>(
          future: _occasions,
          builder: (context, snapshot) {
            if (snapshot.hasError) {
              return LoadFailure(error: snapshot.error, onRetry: reload);
            }
            final occasions = snapshot.data;
            if (occasions == null) {
              return const Center(child: CircularProgressIndicator());
            }
            if (occasions.isEmpty) return const _Empty();
            return ListView(
              padding: const EdgeInsets.all(Spacing.s16),
              children: [
                for (final (index, occasion) in occasions.indexed) ...[
                  if (index > 0) const SizedBox(height: Spacing.s12),
                  _OccasionCard(
                    occasion: occasion,
                    onTap: () => context.push('/shared/${occasion.id}'),
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
  const _Empty();

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
                  Icons.group_outlined,
                  size: Spacing.s48,
                  color: Theme.of(context).colorScheme.primary,
                ),
              ),
              const SizedBox(height: Spacing.s16),
              Text(
                l10n.sharedWithMeEmpty,
                textAlign: TextAlign.center,
                style: Theme.of(context).textTheme.bodyLarge,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// An occasion: its name, date and list, who it is for and who shared it.
class _OccasionCard extends StatelessWidget {
  const _OccasionCard({required this.occasion, required this.onTap});

  final SharedOccasion occasion;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final metadata = theme.textTheme.bodySmall?.copyWith(
      color: theme.colorScheme.onSurfaceVariant,
    );
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
                      occasion.name,
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleMedium,
                    ),
                    const SizedBox(height: Spacing.s4),
                    Text(
                      l10n.sharedOccasionLine(
                        formatOccasionDate(context, occasion.date),
                        occasion.listTitle,
                      ),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: metadata,
                    ),
                    Text(
                      l10n.sharedForBy(
                        personName(l10n, occasion.recipientName),
                        peopleNames(l10n, occasion.ownerNames),
                      ),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                      style: metadata,
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
