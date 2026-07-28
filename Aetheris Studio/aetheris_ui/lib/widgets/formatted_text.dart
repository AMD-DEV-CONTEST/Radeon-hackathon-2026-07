import 'package:flutter/material.dart';

import '../theme.dart';

/// Splits text on ``` fences and renders code blocks in their own bordered,
/// monospace, dark container (with a language label when the fence names
/// one) instead of the whole message rendering as one flat, unstyled block
/// of text -- the reported complaint was specifically that code the model
/// writes in chat "stays raw, no special effect" next to the surrounding
/// prose. Deliberately not a full Markdown renderer (no bold/headers/lists
/// styling): code fences were the concrete, reported gap, and pulling in a
/// markdown package this late is a bigger, riskier change than this scope
/// calls for.
class FormattedText extends StatelessWidget {
  final String text;
  final Color proseColor;
  final double fontSize;

  const FormattedText({super.key, required this.text, required this.proseColor, this.fontSize = 13});

  @override
  Widget build(BuildContext context) {
    final segments = _splitFences(text);
    if (segments.length == 1 && !segments.first.isCode) {
      // Common case (a plain reply with no code at all): skip the Column
      // wrapper entirely, same single-widget shape as before this change.
      return SelectableText(
        segments.first.content,
        style: TextStyle(color: proseColor, fontSize: fontSize, height: 1.4),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 0; i < segments.length; i++) ...[
          if (i > 0) const SizedBox(height: 8),
          segments[i].isCode
              ? _CodeBlock(language: segments[i].language, code: segments[i].content, fontSize: fontSize)
              : SelectableText(
                  segments[i].content,
                  style: TextStyle(color: proseColor, fontSize: fontSize, height: 1.4),
                ),
        ],
      ],
    );
  }

  static List<_Segment> _splitFences(String text) {
    final fenceOpen = RegExp(r'```([a-zA-Z0-9_+-]*)\n');
    final segments = <_Segment>[];
    var cursor = 0;
    while (true) {
      final openMatch = fenceOpen.firstMatch(text.substring(cursor));
      if (openMatch == null) {
        final rest = text.substring(cursor);
        if (rest.isNotEmpty || segments.isEmpty) segments.add(_Segment(rest, false, ''));
        break;
      }
      final openStart = cursor + openMatch.start;
      final bodyStart = cursor + openMatch.end;
      if (openStart > cursor) {
        segments.add(_Segment(text.substring(cursor, openStart), false, ''));
      }
      final closeIdx = text.indexOf('```', bodyStart);
      final language = openMatch.group(1) ?? '';
      if (closeIdx == -1) {
        // Unclosed fence (still streaming, or the model just never closed
        // it) -- show everything to the end as code rather than dropping it.
        segments.add(_Segment(text.substring(bodyStart), true, language));
        break;
      }
      var body = text.substring(bodyStart, closeIdx);
      if (body.endsWith('\n')) body = body.substring(0, body.length - 1);
      segments.add(_Segment(body, true, language));
      cursor = closeIdx + 3;
    }
    return segments;
  }
}

class _Segment {
  final String content;
  final bool isCode;
  final String language;
  _Segment(this.content, this.isCode, this.language);
}

class _CodeBlock extends StatelessWidget {
  final String language;
  final String code;
  final double fontSize;

  const _CodeBlock({required this.language, required this.code, required this.fontSize});

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        color: const Color(0xFF17191C),
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(6),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (language.isNotEmpty)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.fromLTRB(10, 6, 10, 6),
              decoration: const BoxDecoration(
                border: Border(bottom: BorderSide(color: AppColors.border)),
              ),
              child: Text(language,
                  style: const TextStyle(color: AppColors.textMuted, fontSize: 11, letterSpacing: 0.5)),
            ),
          Padding(
            padding: const EdgeInsets.all(10),
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: SelectableText(
                code,
                style: TextStyle(color: AppColors.accentGreen, fontFamily: AppFonts.mono, fontSize: fontSize - 1),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
