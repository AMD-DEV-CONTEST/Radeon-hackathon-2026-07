import 'package:flutter/material.dart';

/// 1:1 port of views/theme.py's "Trae Solo inspired dark developer theme".
class AppColors {
  static const bg = Color(0xFF030303);
  static const panel = Color(0xFF0A0B0C);
  static const border = Color(0xFF141618);
  static const inputBg = Color(0xFF0C0D0F);

  static const accentGreen = Color(0xFF32F08C);
  static const accentBlue = Color(0xFF00D2FF);
  static const accentPurple = Color(0xFF8A2BE2);
  static const accentRed = Color(0xFFE06C75);

  static const textPrimary = Color(0xFFD1D4E0);
  static const textMuted = Color(0xFF5C6370);
  static const textWhite = Color(0xFFFFFFFF);
}

class AppFonts {
  static const mono = 'Consolas';
  static const sans = 'Segoe UI';
}

ThemeData buildAppTheme() {
  return ThemeData(
    brightness: Brightness.dark,
    scaffoldBackgroundColor: AppColors.bg,
    fontFamily: AppFonts.sans,
    colorScheme: const ColorScheme.dark(
      primary: AppColors.accentGreen,
      secondary: AppColors.accentBlue,
      error: AppColors.accentRed,
      surface: AppColors.panel,
    ),
    dialogTheme: const DialogThemeData(
      backgroundColor: AppColors.panel,
      surfaceTintColor: Colors.transparent,
    ),
    textTheme: const TextTheme(
      bodyMedium: TextStyle(color: AppColors.textPrimary),
    ),
    dividerColor: AppColors.border,
    inputDecorationTheme: const InputDecorationTheme(
      filled: true,
      fillColor: AppColors.inputBg,
      border: OutlineInputBorder(borderSide: BorderSide(color: AppColors.border)),
    ),
  );
}
