/* ═══════════════════════════════════════════════════════════════
   Trackademic — appearance engine
   Colour themes × text styles × light/dark/system.
   Loaded in <head> so the saved look is applied before first paint.
   ═══════════════════════════════════════════════════════════════ */
'use strict';

/* Each theme: a gradient (a → b), the accent colour used for text/links,
   the colour of text placed on the gradient, and a hue that tints the greys. */
const THEMES = {
  sunset: {
    name: 'Sunset', hue: 18, sat: 45,
    light: { a: '#D2461A', b: '#BE1F6A', text: '#B0245A', on: '#FFFFFF' },
    dark:  { a: '#FF8A50', b: '#F0509A', text: '#FF9EC4', on: '#1F0E18' },
  },
  midnight: {
    name: 'Midnight lime', hue: 225, sat: 35,
    light: { a: '#3F6212', b: '#0E7490', text: '#3F6212', on: '#FFFFFF' },
    dark:  { a: '#C6F432', b: '#5EEAD4', text: '#C6F432', on: '#0B0F1A' },
  },
  cobalt: {
    name: 'Cobalt', hue: 228, sat: 40,
    light: { a: '#2F54EB', b: '#6D35E0', text: '#2B4DD9', on: '#FFFFFF' },
    dark:  { a: '#7C93FF', b: '#B28CFF', text: '#A5B4FF', on: '#0B1033' },
  },
  ocean: {
    name: 'Ocean', hue: 195, sat: 35,
    light: { a: '#0F766E', b: '#1D4ED8', text: '#0F6B64', on: '#FFFFFF' },
    dark:  { a: '#2DD4BF', b: '#60A5FA', text: '#5EEAD4', on: '#04201E' },
  },
  berry: {
    name: 'Berry', hue: 300, sat: 30,
    light: { a: '#A3195B', b: '#6D28D9', text: '#9A1A57', on: '#FFFFFF' },
    dark:  { a: '#F472B6', b: '#A78BFA', text: '#F9A8D4', on: '#22071A' },
  },
  graphite: {
    name: 'Graphite', hue: 240, sat: 6,
    light: { a: '#18181B', b: '#52525B', text: '#18181B', on: '#FFFFFF' },
    dark:  { a: '#FAFAFA', b: '#A1A1AA', text: '#FAFAFA', on: '#09090B' },
  },
};

/* Text styles: a display face for headings/numbers and a body face. */
const FONTS = {
  rounded:    { name: 'Rounded',    display: 'Outfit',              body: 'Outfit',            weight: 700, track: '-0.025em', sample: 'Friendly and soft' },
  modern:     { name: 'Modern',     display: 'Plus Jakarta Sans',   body: 'Plus Jakarta Sans', weight: 800, track: '-0.03em',  sample: 'Clean and sharp' },
  expressive: { name: 'Expressive', display: 'Bricolage Grotesque', body: 'DM Sans',           weight: 800, track: '-0.035em', sample: 'Bold with character' },
  techy:      { name: 'Techy',      display: 'Space Grotesk',       body: 'Space Grotesk',     weight: 700, track: '-0.03em',  sample: 'Geometric and nerdy' },
  classic:    { name: 'Classic',    display: 'Fraunces',            body: 'DM Sans',           weight: 600, track: '-0.02em',  sample: 'Editorial serif' },
};

const DEFAULT_APPEARANCE = { theme: 'sunset', font: 'rounded', mode: 'system' };
const APPEARANCE_KEY = 'trackademic-appearance';

function hsl(h, s, l) { return `hsl(${h} ${s}% ${l}%)`; }

/* Greys tinted towards the theme's hue, so every theme feels coherent. */
function neutrals(h, s, dark) {
  if (dark) return {
    '--bg': hsl(h, s * 0.55, 6.5), '--surface': hsl(h, s * 0.5, 10), '--surface-2': hsl(h, s * 0.45, 14),
    '--surface-3': hsl(h, s * 0.4, 18), '--line': hsl(h, s * 0.4, 18.5), '--line-strong': hsl(h, s * 0.35, 26),
    '--ink': hsl(h, Math.min(30, s), 94), '--ink-2': hsl(h, s * 0.3, 76), '--muted': hsl(h, s * 0.2, 60),
    '--bar-track': hsl(h, s * 0.4, 17),
  };
  return {
    '--bg': hsl(h, s * 0.9, 97.6), '--surface': hsl(h, s, 99.6), '--surface-2': hsl(h, s * 0.75, 94.8),
    '--surface-3': hsl(h, s * 0.6, 91), '--line': hsl(h, s * 0.5, 90), '--line-strong': hsl(h, s * 0.35, 80),
    '--ink': hsl(h, Math.min(45, s + 10), 12), '--ink-2': hsl(h, s * 0.35, 30), '--muted': hsl(h, s * 0.18, 41),
    '--bar-track': hsl(h, s * 0.6, 92),
  };
}

const systemDark = window.matchMedia('(prefers-color-scheme: dark)');

function readAppearance() {
  try {
    const saved = JSON.parse(localStorage.getItem(APPEARANCE_KEY) || 'null');
    if (saved && typeof saved === 'object') return { ...DEFAULT_APPEARANCE, ...saved };
  } catch (_) {}
  return { ...DEFAULT_APPEARANCE };
}

function applyAppearance(p) {
  const pref = { ...DEFAULT_APPEARANCE, ...p };
  const theme = THEMES[pref.theme] || THEMES.sunset;
  const font = FONTS[pref.font] || FONTS.rounded;
  const dark = pref.mode === 'dark' || (pref.mode === 'system' && systemDark.matches);
  const c = dark ? theme.dark : theme.light;
  const root = document.documentElement;
  const vars = {
    ...neutrals(theme.hue, theme.sat, dark),
    '--grad-a': c.a, '--grad-b': c.b,
    '--grad': `linear-gradient(135deg, ${c.a}, ${c.b})`,
    '--accent': c.a, '--accent-text': c.text, '--accent-ink': c.on,
    '--display': `'${font.display}', system-ui, sans-serif`,
    '--font': `'${font.body}', system-ui, -apple-system, 'Segoe UI', sans-serif`,
    '--display-weight': font.weight, '--display-track': font.track,
  };
  for (const [k, v] of Object.entries(vars)) root.style.setProperty(k, v);
  root.dataset.mode = dark ? 'dark' : 'light';
  root.dataset.theme = pref.theme;
  root.style.colorScheme = dark ? 'dark' : 'light';
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.content = c.a;
  window.__appearance = pref;
  return pref;
}

function saveAppearanceLocal(p) {
  try { localStorage.setItem(APPEARANCE_KEY, JSON.stringify(p)); } catch (_) {}
}

// Follow the computer's light/dark setting live when mode is "system"
systemDark.addEventListener?.('change', () => { if ((window.__appearance || {}).mode === 'system') applyAppearance(window.__appearance); });

applyAppearance(readAppearance());
