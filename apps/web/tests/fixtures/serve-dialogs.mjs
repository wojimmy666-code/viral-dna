import { createServer } from 'node:http';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

// Memory-only fixture server. Stop with Ctrl+C after browser verification.
const root = fileURLToPath(new URL('../../', import.meta.url));
const bundle = await build({ absWorkingDir: root, entryPoints: ['tests/fixtures/dialog-showcase.jsx'], bundle: true, write: false,
  outfile: 'fixture.js', format: 'esm', platform: 'browser', jsx: 'automatic', define: { 'process.env.NODE_ENV': '"production"' } });
const js = bundle.outputFiles.find(file => file.path.endsWith('.js')).text;
const css = bundle.outputFiles.find(file => file.path.endsWith('.css')).text;
const html = '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>弹窗隔离验收</title><link rel="stylesheet" href="/fixture.css"></head><body><div id="root"></div><script type="module" src="/fixture.js"></script></body></html>';
const server = createServer((req, res) => {
  if (req.method !== 'GET' || req.url.startsWith('/api')) { res.writeHead(405); res.end('Fixture denies all backend writes'); return; }
  res.setHeader('Content-Type', req.url === '/fixture.js' ? 'text/javascript' : req.url === '/fixture.css' ? 'text/css' : 'text/html; charset=utf-8');
  res.end(req.url === '/fixture.js' ? js : req.url === '/fixture.css' ? css : html);
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
console.log(`Dialog fixture: http://127.0.0.1:${server.address().port}`);
