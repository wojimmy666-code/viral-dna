import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// Read-only: validates repository documentation, never crawls external sites.
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const slash = value => value.split(path.sep).join('/');
const relative = value => slash(path.relative(root, value));

function withoutFences(text) {
  let fence = null;
  return text.split(/\r?\n/).map(line => {
    const match = /^\s{0,3}(\x60{3,}|~{3,})/.exec(line);
    if (match) {
      if (!fence) fence = match[1];
      else if (match[1][0] === fence[0] && match[1].length >= fence.length) fence = null;
      return '';
    }
    return fence ? '' : line;
  }).join('\n');
}

function links(text) {
  const clean = withoutFences(text);
  const result = [];
  const inline = /!?\[[^\]]*\]\(\s*(?:<([^>]+)>|([^\s)]+))(?:\s+["'][^"']*["'])?\s*\)/g;
  for (const match of clean.matchAll(inline)) result.push(match[1] ?? match[2]);
  for (const match of clean.matchAll(/^\s{0,3}\[[^\]]+\]:\s*(?:<([^>]+)>|(\S+))/gm)) {
    result.push(match[1] ?? match[2]);
  }
  // Legacy QA reports use literal repository-root paths, not Markdown links.
  for (const match of clean.matchAll(/\x60((?:\.\/)?docs\/[^\x60\r\n]+)\x60/g)) {
    result.push('/' + match[1].replace(/^\.\//, ''));
  }
  return result;
}

function anchors(text) {
  const found = new Set();
  const counts = new Map();
  const clean = withoutFences(text);
  for (const match of clean.matchAll(/^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$/gm)) {
    const base = match[1].replace(/<[^>]+>/g, '').toLowerCase()
      .replace(/[^\p{L}\p{N}\p{M}_ -]/gu, '').replace(/ /g, '-');
    const count = counts.get(base) ?? 0;
    counts.set(base, count + 1);
    found.add(base + (count ? '-' + count : ''));
  }
  for (const match of clean.matchAll(/\b(?:id|name)=["']([^"']+)["']/g)) found.add(match[1]);
  return found;
}

function filesUnder(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap(entry => {
    const selected = path.join(directory, entry.name);
    return entry.isDirectory() ? filesUnder(selected) : entry.isFile() ? [selected] : [];
  });
}

function localTarget(from, url) {
  if (/^(?:[a-z][a-z0-9+.-]*:|\/\/)/i.test(url)) return null;
  const hash = url.indexOf('#');
  const fragment = hash < 0 ? '' : decodeURIComponent(url.slice(hash + 1));
  const pathname = decodeURIComponent((hash < 0 ? url : url.slice(0, hash)).split('?')[0]);
  const target = !pathname ? from
    : pathname.startsWith('/') ? path.resolve(root, '.' + pathname)
      : path.resolve(path.dirname(from), pathname);
  const inRepo = path.relative(root, target);
  if (inRepo === '..' || inRepo.startsWith('..' + path.sep) || path.isAbsolute(inRepo)) {
    throw new Error('link escapes the repository: ' + url);
  }
  return { target, fragment };
}

function selfTest() {
  const tick = String.fromCharCode(96);
  assert.deepEqual(links('[图](../图.png) [文](<中文 空格.md>) [外](https://example.com)'),
    ['../图.png', '中文 空格.md', 'https://example.com']);
  assert.deepEqual(links(tick.repeat(3) + '\n[忽略](missing.md)\n' + tick.repeat(3) +
    '\n[保留](ok.md)\n' + tick + 'docs/README.md' + tick), ['ok.md', '/docs/README.md']);
  assert.deepEqual(links('[ref]: docs/README.md'), ['docs/README.md']);
  assert.deepEqual([...anchors('# 标题\n## 标题\n## Hello, World!')], ['标题', '标题-1', 'hello-world']);
  const from = path.join(root, 'docs', 'README.md');
  assert.equal(localTarget(from, 'https://example.com/docs/a'), null);
  assert.equal(localTarget(from, '../README.md').target, path.join(root, 'README.md'));
  assert.equal(localTarget(from, '中文%20空格.md#标题').fragment, '标题');
  assert.throws(() => localTarget(from, '../../outside.md'), /escapes/);
  assert.throws(() => localTarget(from, '%xx.md'), URIError);
}

if (process.argv.includes('--self-test')) {
  selfTest();
  console.log('Documentation checker self-tests passed.');
} else {
  const docFiles = filesUnder(path.join(root, 'docs'));
  const markdown = [...docFiles.filter(file => file.endsWith('.md')),
    path.join(root, 'README.md'), path.join(root, 'design-qa.md')];
  const errors = [];
  const graph = new Map();
  let checked = 0;
  for (const file of markdown) {
    const edges = new Set();
    for (const url of links(readFileSync(file, 'utf8'))) {
      try {
        const resolved = localTarget(file, url);
        if (!resolved) continue;
        checked += 1;
        const info = statSync(resolved.target);
        edges.add(resolved.target);
        if (resolved.fragment && info.isFile() && resolved.target.endsWith('.md') &&
            !anchors(readFileSync(resolved.target, 'utf8')).has(resolved.fragment)) {
          throw new Error('missing heading: ' + url);
        }
      } catch (error) {
        errors.push(relative(file) + ': ' + url + ' — ' + error.message);
      }
    }
    graph.set(file, edges);
  }
  const visited = new Set();
  const queue = [path.join(root, 'docs', 'README.md')];
  while (queue.length) {
    const file = queue.pop();
    if (visited.has(file)) continue;
    visited.add(file);
    queue.push(...(graph.get(file) ?? []));
  }
  for (const file of docFiles) {
    if (!visited.has(file)) errors.push('Not reachable from docs/README.md: ' + relative(file));
  }
  for (const entry of readdirSync(path.join(root, 'docs'), { withFileTypes: true })) {
    if (entry.isFile() && entry.name !== 'README.md') errors.push('Loose docs root file: ' + entry.name);
  }
  if (errors.length) {
    console.error(errors.join('\n'));
    process.exitCode = 1;
  } else {
    console.log('Documentation checks passed: ' + docFiles.length + ' files indexed, ' +
      checked + ' local links/references checked; external URLs not requested.');
  }
}
