import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shushgift/src/design/theme.dart';
import 'package:shushgift/src/design/shushgift_colors.dart';

/// WCAG 2.x relative luminance of an opaque colour.
double _luminance(Color c) {
  double channel(double v) =>
      v <= 0.04045 ? v / 12.92 : math.pow((v + 0.055) / 1.055, 2.4).toDouble();
  return 0.2126 * channel(c.r) + 0.7152 * channel(c.g) + 0.0722 * channel(c.b);
}

/// WCAG 2.x contrast ratio, from 1 to 21.
double _contrast(Color a, Color b) {
  final la = _luminance(a);
  final lb = _luminance(b);
  return (math.max(la, lb) + 0.05) / (math.min(la, lb) + 0.05);
}

void main() {
  test('the WCAG ratio matches known values', () {
    expect(_contrast(Colors.black, Colors.white), closeTo(21, 0.01));
    expect(_contrast(Colors.white, Colors.white), closeTo(1, 0.01));
    // slate-500 on slate-100: the pair D2 rejected for metadata.
    expect(
      _contrast(const Color(0xFF64748B), const Color(0xFFF1F5F9)),
      closeTo(4.34, 0.01),
    );
  });

  final themes = {'light': buildLightTheme(), 'dark': buildDarkTheme()};

  for (final MapEntry(key: name, value: theme) in themes.entries) {
    final s = theme.colorScheme;
    final w = theme.extension<ShushGiftColors>()!;

    // Foreground, background: the pairs of DESIGN_SYSTEM_PLAN U1.
    final pairs = <String, (Color, Color)>{
      'body text on surface': (w.bodyText, s.surface),
      'body text on page background': (w.bodyText, w.pageBackground),
      'headings on surface': (s.onSurface, s.surface),
      'headings on page background': (s.onSurface, w.pageBackground),
      'metadata on surface': (s.onSurfaceVariant, s.surface),
      'metadata on page background': (s.onSurfaceVariant, w.pageBackground),
      'onPrimary on primary': (s.onPrimary, s.primary),
      'onPrimaryContainer on primaryContainer':
          (s.onPrimaryContainer, s.primaryContainer),
      'onInviteeActivityContainer on inviteeActivityContainer':
          (w.onInviteeActivityContainer, w.inviteeActivityContainer),
      'primary (links, outlined buttons) on surface': (s.primary, s.surface),
      'error on surface': (s.error, s.surface),
      'onError on error': (s.onError, s.error),
    };

    // Text drawn straight on the page sits on the backdrop's motif
    // (WEB_LAYOUT_PLAN D5).
    final text = {
      'body text': w.bodyText,
      'headings': s.onSurface,
      'metadata': s.onSurfaceVariant,
    };
    final motif = {
      'motifA': w.motifA,
      'motifB': w.motifB,
      'motifC': w.motifC,
    };
    for (final MapEntry(key: fgName, value: fg) in text.entries) {
      for (final MapEntry(key: bgName, value: bg) in motif.entries) {
        pairs['$fgName on $bgName'] = (fg, bg);
      }
    }

    group('$name theme', () {
      for (final MapEntry(key: label, value: (fg, bg)) in pairs.entries) {
        test('$label is at least 4.5:1', () {
          expect(_contrast(fg, bg), greaterThanOrEqualTo(4.5));
        });
      }

      // The backdrop paints the motif colours translucent over the page
      // background and over each other, so pixels are blends of them.
      test('text is at least 4.5:1 on every blend of the backdrop', () {
        final layers = [w.pageBackground, ...motif.values];
        for (final a in layers) {
          for (final b in layers) {
            for (var i = 0; i <= 10; i++) {
              final bg = Color.lerp(a, b, i / 10)!;
              for (final MapEntry(key: label, value: fg) in text.entries) {
                expect(
                  _contrast(fg, bg),
                  greaterThanOrEqualTo(4.5),
                  reason: '$label on $bg',
                );
              }
            }
          }
        }
      });
    });
  }
}
