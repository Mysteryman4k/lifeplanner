// Builds the phone app's web files into www/: the desktop's screens (static/), a page that loads them with
// the phone's backend first (src/main.ts, bundled as mobile.js), and the phone's own style tweaks (web/).
// Capacitor then copies www/ into the Android and iOS projects (npm run sync).
import { build } from 'esbuild';
import { cpSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const MOBILE = join(HERE, '..');
const ROOT = join(MOBILE, '..');
const OUT = join(MOBILE, 'www');
const VERSION = readFileSync(join(ROOT, 'VERSION'), 'utf8').trim();

rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT, { recursive: true });

// The desktop's screens, as they are (splash.html is the desktop's start-up window: not needed)
cpSync(join(ROOT, 'static'), join(OUT, 'static'), { recursive: true, filter: src => !src.endsWith('splash.html') });
cpSync(join(MOBILE, 'node_modules', 'sql.js', 'dist', 'sql-wasm.wasm'), join(OUT, 'static', 'vendor', 'sql-wasm.wasm'));
cpSync(join(MOBILE, 'web', 'mobile.css'), join(OUT, 'mobile.css'));
// pdf.js reads attached PDFs on the phone (loaded only when one is attached)
for (const f of ['pdf.min.mjs', 'pdf.worker.min.mjs']) {
  cpSync(join(MOBILE, 'node_modules', 'pdfjs-dist', 'legacy', 'build', f), join(OUT, 'static', 'vendor', 'pdfjs', f));
}
cpSync(join(MOBILE, 'node_modules', 'pdfjs-dist', 'LICENSE'), join(OUT, 'static', 'vendor', 'pdfjs', 'LICENSE'));

await build({
  entryPoints: [join(MOBILE, 'src', 'main.ts')],
  outfile: join(OUT, 'mobile.js'),
  bundle: true,
  format: 'iife',
  platform: 'browser',
  target: 'es2020',
  minify: true,
  sourcemap: true,
  define: { __APP_VERSION__: JSON.stringify(VERSION) },
  logLevel: 'warning',
});

// The page: the desktop's index.html with the phone's backend loaded before app.js, versioned links
// (like app.py's index route) and nothing that only the desktop server provides.
let html = readFileSync(join(ROOT, 'static', 'index.html'), 'utf8');
const swap = (from, to) => {
  if (!html.includes(from)) throw new Error(`static/index.html changed: couldn't find ${from}`);
  html = html.replace(from, to);
};
swap('<link rel="manifest" href="/manifest.json">\n', '');
swap('<script src="/static/vendor/purify.min.js"></script>',
  '<script src="/mobile.js"></script>\n<script src="/static/vendor/purify.min.js"></script>');
swap('<link rel="stylesheet" href="/static/intro.css">',
  '<link rel="stylesheet" href="/static/intro.css">\n<link rel="stylesheet" href="/mobile.css">');
html = html.replace(/((?:\/static\/[\w./-]+|\/mobile)\.(?:js|css))(?=")/g, `$1?v=${VERSION}`);
writeFileSync(join(OUT, 'index.html'), html);
console.log(`Built www/ for EasyUniTrack ${VERSION}`);
