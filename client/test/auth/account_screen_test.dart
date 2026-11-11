import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shushgift/src/auth/account_screen.dart';
import 'package:shushgift/src/auth/auth_controller.dart';
import 'package:shushgift/src/auth/sign_in_screen.dart';
import 'package:shushgift/src/billing/billing_repository.dart';
import 'package:shushgift/src/billing/plan_screen.dart';
import 'package:shushgift/src/intro/intro_screen.dart';

import '../billing/support.dart';
import '../support/fakes.dart';

void main() {
  late FakeServer server;
  late MemoryTokenStore store;

  setUp(() {
    server = FakeServer();
    store = MemoryTokenStore(server.addSession());
    installFakeGoogleSignIn();
  });

  Future<AuthController> pumpAccount(WidgetTester tester) async {
    tester.platformDispatcher.defaultRouteNameTestValue = '/account';
    addTearDown(tester.platformDispatcher.clearDefaultRouteNameTestValue);
    final app = buildApp(server, store: store);
    await tester.pumpWidget(app.app);
    await app.auth.restore();
    await tester.pumpAndSettle();
    return app.auth;
  }

  testWidgets('shows the name and email', (tester) async {
    await pumpAccount(tester);

    expect(find.text('Alice Martin'), findsOneWidget);
    expect(find.text('alice@example.com'), findsOneWidget);
  });

  testWidgets('How Shush Gift works opens the introduction and comes back',
      (tester) async {
    await pumpAccount(tester);

    Future<void> openIntro() async {
      await tester.ensureVisible(find.text('How Shush Gift works'));
      await tester.tap(find.text('How Shush Gift works'));
      await tester.pumpAndSettle();
      expect(find.byType(IntroScreen), findsOneWidget);
      expect(find.text('Your wishes, their surprise'), findsOneWidget);
    }

    // Close, from the first page.
    await openIntro();
    expect(find.text('Skip'), findsNothing);
    await tester.tap(find.text('Close'));
    await tester.pumpAndSettle();
    expect(find.byType(IntroScreen), findsNothing);
    expect(find.byType(AccountScreen), findsOneWidget);

    // Done, from the last.
    await openIntro();
    for (var i = 0; i < 2; i++) {
      await tester.tap(find.text('Next'));
      await tester.pumpAndSettle();
    }
    expect(find.text('Get started'), findsNothing);
    await tester.tap(find.text('Done'));
    await tester.pumpAndSettle();
    expect(find.byType(IntroScreen), findsNothing);
    expect(find.byType(AccountScreen), findsOneWidget);
  });

  testWidgets('delete asks for confirmation; cancel deletes nothing',
      (tester) async {
    final auth = await pumpAccount(tester);

    await tester.tap(find.text('Delete account'));
    await tester.pumpAndSettle();

    expect(find.text('Delete your account?'), findsOneWidget);
    expect(
      find.text(
        'Your account and the lists you own, with their gifts and '
        'occasions, are deleted. Everyone you shared them with loses '
        'access, and you are signed out on every device. This cannot be '
        'undone.',
      ),
      findsOneWidget,
    );
    expect(server.calls, isNot(contains('DELETE /api/me')));

    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();

    expect(find.text('Delete your account?'), findsNothing);
    expect(server.calls, isNot(contains('DELETE /api/me')));
    expect(auth.isSignedIn, isTrue);
    expect(find.byType(AccountScreen), findsOneWidget);
  });

  group('an Apple subscription at deletion (Apple IAP plan D9)', () {
    const renewing = 'Your App Store subscription keeps renewing: deleting '
        'your account does not cancel it. Cancel it in your Apple '
        'subscriptions first.';
    const unknown = 'If you subscribed on iPhone, deleting your account does '
        'not cancel that subscription: cancel it in your Apple '
        'subscriptions.';
    const link = 'Open Apple subscriptions';

    for (final web in [true, false]) {
      testWidgets('renewing: warned, with the way to Apple '
          '(${web ? 'web' : 'Android'})', (tester) async {
        debugOnTheWeb = web;
        addTearDown(() => debugOnTheWeb = null);
        final launcher = installRecordingUrlLauncher();
        await pumpAccount(tester);
        // Bought after the screen opened: read again at deletion.
        server.billing = billingStatus(appleRenewing: true);

        await tester.tap(find.text('Delete account'));
        await tester.pumpAndSettle();

        expect(find.text(renewing), findsOneWidget);
        expect(find.text(unknown), findsNothing);
        await tester.tap(find.text(link));
        await tester.pumpAndSettle();
        expect(launcher.launched.single.url, kAppleSubscriptionsUrl);

        // The deletion still goes ahead (guideline 5.1.1(v)).
        await tester.tap(find.text('Delete'));
        await tester.pumpAndSettle();
        expect(server.deleted, isTrue);
      });
    }

    testWidgets('none renewing: no warning', (tester) async {
      server.billing = billingStatus(
        plan: 'premium',
        source: 'apple',
        status: 'canceling',
        endsAt: '2027-03-12T12:00:00Z',
        limits: null,
      );
      await pumpAccount(tester);

      await tester.tap(find.text('Delete account'));
      await tester.pumpAndSettle();

      expect(find.text('Delete your account?'), findsOneWidget);
      expect(find.text(renewing), findsNothing);
      expect(find.text(unknown), findsNothing);
      expect(find.text(link), findsNothing);
    });

    testWidgets('the plan cannot be read: the warning, as a condition',
        (tester) async {
      await pumpAccount(tester);
      server.status['GET /api/billing'] = 500;

      await tester.tap(find.text('Delete account'));
      await tester.pumpAndSettle();

      expect(find.text(unknown), findsOneWidget);
      expect(find.text(link), findsOneWidget);
    });

    testWidgets('in French', (tester) async {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
      server.billing = billingStatus(appleRenewing: true);
      await pumpAccount(tester);

      await tester.tap(find.text('Supprimer le compte'));
      await tester.pumpAndSettle();

      expect(
        find.text('Votre abonnement App Store continue de se renouveler : '
            'supprimer votre compte ne le résilie pas. Résiliez-le '
            "d'abord dans vos abonnements Apple."),
        findsOneWidget,
      );
      expect(find.text('Ouvrir les abonnements Apple'), findsOneWidget);
    });
  });

  group('a Google subscription at deletion (Android release plan D6)', () {
    const cancelled = 'Your Google Play subscription will be cancelled along '
        'with your account.';

    for (final web in [true, false]) {
      testWidgets('renewing: says the deletion cancels it '
          '(${web ? 'web' : 'Android'})', (tester) async {
        debugOnTheWeb = web;
        addTearDown(() => debugOnTheWeb = null);
        await pumpAccount(tester);
        // Bought after the screen opened: read again at deletion.
        server.billing = billingStatus(googleRenewing: true);

        await tester.tap(find.text('Delete account'));
        await tester.pumpAndSettle();

        expect(find.text(cancelled), findsOneWidget);
        // Nothing to do at Google: no warning to cancel, no link.
        expect(find.textContaining('Cancel it'), findsNothing);
        expect(find.text('Open Apple subscriptions'), findsNothing);

        await tester.tap(find.text('Delete'));
        await tester.pumpAndSettle();
        expect(server.deleted, isTrue);
      });
    }

    testWidgets('beside a renewing Apple one: both said', (tester) async {
      server.billing = billingStatus(appleRenewing: true, googleRenewing: true);
      await pumpAccount(tester);

      await tester.tap(find.text('Delete account'));
      await tester.pumpAndSettle();

      expect(find.text(cancelled), findsOneWidget);
      expect(find.textContaining('App Store subscription'), findsOneWidget);
    });

    testWidgets('none renewing, or the plan unread: nothing said of Google',
        (tester) async {
      await pumpAccount(tester);
      server.status['GET /api/billing'] = 500;

      await tester.tap(find.text('Delete account'));
      await tester.pumpAndSettle();

      expect(find.text(cancelled), findsNothing);
    });

    testWidgets('in French', (tester) async {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
      server.billing = billingStatus(googleRenewing: true);
      await pumpAccount(tester);

      await tester.tap(find.text('Supprimer le compte'));
      await tester.pumpAndSettle();

      expect(
        find.text('Votre abonnement Google Play sera résilié avec votre '
            'compte.'),
        findsOneWidget,
      );
    });
  });

  testWidgets('the confirmation is in French on a French device',
      (tester) async {
    tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
    addTearDown(tester.platformDispatcher.clearLocalesTestValue);
    await pumpAccount(tester);

    await tester.tap(find.text('Supprimer le compte'));
    await tester.pumpAndSettle();

    expect(find.text('Supprimer votre compte ?'), findsOneWidget);
    expect(
      find.text(
        "Votre compte et les listes que vous possédez, avec leurs cadeaux et "
        "leurs occasions, sont supprimés. Les personnes avec qui vous les "
        "avez partagées n'y ont plus accès, et vous êtes déconnecté sur tous "
        "vos appareils. Cette action est définitive.",
      ),
      findsOneWidget,
    );
  });

  testWidgets('confirming deletes the account and signs out', (tester) async {
    final auth = await pumpAccount(tester);

    await tester.tap(find.text('Delete account'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();

    expect(server.deleted, isTrue);
    expect(auth.status, AuthStatus.signedOut);
    expect(store.token, isNull);
    expect(find.byType(SignInScreen), findsOneWidget);
  });

  testWidgets('a failed deletion says so and stays signed in',
      (tester) async {
    server.status['DELETE /api/me'] = 500;
    final auth = await pumpAccount(tester);

    await tester.tap(find.text('Delete account'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Delete'));
    await tester.pumpAndSettle();

    expect(find.text('Your account could not be deleted. Try again.'),
        findsOneWidget);
    expect(auth.isSignedIn, isTrue);
    expect(find.byType(AccountScreen), findsOneWidget);
  });

  group('email notifications (COMMENTS_NOTIFICATIONS D20)', () {
    SwitchListTile emailSwitch(WidgetTester tester) =>
        tester.widget(find.byType(SwitchListTile));

    testWidgets('the switch reads the server', (tester) async {
      server.preferences['email_notifications'] = false;
      await pumpAccount(tester);

      expect(server.calls, contains('GET /api/me/preferences'));
      expect(find.text('Email notifications'), findsOneWidget);
      expect(emailSwitch(tester).value, isFalse);
    });

    testWidgets('turning it off writes the server', (tester) async {
      await pumpAccount(tester);
      expect(emailSwitch(tester).value, isTrue);
      final patches = server.preferencePatches.length;

      await tester.tap(find.byType(SwitchListTile));
      await tester.pumpAndSettle();

      expect(server.preferencePatches.sublist(patches), [
        {'email_notifications': false},
      ]);
      expect(server.preferences['email_notifications'], isFalse);
      expect(emailSwitch(tester).value, isFalse);
    });

    testWidgets('a failed change says so and the switch goes back',
        (tester) async {
      await pumpAccount(tester);
      server.status['PATCH /api/me/preferences'] = 500;

      await tester.tap(find.byType(SwitchListTile));
      await tester.pumpAndSettle();

      expect(
        find.text(
          'Your email notifications setting could not be changed. Try again.',
        ),
        findsOneWidget,
      );
      expect(emailSwitch(tester).value, isTrue);
      expect(emailSwitch(tester).onChanged, isNotNull);
    });

    testWidgets('a failed read says so and the switch stays disabled',
        (tester) async {
      server.status['GET /api/me/preferences'] = 500;
      await pumpAccount(tester);

      expect(
        find.text(
          'Your email notifications setting could not be loaded. '
          'Try again later.',
        ),
        findsOneWidget,
      );
      expect(emailSwitch(tester).value, isFalse);
      expect(emailSwitch(tester).onChanged, isNull);
    });

    testWidgets('in French on a French device', (tester) async {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
      await pumpAccount(tester);

      expect(find.text('Notifications par e-mail'), findsOneWidget);
    });
  });

  group('plan (PREMIUM D18)', () {
    const failed = 'That did not work. Try again in a moment.';
    const renews = 'Renews on March 12, 2027';

    Map<String, Object?> premium({
      String status = 'active',
      String? renewsAt = '2027-03-12T12:00:00Z',
      String? endsAt,
      bool canManage = true,
    }) =>
        billingStatus(
          plan: 'premium',
          status: status,
          renewsAt: renewsAt,
          endsAt: endsAt,
          limits: const {'max_lists': null, 'max_gifts_per_list': null},
          canManage: canManage,
        );

    setUp(() {
      debugOnTheWeb = true;
      addTearDown(() => debugOnTheWeb = null);
    });

    testWidgets('free, no offer, not enforced: nothing', (tester) async {
      await pumpAccount(tester);

      expect(server.calls, contains('GET /api/billing'));
      expect(find.text('Your plan'), findsNothing);
      expect(find.text('Free plan'), findsNothing);
      expect(find.text('Terms of service'), findsNothing);
    });

    testWidgets('free, no offer, not enforced: nothing either on mobile',
        (tester) async {
      debugOnTheWeb = false;
      await pumpAccount(tester);

      expect(find.text('Your plan'), findsNothing);
    });

    testWidgets('a failed read leaves the screen as it is, with no error',
        (tester) async {
      server.status['GET /api/billing'] = 500;
      await pumpAccount(tester);

      expect(find.text('Your plan'), findsNothing);
      expect(find.byType(SnackBar), findsNothing);
      expect(find.text('Could not load your plan.'), findsNothing);
      expect(find.text('Alice Martin'), findsOneWidget);
    });

    testWidgets('free with an offer: the way to Premium and the legal links',
        (tester) async {
      server.billing = billingStatus(offer: kBillingOffer);
      await pumpAccount(tester);

      expect(find.text('Your plan'), findsOneWidget);
      expect(find.text('Free plan'), findsOneWidget);
      expect(find.text('See Premium'), findsOneWidget);
      expect(find.text('Manage subscription'), findsNothing);
      expect(find.text('Terms of service'), findsOneWidget);
      expect(find.text('Privacy'), findsOneWidget);
      expect(find.text('Right of withdrawal'), findsOneWidget);
    });

    testWidgets('free and enforced with no offer: the plan alone',
        (tester) async {
      server.billing = billingStatus(enforced: true);
      await pumpAccount(tester);

      expect(find.text('Free plan'), findsOneWidget);
      expect(find.text('See Premium'), findsNothing);
    });

    testWidgets('See Premium goes to the plan page, and back reads again',
        (tester) async {
      server.billing = billingStatus(offer: kBillingOffer);
      await pumpAccount(tester);

      await tester.tap(find.text('See Premium'));
      await tester.pumpAndSettle();
      expect(find.byType(PlanScreen), findsOneWidget);

      server.billing = premium();
      await tester.tap(find.byType(BackButton));
      await tester.pumpAndSettle();

      expect(find.byType(AccountScreen), findsOneWidget);
      expect(find.text('Premium'), findsOneWidget);
      expect(find.text('See Premium'), findsNothing);
    });

    testWidgets('premium, active: the renewal date and Manage', (tester) async {
      server.billing = premium();
      await pumpAccount(tester);

      expect(find.text('Premium'), findsOneWidget);
      expect(find.text(renews), findsOneWidget);
      expect(find.text('Manage subscription'), findsOneWidget);
      expect(find.text('See Premium'), findsNothing);
      expect(find.textContaining('bought on the website'), findsNothing);
    });

    testWidgets('premium, canceling: the end date', (tester) async {
      server.billing = premium(
        status: 'canceling',
        renewsAt: null,
        endsAt: '2027-03-12T12:00:00Z',
      );
      await pumpAccount(tester);

      expect(find.text('Premium'), findsOneWidget);
      expect(find.text('Ends on March 12, 2027'), findsOneWidget);
      expect(find.text(renews), findsNothing);
      expect(find.text('Manage subscription'), findsOneWidget);
    });

    testWidgets('premium, past due: the failed-payment line, not a renewal',
        (tester) async {
      server.billing = premium(status: 'past_due');
      await pumpAccount(tester);

      expect(find.text('Premium'), findsOneWidget);
      expect(
        find.text(
          'Your last payment failed. Update your card to keep Premium.',
        ),
        findsOneWidget,
      );
      expect(find.text(renews), findsNothing);
      expect(find.text('Manage subscription'), findsOneWidget);
    });

    testWidgets('premium that cannot be managed has no Manage', (tester) async {
      server.billing = premium(canManage: false);
      await pumpAccount(tester);

      expect(find.text('Premium'), findsOneWidget);
      expect(find.text('Manage subscription'), findsNothing);
    });

    testWidgets('Manage opens the portal in the same tab', (tester) async {
      final launcher = installRecordingUrlLauncher();
      server.billing = premium();
      await pumpAccount(tester);

      await tester.tap(find.text('Manage subscription'));
      await tester.pumpAndSettle();

      expect(launcher.launched.single.url, server.portalUrl);
      expect(launcher.launched.single.options.webOnlyWindowName, '_self');
    });

    testWidgets('Manage refused: says so and the status is read again',
        (tester) async {
      server.billing = premium();
      await pumpAccount(tester);
      server.status['POST /api/billing/portal'] = 409;
      server.billing = premium(canManage: false);

      await tester.tap(find.text('Manage subscription'));
      await tester.pumpAndSettle();

      expect(find.text(failed), findsOneWidget);
      expect(find.text('Manage subscription'), findsNothing);
    });

    testWidgets('Manage failing at Stripe says so', (tester) async {
      server.billing = premium();
      await pumpAccount(tester);
      server.status['POST /api/billing/portal'] = 502;

      await tester.tap(find.text('Manage subscription'));
      await tester.pumpAndSettle();

      expect(find.text(failed), findsOneWidget);
    });

    testWidgets('on mobile: the plan and its limits, nothing to buy or open',
        (tester) async {
      debugOnTheWeb = false;
      server.billing = billingStatus(offer: kBillingOffer, canManage: true);
      await pumpAccount(tester);

      expect(find.text('Free plan'), findsOneWidget);
      expect(find.text('Free: 1 list, up to 20 gifts per list'), findsOneWidget);
      expect(find.text('See Premium'), findsNothing);
      expect(find.text('Manage subscription'), findsNothing);
      expect(find.text('Terms of service'), findsNothing);
      expect(find.textContaining('49'), findsNothing);
    });

    testWidgets('on mobile, a past-due subscriber still sees the line',
        (tester) async {
      debugOnTheWeb = false;
      server.billing = premium(status: 'past_due');
      await pumpAccount(tester);

      expect(find.text('Premium'), findsOneWidget);
      expect(
        find.text(
          'Your last payment failed. Update your card to keep Premium.',
        ),
        findsOneWidget,
      );
      expect(find.text('Manage subscription'), findsNothing);
      expect(
        find.text(
          'Your Premium was bought on the website and is managed there.',
        ),
        findsOneWidget,
      );
    });

    testWidgets('in French on a French device', (tester) async {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
      server.billing = billingStatus(offer: kBillingOffer);
      await pumpAccount(tester);

      expect(find.text('Votre formule'), findsOneWidget);
      expect(find.text('Formule gratuite'), findsOneWidget);
      expect(find.text('Découvrir Premium'), findsOneWidget);
      expect(find.text('Droit de rétractation'), findsOneWidget);
    });

    testWidgets('the renewal date is in French on a French device',
        (tester) async {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
      server.billing = premium();
      await pumpAccount(tester);

      expect(find.text('Renouvellement le 12 mars 2027'), findsOneWidget);
    });
  });

  testWidgets('sign out clears the store and shows sign-in', (tester) async {
    await pumpAccount(tester);

    await tester.tap(find.text('Sign out'));
    await tester.pumpAndSettle();

    expect(store.token, isNull);
    expect(server.sessions, isEmpty);
    expect(find.byType(SignInScreen), findsOneWidget);
  });
}
