import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:image_picker_platform_interface/image_picker_platform_interface.dart';
import 'package:provider/provider.dart';
import 'package:shushgift/src/api/api_client.dart';
import 'package:shushgift/src/api/api_image.dart';
import 'package:shushgift/src/lists/gift_form_screen.dart';
import 'package:shushgift/src/lists/gift_image_section.dart';
import 'package:shushgift/src/lists/list_detail_screen.dart';
import 'package:shushgift/src/lists/lists_repository.dart';

import '../support/fakes.dart';
import 'support/fake_lists_server.dart';

/// The gift form's image section (GIFT_IMAGES D14): through the whole app
/// for what the form saves, and on its own, with its picker and clipboard
/// injected, for each way in and each refusal.
void main() {
  late FakeListsServer server;
  late String listId;

  setUp(() {
    server = FakeListsServer();
    listId = server.addList('Birthday');
  });

  /// The path the preview shows, or null when it shows the placeholder.
  String? previewPath(WidgetTester tester) {
    final preview = find.byKey(const ValueKey('gift-image-preview'));
    if (preview.evaluate().isEmpty) return null;
    return (tester.widget<Image>(preview).image as ApiImage).path;
  }

  Future<void> tapText(WidgetTester tester, String text) async {
    await tester.ensureVisible(find.text(text));
    await tester.pumpAndSettle();
    await tester.tap(find.text(text));
    await tester.pumpAndSettle();
  }

  /// Gives [url] in the Image URL dialog and confirms it.
  Future<void> giveUrl(WidgetTester tester, String url) async {
    await tapText(tester, 'Image URL');
    await tester.enterText(fieldLabelled('Image address'), url);
    await tester.tap(find.text('Use this image'));
    await tester.pumpAndSettle();
  }

  Future<void> save(WidgetTester tester, String label) async {
    final button = find.widgetWithText(FilledButton, label);
    await tester.ensureVisible(button);
    await tester.pumpAndSettle();
    await tester.tap(button);
    await tester.pumpAndSettle();
  }

  bool saveEnabled(WidgetTester tester, String label) =>
      tester.widget<FilledButton>(find.widgetWithText(FilledButton, label))
          .onPressed !=
      null;

  group('in the form', () {
    testWidgets('adding a gift with a chosen image is one create request '
        'with its id', (tester) async {
      final picker = installFakeImagePicker(kTestImage);
      await startApp(tester, server, '/lists/$listId/gifts/new');

      expect(previewPath(tester), isNull);
      expect(find.text('Remove image'), findsNothing);

      await tapText(tester, 'Choose image');

      // D5: re-encoded and resized by the picker, from the gallery.
      final (source, options) = picker.requests.single;
      expect(source, ImageSource.gallery);
      expect(options.maxWidth, 2048);
      expect(options.maxHeight, 2048);
      expect(options.imageQuality, 90);
      // No photo library permission on iOS; the server drops it anyway.
      expect(options.requestFullMetadata, isFalse);
      expect(server.uploads.single, kTestImage);
      final id = server.images.keys.single;
      expect(previewPath(tester), '/api/images/$id/full');
      expect(find.text('Remove image'), findsOneWidget);

      await tester.enterText(fieldLabelled('What is it?'), 'Headphones');
      await save(tester, 'Add a gift');

      expect(
        server.calls.where((call) => !call.startsWith('GET ')),
        ['POST /api/images', 'POST /api/lists/$listId/gifts'],
      );
      expect(server.bodies['POST /api/lists/$listId/gifts']!['image_id'], id);
      expect(find.byType(ListDetailScreen), findsOneWidget);
    });

    testWidgets('an image from a URL: the address is checked, sent, and the '
        'preview is the answer', (tester) async {
      await startApp(tester, server, '/lists/$listId/gifts/new');

      await giveUrl(tester, 'ftp://shop.example/h.png');
      expect(
        find.text('Enter a web address starting with http:// or https://'),
        findsOneWidget,
      );
      expect(server.calls, isNot(contains('POST /api/images/from-url')));

      await tester.enterText(
        fieldLabelled('Image address'),
        ' https://shop.example/h.png ',
      );
      await tester.tap(find.text('Use this image'));
      await tester.pumpAndSettle();

      expect(server.bodies['POST /api/images/from-url'], {
        'url': 'https://shop.example/h.png',
      });
      final id = server.images.keys.single;
      expect(previewPath(tester), '/api/images/$id/full');
    });

    testWidgets('cancelling the URL dialog sends nothing', (tester) async {
      await startApp(tester, server, '/lists/$listId/gifts/new');

      await tapText(tester, 'Image URL');
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();

      expect(server.calls, isNot(contains('POST /api/images/from-url')));
      expect(previewPath(tester), isNull);
    });

    testWidgets('Save waits while an image is being sent', (tester) async {
      installFakeImagePicker(kTestImage);
      await startApp(tester, server, '/lists/$listId/gifts/new');
      await tester.enterText(fieldLabelled('What is it?'), 'Headphones');

      server.hold = Completer();
      await tester.tap(find.text('Choose image'));
      await tester.pump();
      await tester.pump();

      expect(find.bySemanticsLabel('Adding the image...'), findsOneWidget);
      expect(saveEnabled(tester, 'Add a gift'), isFalse);

      server.hold!.complete();
      server.hold = null;
      await tester.pumpAndSettle();

      expect(saveEnabled(tester, 'Add a gift'), isTrue);
      expect(previewPath(tester), isNotNull);
    });

    testWidgets('a cancelled pick sends nothing and says nothing', (
      tester,
    ) async {
      installFakeImagePicker();
      await startApp(tester, server, '/lists/$listId/gifts/new');

      await tapText(tester, 'Choose image');

      expect(server.calls, isNot(contains('POST /api/images')));
      expect(previewPath(tester), isNull);
    });

    group('editing a gift with an image', () {
      late String giftId;
      late String imageId;

      setUp(() {
        giftId = server.addGift(listId, 'Headphones', image: true);
        imageId = server.images.keys.single;
      });

      String editLocation() => '/lists/$listId/gifts/$giftId/edit';
      String patch() => 'PATCH /api/gifts/$giftId';

      testWidgets('shows it, and saving untouched sends no image_id', (
        tester,
      ) async {
        await startApp(tester, server, editLocation());

        expect(previewPath(tester), '/api/images/$imageId/full');

        await save(tester, 'Save');

        expect(server.bodies[patch()], isNot(contains('image_id')));
        expect(server.gift(giftId)!['image']['id'], imageId);
      });

      testWidgets('Remove then Save sends null', (tester) async {
        await startApp(tester, server, editLocation());

        await tapText(tester, 'Remove image');

        expect(previewPath(tester), isNull);
        expect(find.text('Remove image'), findsNothing);

        await save(tester, 'Save');

        expect(server.bodies[patch()], containsPair('image_id', null));
        expect(server.gift(giftId)!['image'], isNull);
      });

      testWidgets('replacing it sends the new id', (tester) async {
        installFakeImagePicker(kTestImage);
        await startApp(tester, server, editLocation());

        await tapText(tester, 'Choose image');
        final replacement = server.images.keys.last;
        expect(replacement, isNot(imageId));
        expect(previewPath(tester), '/api/images/$replacement/full');

        await save(tester, 'Save');

        expect(server.bodies[patch()]!['image_id'], replacement);
      });

      testWidgets('an image added, then removed, removes the old one too', (
        tester,
      ) async {
        installFakeImagePicker(kTestImage);
        await startApp(tester, server, editLocation());

        await tapText(tester, 'Choose image');
        await tapText(tester, 'Remove image');
        await save(tester, 'Save');

        expect(server.bodies[patch()], containsPair('image_id', null));
      });
    });

    testWidgets('adding an image then removing it before the first save '
        'sends no image_id', (tester) async {
      installFakeImagePicker(kTestImage);
      await startApp(tester, server, '/lists/$listId/gifts/new');

      await tapText(tester, 'Choose image');
      await tapText(tester, 'Remove image');
      await tester.enterText(fieldLabelled('What is it?'), 'Headphones');
      await save(tester, 'Add a gift');

      expect(
        server.bodies['POST /api/lists/$listId/gifts'],
        isNot(contains('image_id')),
      );
    });

    for (final (code, message) in [
      ('image_not_attachable', 'This image can no longer be used. Add it again.'),
      ('image_expired', 'This image was added too long ago. Add it again.'),
    ]) {
      testWidgets('a save refused with $code says so', (tester) async {
        installFakeImagePicker(kTestImage);
        final add = 'POST /api/lists/$listId/gifts';
        server.status[add] = 422;
        server.details[add] = code;
        await startApp(tester, server, '/lists/$listId/gifts/new');

        await tapText(tester, 'Choose image');
        await tester.enterText(fieldLabelled('What is it?'), 'Headphones');
        await save(tester, 'Add a gift');

        expect(find.text(message), findsOneWidget);
        expect(find.byType(GiftFormScreen), findsOneWidget);
      });
    }
  });

  group('the section on its own', () {
    late List<ImageChange> changes;

    setUp(() => changes = []);

    Future<void> pumpSection(
      WidgetTester tester, {
      ImageBytesSource? pick,
      ImageBytesSource? clipboard,
      GiftImage? initial,
    }) async {
      final api = ApiClient(server.client, baseUrl: kApiBase)
        ..token = server.accounts.addSession();
      await tester.pumpWidget(
        Provider<ApiClient>.value(
          value: api,
          child: localizedApp(
            Scaffold(
              body: SingleChildScrollView(
                child: GiftImageSection(
                  initial: initial,
                  onChanged: changes.add,
                  pickImage: pick ?? () async => kTestImage,
                  readClipboard: clipboard ?? () async => null,
                ),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
    }

    testWidgets('Paste image sends the clipboard\'s image', (tester) async {
      final pasted = Uint8List.fromList([...kTestImage]);
      await pumpSection(tester, clipboard: () async => pasted);

      await tapText(tester, 'Paste image');

      expect(server.uploads.single, pasted);
      final id = server.images.keys.single;
      expect(previewPath(tester), '/api/images/$id/full');
      expect(changes.single, isA<AttachImage>().having((c) => c.id, 'id', id));
    });

    testWidgets('an empty clipboard says so and sends nothing', (tester) async {
      await pumpSection(tester);

      await tapText(tester, 'Paste image');

      expect(find.text('No image in the clipboard.'), findsOneWidget);
      expect(server.calls, isEmpty);
      expect(changes, isEmpty);
    });

    testWidgets('a clipboard that cannot be read says it holds no image', (
      tester,
    ) async {
      await pumpSection(
        tester,
        clipboard: () async => throw Exception('no clipboard'),
      );

      await tapText(tester, 'Paste image');

      expect(find.text('No image in the clipboard.'), findsOneWidget);
      expect(server.calls, isEmpty);
    });

    testWidgets('a pick that cannot be read says so', (tester) async {
      await pumpSection(tester, pick: () async => throw Exception('denied'));

      await tapText(tester, 'Choose image');

      expect(
        find.text('This image could not be read. Try another one.'),
        findsOneWidget,
      );
      expect(server.calls, isEmpty);
    });

    testWidgets('an 11 MB pick is refused without a request', (tester) async {
      await pumpSection(
        tester,
        pick: () async => Uint8List(11 * 1024 * 1024),
      );

      await tapText(tester, 'Choose image');

      expect(
        find.text('This image is too large: the limit is 10 MB.'),
        findsOneWidget,
      );
      expect(server.calls, isEmpty);
    });

    testWidgets('exactly 10 MB is sent', (tester) async {
      await pumpSection(tester, pick: () async => Uint8List(kImageMaxBytes));

      await tapText(tester, 'Choose image');

      expect(server.uploads.single.length, 10 * 1024 * 1024);
    });

    for (final (code, status, message) in [
      ('image_too_large', 413, 'This image is too large: the limit is 10 MB.'),
      (
        'image_too_many_pixels',
        422,
        'This image has too many pixels. Try a smaller one.',
      ),
      (
        'image_unsupported',
        422,
        "This kind of image can't be used. Try a JPEG, PNG, WebP or GIF.",
      ),
      (
        'image_busy',
        503,
        'The server is busy with other images. Try again in a moment.',
      ),
    ]) {
      testWidgets('an upload refused with $code says so', (tester) async {
        server.status['POST /api/images'] = status;
        server.details['POST /api/images'] = code;
        await pumpSection(tester);

        await tapText(tester, 'Choose image');

        expect(find.text(message), findsOneWidget);
        expect(previewPath(tester), isNull);
        expect(changes, isEmpty);
      });
    }

    testWidgets('a 413 without a code (a proxy\'s) is a file too large', (
      tester,
    ) async {
      server.status['POST /api/images'] = 413;
      await pumpSection(tester);

      await tapText(tester, 'Choose image');

      expect(
        find.text('This image is too large: the limit is 10 MB.'),
        findsOneWidget,
      );
    });

    testWidgets('another failure is the usual server error', (tester) async {
      server.status['POST /api/images'] = 500;
      await pumpSection(tester);

      await tapText(tester, 'Choose image');

      expect(
        find.text('The server could not complete the request. Try again.'),
        findsOneWidget,
      );
    });

    for (final (code, message) in [
      ('url_not_allowed', "This address can't be used."),
      (
        'url_fetch_failed',
        'The image could not be downloaded from this address.',
      ),
      ('image_busy', 'The server is busy with other images. Try again in a moment.'),
    ]) {
      testWidgets('an image URL refused with $code says so', (tester) async {
        server.status['POST /api/images/from-url'] = 422;
        server.details['POST /api/images/from-url'] = code;
        await pumpSection(tester);

        await giveUrl(tester, 'http://127.0.0.1/a.png');

        expect(find.text(message), findsOneWidget);
        expect(previewPath(tester), isNull);
      });
    }

    testWidgets('the next attempt clears the last error', (tester) async {
      await pumpSection(tester);
      await tapText(tester, 'Paste image');
      expect(find.text('No image in the clipboard.'), findsOneWidget);

      await tapText(tester, 'Choose image');

      expect(find.text('No image in the clipboard.'), findsNothing);
      expect(previewPath(tester), isNotNull);
    });

    testWidgets('the paste handler sends the first pasted image', (
      tester,
    ) async {
      await pumpSection(tester);
      final state = tester.state<GiftImageSectionState>(
        find.byType(GiftImageSection),
      );
      final pasted = Uint8List.fromList([...kTestImage]);
      var textRead = false;

      final took = state.handlePaste([
        PastedFile(
          type: 'text/plain',
          read: () async {
            textRead = true;
            return Uint8List(0);
          },
        ),
        PastedFile(type: 'image/png', read: () async => pasted),
        PastedFile(type: 'image/jpeg', read: () async => Uint8List(1)),
      ]);
      await tester.pumpAndSettle();

      expect(took, isTrue);
      expect(textRead, isFalse);
      expect(server.uploads.single, pasted);
      expect(previewPath(tester), '/api/images/${server.images.keys.single}/full');
    });

    testWidgets('the paste handler leaves a paste without an image alone', (
      tester,
    ) async {
      await pumpSection(tester);
      final state = tester.state<GiftImageSectionState>(
        find.byType(GiftImageSection),
      );

      final took = state.handlePaste([
        PastedFile(type: 'text/plain', read: () async => Uint8List(0)),
      ]);
      await tester.pumpAndSettle();

      expect(took, isFalse);
      expect(server.calls, isEmpty);
    });

    testWidgets('the paste handler ignores a paste while the URL dialog is '
        'open', (tester) async {
      await pumpSection(tester);
      final state = tester.state<GiftImageSectionState>(
        find.byType(GiftImageSection),
      );
      await tapText(tester, 'Image URL');

      final took = state.handlePaste([
        PastedFile(type: 'image/png', read: () async => kTestImage),
      ]);
      await tester.pumpAndSettle();

      expect(took, isFalse);
      expect(server.calls, isEmpty);
    });

    testWidgets('in French', (tester) async {
      tester.platformDispatcher.localesTestValue = const [Locale('fr', 'FR')];
      addTearDown(tester.platformDispatcher.clearLocalesTestValue);
      server.status['POST /api/images/from-url'] = 422;
      server.details['POST /api/images/from-url'] = 'url_not_allowed';
      await pumpSection(
        tester,
        initial: const GiftImage(
          id: 'i',
          width: 8,
          height: 8,
          url: '/api/images/i/full',
          thumbUrl: '/api/images/i/thumb',
        ),
      );

      expect(find.text('Image'), findsOneWidget);
      expect(find.text('Choisir une image'), findsOneWidget);
      expect(find.text("URL d'une image"), findsOneWidget);
      expect(find.text('Coller une image'), findsOneWidget);
      expect(find.text("Retirer l'image"), findsOneWidget);

      await tapText(tester, 'Coller une image');
      expect(find.text('Aucune image dans le presse-papiers.'), findsOneWidget);

      await tapText(tester, "URL d'une image");
      expect(find.text('Image depuis le web'), findsOneWidget);
      await tester.enterText(fieldLabelled("Adresse de l'image"), 'pas un lien');
      await tester.tap(find.text('Utiliser cette image'));
      await tester.pumpAndSettle();
      expect(
        find.text('Saisissez une adresse web commençant par http:// ou https://'),
        findsOneWidget,
      );
      await tester.enterText(
        fieldLabelled("Adresse de l'image"),
        'http://127.0.0.1/a.png',
      );
      await tester.tap(find.text('Utiliser cette image'));
      await tester.pumpAndSettle();
      expect(
        find.text('Cette adresse ne peut pas être utilisée.'),
        findsOneWidget,
      );

      await tapText(tester, "Retirer l'image");
      expect(changes.single, isA<RemoveImage>());
    });
  });
}
