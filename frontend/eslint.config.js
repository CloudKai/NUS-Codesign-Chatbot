/**
 * Minimal deterministic ESLint flat config for CI (ticket 46).
 *
 * Scope: the hand-written student frontend source and test files. The
 * OpenAPI-generated client under `src/api/generated/` is never hand-edited
 * (ticket 33 quirk: the generator re-emits `" 3"`-suffixed duplicates), so it
 * and the disposable Playwright fixture helpers are excluded rather than
 * linted. Rules stay at `recommended` — no stylistic or type-aware rules — so
 * findings stay small, valid and fixable without suppressing real problems.
 */
import tseslint from 'typescript-eslint';

export default tseslint.config(
  {
    ignores: ['dist/**', 'node_modules/**', 'coverage/**', 'src/api/generated/**', 'tests/browser/dbg_*.mjs'],
  },
  ...tseslint.configs.recommended.map(config => ({
    ...config,
    files: ['src/**/*.{ts,tsx}', 'tests/**/*.ts', 'scripts/**/*.mjs', '*.mts', '*.ts'],
  })),
  {
    files: ['src/**/*.{ts,tsx}', 'tests/**/*.ts', 'scripts/**/*.mjs', '*.mts', '*.ts'],
    rules: {
      // The generated-client boundary intentionally re-exports `any` payloads;
      // hand-written call sites narrow them behind typed views.
      '@typescript-eslint/no-explicit-any': 'off',
      '@typescript-eslint/no-unused-vars': ['error', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
    },
  },
);
