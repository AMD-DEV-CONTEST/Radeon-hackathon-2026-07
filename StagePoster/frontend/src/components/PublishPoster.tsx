import type {CSSProperties, Ref} from 'react';
import type {PosterProject, VisualAnalysis} from '../types';
import {formatPosterLocation, localizedPosterCopy} from '../utils/posterLanguage';

type Props = {
  project: PosterProject;
  visualUrl: string;
  nodeRef?: Ref<HTMLDivElement>;
  palette?: string[];
  template?: string;
  analysis?: VisualAnalysis;
};

function safeColor(value: string | undefined, fallback: string) {
  return value && /^(#[0-9a-f]{3,8}|rgb|hsl)/i.test(value) ? value : fallback;
}

function hexHue(color: string) {
  const match = color.match(/^#([0-9a-f]{6})$/i);
  if (!match) return 0;
  const [r, g, b] = [0, 2, 4].map((offset) => Number.parseInt(match[1].slice(offset, offset + 2), 16) / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), delta = max - min;
  if (!delta) return 0;
  const hue = max === r ? ((g - b) / delta) % 6 : max === g ? (b - r) / delta + 2 : (r - g) / delta + 4;
  return (hue * 60 + 360) % 360;
}

function inferTheme(palette: string[], analysis?: VisualAnalysis) {
  const hint = `${analysis?.texture ?? ''} ${analysis?.typographyProfile?.family ?? ''}`.toLowerCase();
  const hues = palette.map(hexHue);
  if (/hand|drawn|organic|psychedelic|serif|collage/.test(hint) || (hues.some((hue) => hue > 65 && hue < 165) && hues.some((hue) => hue > 245 && hue < 330))) return 'organic';
  if (/editorial|minimal|clean/.test(hint)) return 'editorial';
  return 'metal';
}

export default function PublishPoster({project, visualUrl, nodeRef, palette = [], template = 'gothic_frame', analysis}: Props) {
  const copy = localizedPosterCopy(project);
  const effectivePalette = analysis?.palette?.length ? analysis.palette : analysis?.dominantColors?.length ? analysis.dominantColors : palette;
  const theme = inferTheme(effectivePalette, analysis);
  const accent = safeColor(analysis?.typographyProfile?.strokeColor ?? effectivePalette[2], theme === 'organic' ? '#d8b55b' : '#a71919');
  const paper = safeColor(analysis?.typographyProfile?.fillColor ?? effectivePalette.find((color) => /#(?:[c-f][0-9a-f]){3}/i.test(color)), theme === 'organic' ? '#090909' : '#eee8dc');
  const safeZone = analysis?.textSafeZones?.slice().sort((a, b) => (a.priority ?? 99) - (b.priority ?? 99))[0];
  const safeX = safeZone ? Math.min(0.72, Math.max(0.07, safeZone.x)) : 0;
  const safeY = safeZone ? Math.min(0.55, Math.max(0.1, safeZone.y)) : 0;
  const safeW = safeZone ? Math.min(0.86, Math.max(0.22, Math.min(safeZone.w, 0.93 - safeX))) : 0;
  const safeH = safeZone ? Math.min(0.26, Math.max(0.12, Math.min(safeZone.h, 0.68 - safeY))) : 0;
  const style = {
    '--poster-accent': accent,
    '--poster-paper': paper,
    ...(safeZone ? {
      '--title-x': `${safeX * 100}%`, '--title-y': `${safeY * 100}%`,
      '--title-w': `${safeW * 100}%`, '--title-h': `${safeH * 100}%`,
    } : {}),
  } as CSSProperties;
  const templateClass = /center|cinematic/i.test(template) ? 'cinematic-center' : /editorial|top/i.test(template) ? 'editorial-top' : 'gothic-frame';
  const verticalTitle = Boolean(safeZone && safeZone.h > safeZone.w * 1.55 && /[\u3400-\u9fff]/.test(copy.title));
  const compactTitle = copy.title.length > 18;
  const bands = copy.bands.filter((band) => band.displayName || band.logo);

  return <div className={`session-publish-poster publish-theme-metal publish-variant-${theme} ${templateClass} ${safeZone ? 'safe-placement' : ''} ${verticalTitle ? 'vertical-title' : ''} ${compactTitle ? 'compact-title' : ''}`} ref={nodeRef} style={style}>
    <img className="session-publish-visual" src={visualUrl} alt={`${copy.title} AI 主视觉`}/>
    <div className="session-publish-shade"/>
    <div className="publish-grain"/>
    <div className="session-publish-copy">
      <small>POSTER VISUAL LAB · AMD ROCm</small>
      <div className="publish-title-lockup">
        <h2 data-text={copy.title}>{copy.title}</h2>
        <p>{copy.theme}</p>
      </div>
      <div className={`session-publish-bands count-${Math.min(3, bands.length)}`}>
        {bands.map((band, index) => <div className="publish-band" key={band.id}>
          {index > 0 && <i aria-hidden="true">×</i>}
          <span>{band.logo?.dataUrl
            ? <img src={band.logo.dataUrl} alt={`${band.displayName} Logo`}/>
            : <b>{band.displayName}</b>}
            {band.displayGenre && <em>{band.displayGenre}</em>}
          </span>
        </div>)}
      </div>
      <dl>
        <div><dt>{copy.labels.date}</dt><dd>{project.dateTime}</dd></div>
        <div><dt>{copy.labels.venue}</dt><dd>{formatPosterLocation(copy.city, copy.venue)}</dd></div>
        {(project.price || copy.ticketInfo) && <div><dt>{copy.labels.ticket}</dt><dd>{project.price || copy.ticketInfo}</dd></div>}
      </dl>
      {project.assets.qr?.dataUrl && <img className="session-publish-qr" src={project.assets.qr.dataUrl} alt="购票二维码"/>}
    </div>
  </div>;
}
