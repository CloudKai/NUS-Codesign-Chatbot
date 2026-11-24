/** Regenerate into a temporary directory and compare all files without rewriting source. */
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, relative } from 'node:path';

const directory = mkdtempSync(join(tmpdir(), 'codesign-api-check-'));
function files(path, base = path) {
  return readdirSync(path, { withFileTypes: true }).flatMap(entry => {
    const child = join(path, entry.name);
    return entry.isDirectory() ? files(child, base) : [relative(base, child)];
  }).sort();
}
try {
  const manifest = JSON.parse(readFileSync('node_modules/@hey-api/openapi-ts/package.json', 'utf8'));
  const entry = join('node_modules/@hey-api/openapi-ts', manifest.bin['openapi-ts']);
  const result = spawnSync(process.execPath, [entry,
    '--file', 'openapi-ts.config.ts', '--output', directory], { stdio: 'inherit' });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error('API generation failed');
  const checked = 'src/api/generated';
  const expected = files(checked);
  const actual = files(directory);
  if (JSON.stringify(expected) !== JSON.stringify(actual)
    || expected.some(file => !readFileSync(join(checked, file)).equals(readFileSync(join(directory, file))))) {
    throw new Error('Generated reader client drift: run npm run api:generate');
  }
} finally {
  rmSync(directory, { recursive: true, force: true });
}
