import {MapPin, Radio, Tickets} from 'lucide-react';
import type {PosterProject} from '../types';
import {styles} from '../data/mock';
import {formatPosterLocation, localizedPosterCopy} from '../utils/posterLanguage';

export default function PosterPreview({project, nodeRef}: {
  project: PosterProject;
  nodeRef?: React.Ref<HTMLDivElement>;
}) {
  const style = styles.find((item) => item.id === project.styleId) ?? styles[0];
  const copy = localizedPosterCopy(project);
  const bands = copy.bands.length
    ? copy.bands
    : [
      {id: '1', name: '', genre: '', displayName: copy.subject || 'SUBJECT A', displayGenre: ''},
      {id: '2', name: '', genre: '', displayName: 'SUBJECT B', displayGenre: ''},
    ];

  return <div ref={nodeRef} className={`poster poster-${style.id}`} data-poster-language={copy.language}>
    <div className="poster-grid"/>
    <div className="poster-orbit orbit-a"/>
    <div className="poster-orbit orbit-b"/>
    <div className="poster-kicker"><Radio size={13}/> POSTER VISUAL LAB · AMD</div>
    <div className="poster-title"><span>{copy.title}</span><strong>{copy.theme}</strong></div>
    <div className="poster-duel">{bands.slice(0, 2).map((band, index) => <div className="fighter" key={band.id}>
      <div className="silhouette">{band.logo?.dataUrl ? <img src={band.logo.dataUrl} alt={band.displayName}/> : <span>0{index + 1}</span>}</div>
      <b>{band.displayName}</b><small>{band.displayGenre}</small>
    </div>)}</div>
    <div className="poster-info">
      <span>{copy.labels.date}: {project.dateTime || copy.labels.pending}</span>
      <span><MapPin size={14}/>{copy.labels.venue}: {formatPosterLocation(copy.city, copy.venue) || copy.labels.pending}</span>
      <span><Tickets size={14}/>{copy.labels.ticket}: {project.price || copy.ticketInfo || copy.labels.pending}</span>
    </div>
    <div className="poster-foot"><b>REAL DATA / REAL LOGO</b><span>1024 × 1536</span>{project.assets.qr?.dataUrl && <img src={project.assets.qr.dataUrl} alt="购票二维码"/>}</div>
  </div>;
}
