import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../tokens.dart';
import 'backdrop.dart';

/// A page's body (WEB_LAYOUT_PLAN D2): the [Backdrop] filling it, and the
/// content centred and capped at one of the [ContentWidths], padded
/// [Spacing.s16] on compact windows and [Spacing.s24] from
/// [Breakpoints.medium].
///
/// Two forms, so no screen computes widths itself:
///
/// - [PageFrame.new] for a body that scrolls. The frame gives [child] the
///   full width, so the scroll bar stays at the window edge and the wheel
///   scrolls anywhere over the page; the scroll view caps its content by
///   taking its padding from [paddingOf]:
///
///   ```dart
///   PageFrame(
///     child: ListView(
///       padding: PageFrame.paddingOf(context, ContentWidths.reading),
///       children: [...],
///     ),
///   )
///   ```
///
/// - [PageFrame.centered] for a body that does not scroll by itself (a
///   `Center`ed card, a `Column`): the frame pads it, caps it at [maxWidth]
///   and centres it horizontally.
class PageFrame extends StatelessWidget {
  const PageFrame({
    super.key,
    required this.child,
    this.intensity = BackdropIntensity.subtle,
  })  : maxWidth = null,
        padding = null;

  const PageFrame.centered({
    super.key,
    required this.child,
    double this.maxWidth = ContentWidths.reading,
    this.intensity = BackdropIntensity.subtle,
    this.padding,
  });

  final Widget child;
  final BackdropIntensity intensity;

  /// The cap of a [PageFrame.centered] child; null for a scrolling one,
  /// whose scroll view gets it through [paddingOf].
  final double? maxWidth;

  /// Replaces the window class's padding around a [PageFrame.centered]
  /// child.
  final EdgeInsets? padding;

  /// The padding of a scroll view inside a [PageFrame]: the window class's
  /// padding, widened on both sides so the content is a centred column of
  /// at most [maxWidth].
  ///
  /// Measured against the window (D1). A page drawn beside something else,
  /// such as a navigation rail, gets a column narrower than [maxWidth] by
  /// that thing's width, still centred.
  static EdgeInsets paddingOf(BuildContext context, double maxWidth) {
    final width = MediaQuery.sizeOf(context).width;
    final pad = _classPadding(width);
    final side = math.max(pad, (width - maxWidth) / 2);
    return EdgeInsets.symmetric(horizontal: side, vertical: pad);
  }

  static double _classPadding(double windowWidth) =>
      windowWidth < Breakpoints.medium ? Spacing.s16 : Spacing.s24;

  @override
  Widget build(BuildContext context) {
    final cap = maxWidth;
    if (cap == null) return Backdrop(intensity: intensity, child: child);

    return Backdrop(
      intensity: intensity,
      child: Padding(
        padding: padding ??
            EdgeInsets.all(_classPadding(MediaQuery.sizeOf(context).width)),
        child: Align(
          alignment: Alignment.topCenter,
          // The cap, or less when the window is narrower. The height is left
          // to the child, so a `Center` child still centres vertically.
          child: SizedBox(width: cap, child: child),
        ),
      ),
    );
  }
}
