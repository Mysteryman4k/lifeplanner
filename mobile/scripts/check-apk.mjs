// Checks a built Android package has what the app needs to start: the screens, the phone's backend,
// the SQLite engine and the icons. CI runs it on the debug build.
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

const apk = process.argv[2];
const list = execFileSync('unzip', ['-l', apk]).toString();
const version = readFileSync(new URL('../../VERSION', import.meta.url), 'utf8').trim();
const need = [
  'assets/public/index.html', 'assets/public/mobile.js', 'assets/public/mobile.css', 'assets/public/static/app.js',
  'assets/public/static/styles.css', 'assets/public/static/vendor/katex/katex.min.js', 'assets/capacitor.config.json',
  'assets/public/static/vendor/pdfjs/pdf.min.mjs', 'assets/public/static/vendor/pdfjs/pdf.worker.min.mjs', 'assets/public/static/vendor/sql-wasm.wasm',
  'res/mipmap-anydpi-v26/ic_launcher.xml', 'AndroidManifest.xml', 'classes.dex',
];
const missing = need.filter(f => !list.includes(f));
if (!/lib\/[^/]+\/libsqlcipher\.so|lib\/[^/]+\/libsqlite/.test(list) && !list.includes('net/zetetic')) {
  console.log('Note: no bundled SQLite library found by name (the plugin may use Android\'s own)');
}
if (missing.length) {
  console.error(`The app package is missing: ${missing.join(', ')}`);
  process.exit(1);
}
const html = execFileSync('unzip', ['-p', apk, 'assets/public/index.html']).toString();
if (!html.includes(`/mobile.js?v=${version}`)) {
  console.error(`The package's page isn't from version ${version}`);
  process.exit(1);
}
console.log(`The app package has everything it needs (version ${version})`);
