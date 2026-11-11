import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../l10n/app_localizations.dart';
import '../api/api_client.dart';
import '../app_router.dart';
import '../design/tokens.dart';
import '../design/widgets/page_frame.dart';
import '../lists/common.dart';
import 'admin_format.dart';
import 'admin_repository.dart';

/// Wide enough for the users as a table (admin panel plan D10); cards below.
bool adminWide(BuildContext context) =>
    MediaQuery.sizeOf(context).width >= Breakpoints.expanded;

/// `/admin`: every account, newest first, 50 at a time, searchable by
/// address (D5). Opens one account's page. Read only.
class AdminUsersScreen extends StatefulWidget {
  const AdminUsersScreen({super.key});

  @override
  State<AdminUsersScreen> createState() => _AdminUsersScreenState();
}

class _AdminUsersScreenState extends State<AdminUsersScreen>
    with ReloadOnReturn<AdminUsersScreen> {
  late final _repository = AdminRepository.of(context);
  final _search = TextEditingController();

  /// The search the list on screen answers; empty for every account.
  String _query = '';

  /// Null until the first page is read.
  List<AdminUserRow>? _users;
  String? _next;
  Object? _error;
  bool _loadingMore = false;

  /// Bumped by each new first page, so a late answer to an older one, or to
  /// its "show more", is dropped.
  int _generation = 0;

  @override
  void initState() {
    super.initState();
    _fetch();
  }

  @override
  void dispose() {
    _search.dispose();
    super.dispose();
  }

  /// The first page again, the same search: the account on the page closed
  /// may have changed or gone. What is on screen stays until it comes.
  @override
  void reload() => _fetch();

  void _retry() {
    setState(() => _error = null);
    _fetch();
  }

  void _searchFor(String text) {
    final query = text.trim();
    setState(() {
      _query = query;
      _users = null;
      _next = null;
      _error = null;
    });
    _fetch();
  }

  Future<void> _fetch() async {
    final generation = ++_generation;
    try {
      final page = await _repository.users(query: _query);
      if (!mounted || generation != _generation) return;
      setState(() {
        _users = page.users;
        _next = page.nextCursor;
        _error = null;
        _loadingMore = false;
      });
    } catch (error) {
      if (!mounted || generation != _generation) return;
      setState(() => _error = error);
    }
  }

  Future<void> _more() async {
    final cursor = _next;
    if (cursor == null) return;
    final generation = _generation;
    final failed = AppLocalizations.of(context).adminLoadMoreFailed;
    setState(() => _loadingMore = true);
    try {
      final page = await _repository.users(query: _query, cursor: cursor);
      if (!mounted || generation != _generation) return;
      setState(() {
        _users = [...?_users, ...page.users];
        _next = page.nextCursor;
      });
    } catch (error) {
      if (!mounted || generation != _generation) return;
      if (refusalCode(error) == kInvalidCursor) {
        // The cursor no longer reads: start the list again.
        _fetch();
      } else if (error is! UnauthorizedException) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(failed)));
      }
    }
    if (mounted && generation == _generation) {
      setState(() => _loadingMore = false);
    }
  }

  void _open(AdminUserRow user) => context.push(adminUserPath(user.id));

  @override
  Widget build(BuildContext context) {
    // No longer the admin, as far as the server knows: the panel is not there.
    if (isNotFound(_error)) return const NotFoundScreen();
    final l10n = AppLocalizations.of(context);
    final users = _users;
    final wide = adminWide(context);
    final Widget body;
    if (users == null && _error != null) {
      body = LoadFailure(error: _error, onRetry: _retry);
    } else {
      body = ListView(
        padding: PageFrame.paddingOf(
          context,
          wide ? ContentWidths.welcome : ContentWidths.reading,
        ),
        children: [
          _SearchField(
            controller: _search,
            onSearch: _searchFor,
            searching: _query.isNotEmpty,
          ),
          const SizedBox(height: Spacing.s16),
          if (users == null)
            const Center(child: CircularProgressIndicator())
          else if (users.isEmpty)
            Card(
              child: Padding(
                padding: const EdgeInsets.all(Spacing.s24),
                child: Text(
                  _query.isEmpty
                      ? l10n.adminNoUsers
                      : l10n.adminNoMatch(_query),
                  textAlign: TextAlign.center,
                ),
              ),
            )
          else if (wide)
            _UsersTable(users: users, onOpen: _open)
          else
            for (final user in users) ...[
              _UserCard(user: user, onTap: () => _open(user)),
              const SizedBox(height: Spacing.s12),
            ],
          if (users != null && _next != null) ...[
            const SizedBox(height: Spacing.s16),
            Center(
              child: OutlinedButton(
                onPressed: _loadingMore ? null : _more,
                child: Text(l10n.adminShowMore),
              ),
            ),
          ],
        ],
      );
    }
    return Scaffold(
      appBar: AppBar(title: Text(l10n.adminPanel)),
      body: PageFrame(child: SafeArea(child: body)),
    );
  }
}

