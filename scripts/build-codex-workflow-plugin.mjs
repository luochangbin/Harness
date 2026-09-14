import { cp, mkdir, rm, readdir } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const exec = promisify(execFile);
const root = resolve(import.meta.dirname, '..');
const runNpm = (args, cwd) => process.platform === "win32" ? execFile("cmd.exe", ["/d", "/s", "/c", "npm", ...args], { cwd }) : execFile("npm", args, { cwd });
const runNpmAsync = (args, cwd) => new Promise((resolve, reject) => { const child = runNpm(args, cwd); let stderr = ""; child.stderr?.on("data", d => stderr += d); child.on("error", reject); child.on("close", code => code === 0 ? resolve() : reject(new Error(stderr || `npm exited ${code}`))); });
const runCommandAsync = (file, args, cwd) => new Promise((resolve, reject) => {
  const child = process.platform === "win32"
    ? execFile("cmd.exe", ["/d", "/s", "/c", file, ...args], { cwd })
    : execFile(file, args, { cwd });
  let stderr = "";
  child.stderr?.on("data", data => { stderr += data; });
  child.on("error", reject);
  child.on("close", code => code === 0 ? resolve() : reject(new Error(stderr || file + " exited " + code)));
});
const output = resolve(root, 'dist/codex-workflow-plugin');
await rm(output, { recursive: true, force: true });
await mkdir(output, { recursive: true });
await runNpmAsync(["run", "build"], resolve(root, "codex-workflow-mcp"));
await mkdir(resolve(output, "mcp"), { recursive: true });
const esbuild = process.platform === "win32"
  ? resolve(root, "codex-workflow-mcp/node_modules/.bin/esbuild.cmd")
  : resolve(root, "codex-workflow-mcp/node_modules/.bin/esbuild");
await runCommandAsync(esbuild, ["src/index.ts", "--bundle", "--platform=node", "--format=esm", "--outfile=" + resolve(output, "mcp/index.js")], resolve(root, "codex-workflow-mcp"));
const mcpEntry = resolve(output, "mcp/index.js");
if (!(await import("node:fs/promises")).stat(mcpEntry).catch(() => null)) {
  throw new Error("MCP bundle was not created: " + mcpEntry);
}

const EXCLUDED = new Set(['__pycache__', '.pytest_cache', '.mypy_cache']);
const skillRoot = resolve(root, 'codex-workflow');
const skillFilter = (src) => {
  const name = src.split(/[\\/]/).pop() ?? '';
  if (EXCLUDED.has(name)) return false;
  if (name.endsWith('.pyc') || name.endsWith('.pyo') || name.endsWith('.tmp')) return false;
  return true;
};
await cp(skillRoot, resolve(output, "skills/codex-workflow"), { recursive: true, filter: skillFilter });
const packaged = resolve(output, 'skills/codex-workflow');
for (const entry of await readdir(packaged, { recursive: true })) {
  if (/(^|[\\/])__pycache__([\\/]|$)/.test(entry) || entry.endsWith('.pyc') || entry.endsWith('.pytest_cache')) {
    throw new Error('Packaged Skill leaked build artifacts: ' + entry);
  }
  if (/reasoner|oracle|design-reasoner-prompt/.test(entry)) {
    throw new Error('Packaged Skill leaked Oracle-only resource: ' + entry);
  }
}

await cp(resolve(root, 'plugin/codex-workflow/plugin.json'), resolve(output, 'plugin.json'));
await cp(resolve(root, 'plugin/codex-workflow/mcp.json'), resolve(output, 'mcp.json'));
await cp(resolve(root, 'plugin/codex-workflow/README.md'), resolve(output, 'README.md'));
await cp(resolve(root, 'plugin/codex-workflow/.codex-plugin/plugin.json'), resolve(output, '.codex-plugin/plugin.json'));
await cp(resolve(root, 'plugin/codex-workflow/.mcp.json'), resolve(output, '.mcp.json'));
console.log(`Built ${output}`);
