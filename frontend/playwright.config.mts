/**
 * Playwright Test configuration for the CDE2300 browser CI slice (local ticket 05).
 *
 * Specs boot the production-built CDE2300 reader frontend and the same-origin
 * disposable mock FastAPI/SQLite stack themselves through
 * `tests/browser/disposable_stack.py` (see frontend/tests/browser/stack.ts).
 * Everything is finite, self-cleaning, non-billable, and bound to loopback:
 *   - deterministic mock provider (see disposable_stack.py guards)
 *   - disposable SQLite + local files under the system temp directory
 *   - Guest / synthetic identity only, never Cognito or paid providers
 *
 * Run the slice with:
 *   npx playwright test --config frontend/playwright.config.mts
 */
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { devices } from '@playwright/test';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// Playwright co-locates its configuration and node_modules inside the frontend
// project; the disposable backend stack and specs live at the repository root.
const ROOT = path.resolve(__dirname, '..');
const SPECS_DIR = path.join(__dirname, 'tests', 'browser');

const host = process.env.PW_STACK_HOST ?? '127.0.0.1';
const port = Number(process.env.PW_STACK_PORT ?? 8123);
const baseUrl = `http://${host}:${port}`;

export default {
  testDir: SPECS_DIR,
  testMatch: /\.spec\.ts$/,
  // The student journey mutates identity and relies on a single browser context.
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 15_000 },
  reporter: [
    ['list'],
    ['html', { outputFolder: path.join(ROOT, 'output', 'playwright', 'report'), open: 'never' }],
    ['json', { outputFile: path.join(ROOT, 'output', 'playwright', 'results.json') }],
  ],
  use: {
    baseURL: baseUrl,
    headless: true,
    screenshot: { mode: 'only-on-failure', fullPage: true },
    viewport: { width: 1440, height: 960 },
    trace: 'off',
    actionTimeout: 15_000,
    navigationTimeout: 20_000,
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
};
