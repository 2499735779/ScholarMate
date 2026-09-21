import { existsSync } from 'node:fs';
import { spawn } from 'node:child_process';
import { dirname, join, delimiter } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const env = { ...process.env };
const inheritedPath = Object.entries(process.env).find(([key]) => key.toLowerCase() === 'path')?.[1] || '';
for (const key of Object.keys(env)) if (key.toLowerCase() === 'path') delete env[key];
env.PATH = dirname(process.execPath) + delimiter + inheritedPath;
// Reuse this workspace's isolated tools when present; otherwise use system tools.
const cargo = join(root, '.tools', 'cargo');
if (existsSync(cargo)) {
  env.CARGO_HOME = cargo;
  env.RUSTUP_HOME = join(root, '.tools', 'rustup');
  env.PATH = join(cargo, 'bin') + delimiter + (env.PATH || '');
}
const pythonSuffix = process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python';
for (const venv of ['.venv311', '.venv']) {
  const path = join(root, venv, pythonSuffix);
  if (existsSync(path)) { env.SCHOLARMATE_PYTHON = path; break; }
}
const args = process.argv.slice(2);
const child = args[0] === 'sidecar'
  ? spawn(env.SCHOLARMATE_PYTHON || 'python', [join(root, 'scripts/build_sidecar.py')], { cwd: root, env, stdio: 'inherit' })
  : spawn(process.execPath, [join(root, 'node_modules/@tauri-apps/cli/tauri.js'), ...args], { cwd: root, env, stdio: 'inherit' });
child.on('error', (error) => { console.error(error.message); process.exitCode = 1; });
child.on('exit', (code) => { process.exitCode = code ?? 1; });

