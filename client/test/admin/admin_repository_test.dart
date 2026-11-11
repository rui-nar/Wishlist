import 'package:flutter_test/flutter_test.dart';
import 'package:wishlist/src/admin/admin_repository.dart';
import 'package:wishlist/src/api/api_client.dart';

import '../support/fakes.dart';
import 'support/fake_admin.dart';

void main() {
  late FakeServer server;
  late FakeAdmin admin;
  late AdminRepository repository;

  setUp(() {
    server = FakeServer();
    admin = FakeAdmin(server);
    final api = ApiClient(server.client, baseUrl: kApiBase)
      ..token = server.addSession();
    repository = AdminRepository(api);
  });

  test('reads a page: rows, plan, counts and photo figures', () async {
    final page = await repository.users();

    expect(page.nextCursor, isNull);
    expect(page.users.map((user) => user.email), [
      'bob@example.com',
      'carol@example.com',
      'alice@example.com',
    ]);
    final bob = page.users.first;
    expect(bob.displayName, 'Bob Durand');
    expect(bob.signIn, ['apple', 'email']);
    expect(bob.plan.isPremium, isTrue);
    expect(bob.plan.source, 'stripe');
    expect(bob.plan.until, DateTime.utc(2027, 3, 12, 12));
    expect(bob.listsOwned, 2);
    expect(bob.photos.count, 3);
    expect(bob.photos.bytes, 1500000);
    expect(bob.photos.measuring, isFalse);
    expect(page.users[1].photos.measuring, isTrue);
  });

  test('a row carries the Stripe subscription and the grant, apart',
      () async {
    admin.rows.first['subscription'] = stripeSubscription('past_due');
    admin.grants[kBobId] = '2027-06-01T12:00:00Z';
    final page = await repository.users();

    final bob = page.users.first;
    expect(bob.subscription?.status, 'past_due');
    expect(bob.subscription?.startedAt, DateTime.utc(2026, 5, 2, 10, 5));
    expect(bob.subscription?.periodEnd, DateTime.utc(2027, 3, 12, 12));
    expect(bob.manualGrantEnd, DateTime.utc(2027, 6, 1, 12));
    // Never subscribed, nothing granted.
    final carol = page.users[1];
    expect(carol.subscription, isNull);
    expect(carol.manualGrantEnd, isNull);
  });

  test('a subscription without its dates still reads', () async {
    admin.rows.first['subscription'] =
        stripeSubscription('ended', startedAt: null, periodEnd: null);
    final bob = (await repository.users()).users.first;

    expect(bob.subscription?.status, 'ended');
    expect(bob.subscription?.startedAt, isNull);
    expect(bob.subscription?.periodEnd, isNull);
  });

  test('sends the search and the cursor, and nothing when empty', () async {
    admin.pageSize = 1;
    final first = await repository.users(query: 'example');
    await repository.users(query: 'example', cursor: first.nextCursor);
    await repository.users(query: '');

    expect(admin.queries, [
      {'q': 'example'},
      {'q': 'example', 'cursor': '1'},
      <String, String>{},
    ]);
  });

  test('one account: its lists and the grant', () async {
    admin.grants[kBobId] = '2027-01-10T12:00:00Z';
    final detail = await repository.user(kBobId);

    expect(detail.user.email, 'bob@example.com');
    expect(detail.lists.map((list) => list.title), ['Birthday', 'Wedding']);
    expect(detail.lists.last.giftCount, 12);
    expect(detail.lists.last.ownerCount, 2);
    expect(detail.user.manualGrantEnd, DateTime.utc(2027, 1, 10, 12));
    expect(detail.user.subscription?.status, 'active');
  });

  test('a grant sends its calendar day', () async {
    final detail = await repository.grantPremium(kCarolId, DateTime(2027, 2, 3));

    expect(admin.bodies['POST /api/admin/users/$kCarolId/premium'], [
      {'period_end': '2027-02-03'},
    ]);
    expect(detail.user.plan.source, 'manual');
  });

  test('ending a grant reads the account again', () async {
    admin.grants[kCarolId] = '2027-01-10T12:00:00Z';
    final detail = await repository.endPremium(kCarolId);

    expect(server.calls.sublist(server.calls.length - 2), [
      'DELETE /api/admin/users/$kCarolId/premium',
      'GET /api/admin/users/$kCarolId',
    ]);
    expect(detail.user.manualGrantEnd, isNull);
  });

  test('a deletion sends the address typed', () async {
    await repository.deleteUser(kBobId, 'bob@example.com');

    expect(admin.bodies['DELETE /api/admin/users/$kBobId'], [
      {'email': 'bob@example.com'},
    ]);
  });

  test('refusals keep their code; reauth_required has its own error',
      () async {
    await expectLater(
      repository.deleteUser(kBobId, 'someone@else.test'),
      throwsA(predicate((error) => refusalCode(error) == kEmailMismatch)),
    );
    admin.reauth = true;
    await expectLater(
      repository.grantPremium(kBobId, DateTime(2027, 2, 3)),
      throwsA(isA<ReauthRequiredException>()),
    );
    expect(refusalCode(const UnauthorizedException()), isNull);
  });
}
