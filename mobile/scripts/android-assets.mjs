// Draws the Android launcher icons and start-up screens from the app's icon (static/icon.svg), in the Plain
// look: the white check-and-arrow mark on a near-black tile. Run after changing the icon, then commit:
//   node scripts/android-assets.mjs     (needs Chromium for Playwright)
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const MOBILE = fileURLToPath(new URL('..', import.meta.url));
const RES = join(MOBILE, 'android', 'app', 'src', 'main', 'res');
const TILE = '#1F2328';
const SPLASH_BG = '#F9F9F9';
const svg = readFileSync(join(MOBILE, '..', 'static', 'icon.svg'), 'utf8');
const MARK = '<path d="M132 268l76 76 168-176" fill="none" stroke="#fff" stroke-width="46" stroke-linecap="round" stroke-linejoin="round"/>' +
  '<path d="M296 168h80v80" fill="none" stroke="#fff" stroke-width="46" stroke-linecap="round" stroke-linejoin="round"/>';

const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
const page = await browser.newPage();

async function png(html, w, h, file, transparent = false) {
  await page.setViewportSize({ width: w, height: h });
  await page.setContent(`<html><body style="margin:0;background:transparent">${html}</body></html>`);
  writeFileSync(file, await page.screenshot({ omitBackground: transparent, clip: { x: 0, y: 0, width: w, height: h } }));
}

const DENSITIES = { mdpi: 1, hdpi: 1.5, xhdpi: 2, xxhdpi: 3, xxxhdpi: 4 };
for (const [name, scale] of Object.entries(DENSITIES)) {
  const dir = join(RES, `mipmap-${name}`);
  const s = Math.round(48 * scale);
  await png(svg.replace('<svg ', `<svg width="${s}" height="${s}" `), s, s, join(dir, 'ic_launcher.png'), true);
  await png(`<svg xmlns="http://www.w3.org/2000/svg" width="${s}" height="${s}" viewBox="0 0 512 512"><circle cx="256" cy="256" r="256" fill="${TILE}"/>${MARK}</svg>`,
    s, s, join(dir, 'ic_launcher_round.png'), true);
  // Adaptive icon: the mark alone on a 108dp canvas, inside the middle 66dp the launcher always shows
  const f = Math.round(108 * scale), inner = Math.round(66 * scale), off = (f - inner) / 2;
  await png(`<svg xmlns="http://www.w3.org/2000/svg" width="${f}" height="${f}"><svg x="${off}" y="${off}" width="${inner}" height="${inner}" viewBox="0 0 512 512">${MARK}</svg></svg>`,
    f, f, join(dir, 'ic_launcher_foreground.png'), true);
}

// Start-up screens (Android 11 and earlier; newer versions show the launcher icon on its own)
const SPLASH = { '': [480, 320], 'port-mdpi': [320, 480], 'port-hdpi': [480, 800], 'port-xhdpi': [720, 1280], 'port-xxhdpi': [960, 1600],
  'port-xxxhdpi': [1280, 1920], 'land-mdpi': [480, 320], 'land-hdpi': [800, 480], 'land-xhdpi': [1280, 720], 'land-xxhdpi': [1600, 960],
  'land-xxxhdpi': [1920, 1280] };
for (const [name, [w, h]] of Object.entries(SPLASH)) {
  const s = Math.round(Math.min(w, h) * 0.28);
  await png(`<div style="width:${w}px;height:${h}px;background:${SPLASH_BG};display:flex;align-items:center;justify-content:center">${svg.replace('<svg ', `<svg width="${s}" height="${s}" `)}</div>`,
    w, h, join(RES, name ? `drawable-${name}` : 'drawable', 'splash.png'));
}
await browser.close();
writeFileSync(join(RES, 'values', 'ic_launcher_background.xml'),
  `<?xml version="1.0" encoding="utf-8"?>\n<resources>\n    <color name="ic_launcher_background">${TILE}</color>\n</resources>\n`);
console.log('Android icons and start-up screens drawn');
