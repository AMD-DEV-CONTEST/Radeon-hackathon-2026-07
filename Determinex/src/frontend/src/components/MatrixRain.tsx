"use client";
import { useIterationTheme } from "@/contexts/IterationThemeContext";
import {
  CodefallTheme,
  OrbitalHUDTheme,
  NeonTerminalTheme,
  StrategyConsoleTheme,
  VectorGridTheme,
  RedLensTheme,
  ArchiveCoreTheme,
  AegisAssistantTheme,
  TerrainNavigatorTheme,
  RainCityTheme,
  ShelterTerminalTheme,
  CaveConsoleTheme,
  AetherConsoleTheme,
  EndoframeHUDTheme,
  WraithTerminalTheme,
  RingArrayTheme,
  TestChamberTheme,
  GalaxyAtlasTheme,
  DeepSpaceSignalTheme,
  DungeonMapTheme,
  MechBayTheme,
  PlainDarkTheme,
  PlainLightTheme,
  type LoadingThemeProps,
} from "./LoadingThemes";

export type MatrixRainProps = LoadingThemeProps;

const THEMES = {
  determinex: OrbitalHUDTheme,
  codefall: CodefallTheme,
  orbital: OrbitalHUDTheme,
  neon: NeonTerminalTheme,
  strategy: StrategyConsoleTheme,
  vector: VectorGridTheme,
  redlens: RedLensTheme,
  archive: ArchiveCoreTheme,
  aegis: AegisAssistantTheme,
  terrain: TerrainNavigatorTheme,
  raincity: RainCityTheme,
  shelter: ShelterTerminalTheme,
  cave: CaveConsoleTheme,
  aether: AetherConsoleTheme,
  endoframe: EndoframeHUDTheme,
  wraith: WraithTerminalTheme,
  ringarray: RingArrayTheme,
  testchamber: TestChamberTheme,
  galaxyatlas: GalaxyAtlasTheme,
  deepspace: DeepSpaceSignalTheme,
  dungeon: DungeonMapTheme,
  mechbay: MechBayTheme,
  rocinante: OrbitalHUDTheme,
  lightcycle: VectorGridTheme,
  trex: TerrainNavigatorTheme,
  plaindark: PlainDarkTheme,
  plainlight: PlainLightTheme,
} as const;

export function MatrixRain(props: MatrixRainProps) {
  const { theme } = useIterationTheme();
  const Theme = THEMES[theme] ?? CodefallTheme;
  return <Theme {...props} />;
}
