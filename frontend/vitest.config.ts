/** Vitest runs the unit specs under src/ only; Playwright specs live in tests/browser/. */
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
});
