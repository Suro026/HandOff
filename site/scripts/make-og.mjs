// Renders public/og.png (1200x630) from an inline SVG in the page's visual language.
// Text is limited to the product name and tagline.
import sharp from 'sharp';
import { writeFileSync, mkdirSync } from 'node:fs';

const NAME = 'Handoff';
const L1 = 'Deliver finished work.';
const L2 = 'Exactly as you made it.';
const font = 'Segoe UI, Helvetica, Arial, sans-serif';

const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630">
<rect width="1200" height="630" fill="#FFF8EF"/>
<rect x="0.5" y="0.5" width="1199" height="629" fill="none" stroke="#EBD9BF"/>
<rect x="760" y="-40" width="520" height="220" fill="#FFC27A" opacity="0.55" transform="rotate(-8 760 -40)"/>
<g transform="translate(80 72)">
  <g transform="scale(1.125)">
    <rect x="6" y="6" width="14" height="52" rx="5" fill="#D63A06"/>
    <rect x="24" y="24" width="16" height="16" rx="2.5" fill="#D63A06"/>
    <rect x="44" y="6" width="14" height="52" rx="5" fill="#0F8B8D"/>
  </g>
  <text x="90" y="52" font-family="${font}" font-size="40" font-weight="800" fill="#0E2F2F">${NAME}</text>
</g>
<text x="80" y="330" font-family="${font}" font-size="64" font-weight="800" fill="#0E2F2F">${L1}</text>
<text x="80" y="410" font-family="${font}" font-size="64" font-weight="800" fill="#C23400">${L2}</text>
</svg>`;

mkdirSync('public', { recursive: true });
writeFileSync('public/og.svg', svg);
await sharp(Buffer.from(svg)).png({ compressionLevel: 9 }).toFile('public/og.png');
console.log('wrote public/og.png');
