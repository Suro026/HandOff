# Handoff landing page

Static landing page for Handoff (working title), built with [Astro](https://astro.build). It describes the product as specified in the repository root `README.md`: finished work delivered as untouched originals through private, revocable links, with view-only links and their limits stated plainly.

Everything is server-rendered HTML and plain CSS, except the interactive hero demo, which is a small React island. The page works with JavaScript off; the demo then stays in its starting state.

## Develop

```bash
cd site
npm install
npm run dev        # http://localhost:4321
```

## Build

```bash
npm run build      # makes public/og.png, then builds to dist/
npm run preview
npm run check:contrast   # WCAG contrast of every token pair, both themes
```

## Config

Everything you might change is in `site.config.ts`: `NAME`, `TAGLINE`, `DESCRIPTION`, `REPO_URL`, `DOCS_URL`, `LICENSE_NAME`, `UPDATES_FORM_URL`, `UPDATES_FORM_SERVICE`.
Empty values hide whatever depends on them. With `LICENSE_NAME` empty the footer says "License: to be decided".

## Rename the product

1. Change `NAME` in `site.config.ts`.
2. Update the product name in `scripts/make-og.mjs` (the OG image text).
3. Review the copy in `src/pages/index.astro` for any wording that assumes the name.

## Deploy to GitHub Pages

The workflow in `.github/workflows/deploy.yml` builds with `BASE=/<repo-name>/` so assets resolve under a repository subpath, and sets `SITE_URL` for the canonical and Open Graph URLs. Locally both default to `/` and empty.
GitHub only runs workflows from the repository root, so if `site/` is inside a larger repo, copy the workflow to the root `.github/workflows/`. Then in the repo settings choose Pages → Source: GitHub Actions.

## Honesty rules

The product is pre-release. Do not add testimonials, counts, logos, payment-safety claims or a license name before they are real. See the checks at the end of the build notes in the PR description.
