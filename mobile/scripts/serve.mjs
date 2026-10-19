// Serves www/ for the browser preview and the phone-size browser tests: npm run preview, then open
// http://localhost:8686 (use the browser's phone view). The data stays in that browser.
import { createReadStream, existsSync, statSync } from 'node:fs';
import { createServer } from 'node:http';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const WWW = fileURLToPath(new URL('../www', import.meta.url));
const TYPES = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.json': 'application/json',
  '.png': 'image/png', '.svg': 'image/svg+xml', '.ico': 'image/x-icon', '.woff2': 'font/woff2', '.wasm': 'application/wasm',
  '.map': 'application/json', '.txt': 'text/plain' };

export function serve(port = Number(process.env.PORT) || 8686) {
  const server = createServer((req, res) => {
    const path = decodeURIComponent(new URL(req.url, 'http://x').pathname);
    let file = normalize(join(WWW, path === '/' ? 'index.html' : path));
    if (!file.startsWith(WWW) || !existsSync(file) || statSync(file).isDirectory()) file = join(WWW, 'index.html');
    res.writeHead(200, { 'Content-Type': TYPES[extname(file)] || 'application/octet-stream', 'Cache-Control': 'no-cache' });
    createReadStream(file).pipe(res);
  });
  return new Promise(resolve => server.listen(port, '127.0.0.1', () => resolve(server)));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const server = await serve();
  console.log(`EasyUniTrack phone preview: http://localhost:${server.address().port}`);
}
