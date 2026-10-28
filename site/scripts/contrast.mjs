// Checks every foreground/background token pair used on the page (WCAG 2.x ratios).
const themes = {
  light: { bg: '#FFF8EF', surface: '#FFFFFF', border: '#EBD9BF', text: '#0E2F2F', muted: '#4A6362', accent: '#C23400', success: '#0B7A5A', warning: '#8A5300', danger: '#B42318', info: '#0B6E70', onAccent: '#FFFFFF', sunken: '#FCEBD6' },
  dark: { bg: '#071A1B', surface: '#0D2A2B', border: '#1C4446', text: '#EAF7F4', muted: '#9FC2BE', accent: '#FF8A5B', success: '#5FD6A8', warning: '#FFC25C', danger: '#FF8A80', info: '#3FD0C9', onAccent: '#1A0A03', sunken: '#0A2223' },
  ink: { bg: '#071A1B', surface: '#0D2A2B', border: '#1C4446', text: '#EAF7F4', muted: '#9FC2BE', accent: '#FF8A5B', success: '#5FD6A8', warning: '#FFC25C', danger: '#FF8A80', info: '#3FD0C9', onAccent: '#1A0A03', sunken: '#0A2223' },
};
const lum = (h) => {
  const c = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
// [foreground, background, minimum]
const pairs = [
  ['text', 'bg', 4.5], ['text', 'surface', 4.5], ['text', 'sunken', 4.5],
  ['muted', 'bg', 4.5], ['muted', 'surface', 4.5], ['muted', 'sunken', 4.5],
  ['accent', 'bg', 4.5], ['accent', 'surface', 4.5],
  ['onAccent', 'accent', 4.5],
  ['success', 'surface', 4.5], ['warning', 'surface', 4.5], ['danger', 'surface', 4.5], ['info', 'surface', 4.5],
  ['success', 'bg', 4.5], ['warning', 'bg', 4.5], ['danger', 'bg', 4.5],
  ['border', 'bg', 1.0], // decorative dividers only
  ['accent', 'surface', 3.0], // focus ring / UI component
];
let fail = 0;
for (const [name, t] of Object.entries(themes)) {
  for (const [f, b, min] of pairs) {
    const r = ratio(t[f], t[b]);
    const ok = r >= min;
    if (!ok) fail++;
    console.log(`${ok ? 'ok  ' : 'FAIL'} ${name.padEnd(5)} ${f.padEnd(9)} on ${b.padEnd(8)} ${r.toFixed(2)} (min ${min})`);
  }
}
process.exit(fail ? 1 : 0);