/// The address search: runs on Enter or the search button, and clears.
class _SearchField extends StatelessWidget {
  const _SearchField({
    required this.controller,
    required this.onSearch,
    required this.searching,
  });

  final TextEditingController controller;
  final ValueChanged<String> onSearch;

  /// A search is applied: the clear button shows.
  final bool searching;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return TextField(
      controller: controller,
      textInputAction: TextInputAction.search,
      keyboardType: TextInputType.emailAddress,
      autocorrect: false,
      onSubmitted: onSearch,
      decoration: InputDecoration(
        hintText: l10n.adminSearchHint,
        prefixIcon: IconButton(
          icon: const Icon(Icons.search),
          tooltip: l10n.adminSearch,
          onPressed: () => onSearch(controller.text),
        ),
        suffixIcon: searching
            ? IconButton(
                icon: const Icon(Icons.close),
                tooltip: l10n.adminClearSearch,
                onPressed: () {
                  controller.clear();
                  onSearch('');
                },
              )
            : null,
      ),
    );
  }
}

/// The widest an address gets in the table: with it, every column fits at
/// the table's full width, Photos included. Narrower windows above the
/// breakpoint scroll sideways.
const _kEmailWidth = 4 * Spacing.s64;

/// The users on a wide screen: one row each, opening the account's page.
class _UsersTable extends StatelessWidget {
  const _UsersTable({required this.users, required this.onOpen});

  final List<AdminUserRow> users;
  final ValueChanged<AdminUserRow> onOpen;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Card(
      clipBehavior: Clip.antiAlias,
      child: LayoutBuilder(
        builder: (context, constraints) => SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: ConstrainedBox(
            constraints: BoxConstraints(minWidth: constraints.maxWidth),
            child: DataTable(
              showCheckboxColumn: false,
              columnSpacing: Spacing.s24,
              // A plan on two lines still shows under a larger text size.
              dataRowMaxHeight: double.infinity,
              columns: [
                DataColumn(label: Text(l10n.adminColumnEmail)),
                DataColumn(label: Text(l10n.adminColumnCreated)),
                DataColumn(label: Text(l10n.adminColumnSignIn)),
                DataColumn(label: Text(l10n.adminColumnPlan)),
                DataColumn(label: Text(l10n.adminColumnLists), numeric: true),
                DataColumn(label: Text(l10n.adminColumnPhotos)),
              ],
              rows: [
                for (final user in users)
                  DataRow(
                    onSelectChanged: (_) => onOpen(user),
                    cells: [
                      // The whole address and the name are on the
                      // account's page.
                      DataCell(ConstrainedBox(
                        constraints:
                            const BoxConstraints(maxWidth: _kEmailWidth),
                        child: Text(
                          user.email,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      )),
                      DataCell(Text(formatDay(context, user.createdAt))),
                      DataCell(Text(
                        signInLine(l10n, user.signIn, compact: true),
                      )),
                      // Clear of the row's lines when it takes three.
                      DataCell(Padding(
                        padding: const EdgeInsets.symmetric(
                          vertical: Spacing.s4,
                        ),
                        child: _PlanLines(user: user),
                      )),
                      DataCell(Text('${user.listsOwned}')),
                      DataCell(Text(photosLine(context, user.photos))),
                    ],
                  ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// The plan, in the table and on a card: the effective plan, then the Stripe
/// subscription and the grant on lines of their own ([planLines]).
class _PlanLines extends StatelessWidget {
  const _PlanLines({required this.user, this.style});

  final AdminUserRow user;
  final TextStyle? style;

  @override
  Widget build(BuildContext context) => Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final line in planLines(context, user)) Text(line, style: style),
        ],
      );
}

/// A user on a phone: the address, the name, and the figures below.
class _UserCard extends StatelessWidget {
  const _UserCard({required this.user, required this.onTap});

  final AdminUserRow user;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    final theme = Theme.of(context);
    final small = theme.textTheme.bodySmall?.copyWith(
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
                      user.email,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: theme.textTheme.titleMedium,
                    ),
                    if (user.displayName.isNotEmpty)
                      Text(user.displayName, style: theme.textTheme.bodyMedium),
                    const SizedBox(height: Spacing.s4),
                    _PlanLines(user: user, style: small),
                    Text(
                      l10n.adminFiguresLine(
                        l10n.adminListsOwned(user.listsOwned),
                        photosLine(context, user.photos),
                      ),
                      style: small,
                    ),
                    Text(
                      l10n.adminFiguresLine(
                        l10n.adminCreated(formatDay(context, user.createdAt)),
                        signInLine(l10n, user.signIn),
                      ),
                      style: small,
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
