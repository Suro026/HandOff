import { defineConfig } from 'astro/config';
import react from '@astrojs/react';

// BASE is set by the GitHub Pages workflow (e.g. "/handoff/"). Locally it is "/".
// SITE_URL is optional; when empty no canonical URL is emitted.
export default defineConfig({
  base: process.env.BASE || '/',
  site: process.env.SITE_URL || undefined,
  output: 'static',
  compressHTML: true,
  build: { inlineStylesheets: 'always' },
  integrations: [react()],
});
