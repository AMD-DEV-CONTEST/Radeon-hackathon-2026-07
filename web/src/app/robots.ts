import { MetadataRoute } from 'next';

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
      disallow: '/dashboard', // Protect private console dashboard routes from indexing
    },
    sitemap: 'https://pitchdock.xyz/sitemap.xml',
  };
}
