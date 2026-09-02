import type {PosterLanguage, PosterProject} from '../types';

export function posterLanguage(project: PosterProject): PosterLanguage {
  return project.posterLanguage ?? 'en';
}

export function formatPosterLocation(city?: string, venue?: string): string {
  const cleanCity = city?.trim() ?? '';
  const cleanVenue = venue?.trim() ?? '';
  if (!cleanCity) return cleanVenue;
  if (!cleanVenue) return cleanCity;
  const normalizedCity = cleanCity.toLocaleLowerCase();
  const normalizedVenue = cleanVenue.toLocaleLowerCase().replace(/^[·,\s]+/, '');
  if (normalizedVenue === normalizedCity
    || normalizedVenue.startsWith(`${normalizedCity} ·`)
    || normalizedVenue.startsWith(`${normalizedCity} `)) {
    return cleanVenue;
  }
  return `${cleanCity} · ${cleanVenue}`;
}

export function localizedPosterCopy(project: PosterProject) {
  const language = posterLanguage(project);
  const english = language === 'en';
  return {
    language,
    title: (english ? project.titleEn : project.title) || project.title || 'UNTITLED',
    theme: (english ? project.themeEn : project.theme) || project.theme || 'REALITY INTO VISUAL',
    city: (english ? project.cityEn : project.city) || project.city,
    venue: (english ? project.venueEn : project.venue) || project.venue,
    subject: (english ? project.subjectEn : project.subject) || project.subject,
    ticketInfo: (english ? project.ticketInfoEn : project.ticketInfo) || project.ticketInfo,
    bands: project.bands.map((band) => ({
      ...band,
      displayName: (english ? band.nameEn : band.name) || band.name,
      displayGenre: (english ? band.genreEn : band.genre) || band.genre,
    })),
    labels: english
      ? {date: 'DATE / TIME', venue: 'VENUE', ticket: 'TICKET', pending: 'TBC'}
      : {date: '日期 / 时间', venue: '地点', ticket: '票务', pending: '待确认'},
  };
}
