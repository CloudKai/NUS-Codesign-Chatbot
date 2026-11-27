/**
 * Bundle measurement for the production build (ticket 43). Run after
 * `npm run build`: reads dist/index.html, classifies every emitted asset as
 * referenced by the entry HTML ("entry") versus a dynamic-import chunk
 * ("async"; some async chunks, such as the preloaded markdown renderer, are
 * still fetched at startup — the real per-route downloads are measured in the
 * browser by tests/browser/route_load.spec.ts). Prints raw + gzip bytes so the
 * ledger numbers are reproducible.
 */
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const dist = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'dist');
const html = fs.readFileSync(path.join(dist, 'index.html'), 'utf8');
const entryAssets = [...html.matchAll(/\/pilot\/assets\/[^"']+/g)].map(match => path.basename(match[0]));

function bytes(file) {
  const raw = fs.readFileSync(path.join(dist, 'assets', file));
  return { raw: raw.length, gzip: zlib.gzipSync(raw).length };
}

const rows = fs.readdirSync(path.join(dist, 'assets'))
  .filter(file => /\.(js|css)$/.test(file))
  .sort()
  .map(file => ({ file, phase: entryAssets.includes(file) ? 'entry' : 'async', ...bytes(file) }));

const sum = (rows, key) => rows.reduce((total, row) => total + row[key], 0);
for (const row of rows) {
  console.log(`${row.phase.padEnd(7)} ${String(row.raw).padStart(9)} B ${String(row.gzip).padStart(8)} B gzip  ${row.file}`);
}
for (const phase of ['entry', 'async']) {
  const group = rows.filter(row => row.phase === phase);
  console.log(`${phase.padEnd(7)} ${String(sum(group, 'raw')).padStart(9)} B ${String(sum(group, 'gzip')).padStart(8)} B gzip  (${group.length} assets)`);
}
