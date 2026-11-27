/**
 * Shared helper to start, stop, and restart the disposable mock FastAPI stack for
 * the Playwright Test CI slice (local ticket 05). Managing the process directly
 * (instead of Playwright's webServer) lets a test perform a real backend restart
 * and prove that saved work survives it.
 */
import { spawn, type ChildProcess } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '../../..');
const STACK_SCRIPT = path.join(ROOT, 'tests', 'browser', 'disposable_stack.py');
// CI has no project .venv, so the interpreter is overridable (e.g. PW_PYTHON=python3).
const STACK_PYTHON = process.env.PW_PYTHON ?? path.join(ROOT, '.venv', 'bin', 'python');

export interface Stack {
  /** Origin the stack serves, used as the page base URL. */
  url: string;
  /** Stop the server and its served uvicorn child. */
  stop: () => Promise<void>;
  /** Restart the server against the same workspace so saved data survives. */
  restart: () => Promise<void>;
}

async function waitReady(port: number, timeoutMs = 60_000): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/v1/ready`, { cache: 'no-store' });
      if (response.ok) return;
    } catch {
      /* server not up yet */
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`disposable stack on port ${port} did not become ready`);
}

function startChild(
  port: number,
  workspaceDir: string,
  options: { registeredIdentity?: boolean; cancellableTurns?: boolean } = {},
): ChildProcess {
  if (options.registeredIdentity && options.cancellableTurns) {
    throw new Error('registeredIdentity and cancellableTurns are mutually exclusive stack modes');
  }
  const logFile = path.join(workspaceDir, 'stack.log');
  const child = spawn(
    STACK_PYTHON,
    [STACK_SCRIPT],
    {
      cwd: ROOT,
      env: {
        ...process.env,
        PW_STACK_HOST: '127.0.0.1',
        PW_STACK_PORT: String(port),
        CO_DESIGN_STACK_DIR: workspaceDir,
        MODEL_PROVIDER: 'mock',
        MOCK_OPENAI: 'true',
        OPENAI_API_KEY: '',
        // Serve the deterministic registered-identity boundary instead of the
        // plain mock app so a spec can exercise a synthetic registered student.
        ...(options.registeredIdentity ? { PW_REGISTERED_IDENTITY: '1' } : {}),
        // Serve the cancellable-turn fixture so a spec can click the real Stop
        // control against a paused mock workflow (see cancellable_stack_app.py).
        ...(options.cancellableTurns ? { PW_STACK_APP: 'cancellable_stack_app' } : {}),
      },
      stdio: ['ignore', fs.openSync(logFile, 'a'), fs.openSync(logFile, 'a')],
    },
  );
  child.on('error', (error) => {
    throw new Error(`disposable stack failed to start: ${error.message}`);
  });
  return child;
}

/** Start the disposable stack on a fixed loopback port against a persistent workspace. */
export async function startStack(
  dir: string,
  port = 8123,
  options: { registeredIdentity?: boolean; cancellableTurns?: boolean } = {},
): Promise<Stack> {
  fs.mkdirSync(dir, { recursive: true });
  let child = startChild(port, dir, options);

  const stop = async (): Promise<void> => {
    await new Promise<void>((resolve) => {
      child.once('exit', () => resolve());
      child.kill('SIGTERM');
    });
  };

  const restart = async (): Promise<void> => {
    await stop();
    child = startChild(port, dir, options);
    await waitReady(port);
  };

  await waitReady(port);
  return { url: `http://127.0.0.1:${port}`, stop, restart };
}

/** A fresh, uniquely-named temporary workspace for a single test run. */
export function tempWorkspace(prefix = 'codesign-pw-'): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}
