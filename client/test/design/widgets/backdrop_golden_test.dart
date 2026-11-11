@Tags(['golden'])
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shushgift/src/design/theme.dart';
import 'package:shushgift/src/design/tokens.dart';
import 'package:shushgift/src/design/widgets/backdrop.dart';
import 'package:shushgift/src/design/widgets/page_frame.dart';

// Goldens render on Linux only (DESIGN_SYSTEM_PLAN D10): .\goldens.ps1
// regenerates them there.
final Object _skip = Platform.isLinux
    ? false
    : r'goldens render on Linux only: run .\goldens.ps1';

void main() {
  final themes = {'light': buildLightTheme(), 'dark': buildDarkTheme()};
  const sizes = [Size(390, 844), Size(1440, 900)];

  group('goldens', skip: _skip, () {
    for (final MapEntry(key: mode, value: theme) in themes.entries) {
      for (final intensity in BackdropIntensity.values) {
        for (final size in sizes) {
          final name =
              '${intensity.name}_${mode}_'
              '${size.width.toInt()}x${size.height.toInt()}';

          // A heading and a line of text straight on the page, and a card,
          // as a page draws them on the backdrop.
          testWidgets('backdrop, $name', (tester) async {
            tester.view.physicalSize = size;
            tester.view.devicePixelRatio = 1;
            addTearDown(tester.view.reset);
            await tester.pumpWidget(
              MaterialApp(
                debugShowCheckedModeBanner: false,
                theme: theme,
                home: Scaffold(
                  body: PageFrame.centered(
                    maxWidth: ContentWidths.form,
                    intensity: intensity,
                    child: Builder(
                      builder: (context) {
                        final text = Theme.of(context).textTheme;
                        return Column(
                          mainAxisSize: MainAxisSize.min,
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            Text('Shush Gift', style: text.headlineMedium),
                            const SizedBox(height: Spacing.s8),
                            Text(
                              'Wish lists for every occasion.',
                              style: text.bodyLarge,
                            ),
                            const SizedBox(height: Spacing.s24),
                            Card(
                              child: Padding(
                                padding: const EdgeInsets.all(Spacing.s16),
                                child: Text(
                                  'Cards keep their opaque surface.',
                                  style: text.bodyMedium,
                                ),
                              ),
                            ),
                          ],
                        );
                      },
                    ),
                  ),
                ),
              ),
            );
            await expectLater(
              find.byType(MaterialApp),
              matchesGoldenFile('goldens/backdrop_$name.png'),
            );
          }, tags: ['golden']);
        }
      }
    }
  });
}
