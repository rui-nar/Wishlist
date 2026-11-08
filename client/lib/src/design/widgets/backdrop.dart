import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import '../wishlist_colors.dart';

/// How strongly [Backdrop] draws its motif (WEB_LAYOUT_PLAN D4).
enum BackdropIntensity {
  /// Behind app screens.
  subtle,

  /// The welcome page and the sign-in screen.
  bold,
}

/// The page background with an abstract motif behind [child]
/// (WEB_LAYOUT_PLAN D4): large, soft, overlapping curved shapes in the motif
/// colours of [WishlistColors], anchored to the top-right and bottom-left
/// corners so the centre, where content sits, stays calm.
///
/// Fills its constraints, which must be bounded. Pages get it through
/// `PageFrame` rather than directly.
class Backdrop extends StatelessWidget {
  const Backdrop({
    super.key,
    required this.child,
    this.intensity = BackdropIntensity.subtle,
  });

  final Widget child;
  final BackdropIntensity intensity;

  @override
  Widget build(BuildContext context) {
    final colors = context.wishlistColors;

    return CustomPaint(
      painter: BackdropPainter(
        background: colors.pageBackground,
        motifA: colors.motifA,
        motifB: colors.motifB,
        motifC: colors.motifC,
        intensity: intensity,
      ),
      // Scrolling content repaints on its own layer, not the motif's.
      child: RepaintBoundary(child: SizedBox.expand(child: child)),
    );
  }
}

/// Paints [Backdrop]: [background] everywhere, then the motif in [motifA],
/// [motifB] and [motifC] only, each at most fully opaque, so every pixel is
/// a blend of these four colours (D5's contrast holds on all of them).
///
/// Shapes are sized from the geometric mean of the width and height, so a
/// phone and a desktop window get the same composition at their own scale.
/// No randomness: the same size always draws the same picture.
class BackdropPainter extends CustomPainter {
  const BackdropPainter({
    required this.background,
    required this.motifA,
    required this.motifB,
    required this.motifC,
    required this.intensity,
  });

  final Color background;
  final Color motifA;
  final Color motifB;
  final Color motifC;
  final BackdropIntensity intensity;

  /// Every colour this painter paints with.
  List<Color> get colors => [background, motifA, motifB, motifC];

  @override
  void paint(Canvas canvas, Size size) {
    final rect = Offset.zero & size;
    canvas.drawRect(rect, Paint()..color = background);
    if (size.isEmpty) return;

    final w = size.width;
    final h = size.height;
    final u = math.sqrt(w * h);
    // The opacity the shapes reach at their strongest.
    final k = intensity == BackdropIntensity.bold ? 1.0 : 0.55;

    canvas.save();
    canvas.clipRect(rect);

    // Top right: a teal glow, a slate wave sweeping over it, a ring.
    _glow(canvas, Offset(w + 0.06 * u, -0.08 * u), 0.78 * u, motifA, k);
    _wave(
      canvas,
      Path()
        ..moveTo(w - 0.82 * u, 0)
        ..cubicTo(
          w - 0.62 * u, 0.30 * u,
          w - 0.30 * u, 0.06 * u,
          w, 0.46 * u,
        )
        ..lineTo(w, 0)
        ..close(),
      Offset(w, 0),
      Offset(w - 0.42 * u, 0.36 * u),
      motifB,
      k,
    );
    _ring(canvas, Offset(w - 0.16 * u, 0.12 * u), 0.22 * u, motifB, k, u);

    // Bottom left: a mist glow, a teal wave sweeping over it, a ring.
    _glow(canvas, Offset(-0.06 * u, h + 0.08 * u), 0.82 * u, motifC, k);
    _wave(
      canvas,
      Path()
        ..moveTo(0, h - 0.50 * u)
        ..cubicTo(
          0.36 * u, h - 0.14 * u,
          0.16 * u, h - 0.02 * u,
          0.70 * u, h,
        )
        ..lineTo(0, h)
        ..close(),
      Offset(0, h),
      Offset(0.40 * u, h - 0.38 * u),
      motifA,
      k,
    );
    _ring(canvas, Offset(0.14 * u, h - 0.16 * u), 0.26 * u, motifB, k, u);

    canvas.restore();
  }

  /// A disc fading from [color] at its centre to nothing at its edge.
  void _glow(Canvas canvas, Offset center, double radius, Color color,
      double k) {
    final paint = Paint()
      ..shader = ui.Gradient.radial(
        center,
        radius,
        [
          color.withValues(alpha: k),
          color.withValues(alpha: 0.6 * k),
          color.withValues(alpha: 0),
        ],
        const [0, 0.45, 1],
      );
    canvas.drawCircle(center, radius, paint);
  }

  /// [path] filled with [color], fading from [from] to nothing at [to]: a
  /// crisp curved edge near the corner that dissolves towards the centre.
  void _wave(Canvas canvas, Path path, Offset from, Offset to, Color color,
      double k) {
    final paint = Paint()
      ..shader = ui.Gradient.linear(
        from,
        to,
        [color.withValues(alpha: 0.9 * k), color.withValues(alpha: 0)],
      );
    canvas.drawPath(path, paint);
  }

  /// A thin circle outline in [color].
  void _ring(Canvas canvas, Offset center, double radius, Color color,
      double k, double u) {
    final paint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = math.max(1.5, 0.004 * u)
      ..color = color.withValues(alpha: k);
    canvas.drawCircle(center, radius, paint);
  }

  @override
  bool shouldRepaint(BackdropPainter oldDelegate) =>
      background != oldDelegate.background ||
      motifA != oldDelegate.motifA ||
      motifB != oldDelegate.motifB ||
      motifC != oldDelegate.motifC ||
      intensity != oldDelegate.intensity;
}
