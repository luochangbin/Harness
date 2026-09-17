import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtemp, readFile, readdir, rm } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const root = resolve(import.meta.dirname, '..');
const readJson = async (relativePath) =>
  JSON.parse(await readFile(resolve(root, relativePath), 'utf8'));

const portableManifest = await readJson('plugin/codex-workflow/plugin.json');
const portableMcp = await readJson('plugin/codex-workflow/mcp.json');
const compatibilityManifest = await readJson('plugin/codex-workflow/.codex-plugin/plugin.json');
const packagedCompatibilityManifest = await readJson('dist/codex-workflow-plugin/.codex-plugin/plugin.json');
const buildScript = await readFile(resolve(root, 'scripts/build-codex-workflow-plugin.mjs'), 'utf8');

assert.equal(
  portableManifest.$schema,
  'https://agent-plugins.org/schemas/1.0.0/plugin.schema.json',
  'portable plugin.json must declare the Agent Plugins schema'
);
assert.equal(portableManifest.extensions?.['com.openai']?.interface?.displayName, 'Codex Workflow');
assert.equal(portableManifest.skills, undefined, 'portable manifest must use fixed component discovery');
assert.equal(portableManifest.mcpServers, undefined, 'portable manifest must use fixed component discovery');
assert.equal(portableManifest.interface, undefined, 'OpenAI metadata must be under extensions.com.openai');
assert.equal(compatibilityManifest.name, portableManifest.name, 'source manifests must use the same plugin name');
assert.equal(compatibilityManifest.version, portableManifest.version, 'source manifests must use the same plugin version');
assert.equal(packagedCompatibilityManifest.name, portableManifest.name, 'packaged compatibility manifest must use the public plugin name');
assert.equal(packagedCompatibilityManifest.version, portableManifest.version, 'packaged compatibility manifest must use the public plugin version');

assert.equal(
  portableMcp.$schema,
  'https://agent-plugins.org/schemas/1.0.0/mcp.schema.json',
  'portable mcp.json must declare the Agent Plugins schema'
);
const server = portableMcp.mcpServers?.['codex-workflow-opencode'];
assert.equal(server?.type, 'stdio', 'bundled MCP must explicitly select stdio transport');
assert.equal(server?.args?.[0], '${PLUGIN_ROOT}/mcp/index.js');
assert.equal(server?.cwd, '${PLUGIN_ROOT}');

assert.equal(compatibilityManifest.mcpServers, './.mcp.json');
assert.equal(
  buildScript.includes("resolve(root, 'plugin/codex-workflow/.codex-plugin/plugin.json')"),
  true,
  'build must copy the compatibility manifest from its own source'
);
assert.equal(
  buildScript.includes("resolve(root, 'plugin/codex-workflow/.mcp.json')"),
  true,
  'build must copy the compatibility MCP config from its own source'
);
assert.equal(buildScript.includes('manifest.skills ='), false);
assert.equal(buildScript.includes('manifest.mcpServers ='), false);

const skillRoot = resolve(root, 'codex-workflow');
const packagedSkill = resolve(root, 'dist/codex-workflow-plugin/skills/codex-workflow');
async function filesUnder(directory, prefix = '') {
  const result = [];
  for (const entry of await readdir(resolve(directory, prefix), { withFileTypes: true })) {
    const relative = prefix ? prefix + '/' + entry.name : entry.name;
    if (['__pycache__', '.pytest_cache', '.mypy_cache'].includes(entry.name) ||
        entry.name.endsWith('.pyc') || entry.name.endsWith('.pyo') || entry.name.endsWith('.tmp')) continue;
    if (entry.isDirectory()) result.push(...await filesUnder(directory, relative));
    else result.push(relative);
  }
  return result.sort();
}
async function digest(file) {
  return createHash('sha256').update(await readFile(file)).digest('hex');
}

const exec = promisify(execFile);
async function bundleFreshMcp(outputFile) {
  const mcpRoot = resolve(root, 'codex-workflow-mcp');
  const esbuild = process.platform === 'win32'
    ? resolve(mcpRoot, 'node_modules/.bin/esbuild.cmd')
    : resolve(mcpRoot, 'node_modules/.bin/esbuild');
  const args = ['src/index.ts', '--bundle', '--platform=node', '--format=esm', '--outfile=' + outputFile];
  if (process.platform === 'win32') {
    await exec('cmd.exe', ['/d', '/s', '/c', esbuild, ...args], { cwd: mcpRoot });
  } else {
    await exec(esbuild, args, { cwd: mcpRoot });
  }
}
const sourceFiles = await filesUnder(skillRoot);
const packagedFiles = await filesUnder(packagedSkill);
assert.deepEqual(packagedFiles, sourceFiles, 'packaged Skill file set must match source');
for (const relative of sourceFiles) {
  assert.equal(await digest(resolve(packagedSkill, relative)), await digest(resolve(skillRoot, relative)),
    'packaged Skill is stale: ' + relative);
}

const packagedContracts = [
  ['plugin/codex-workflow/plugin.json', 'dist/codex-workflow-plugin/plugin.json'],
  ['plugin/codex-workflow/mcp.json', 'dist/codex-workflow-plugin/mcp.json'],
  ['plugin/codex-workflow/README.md', 'dist/codex-workflow-plugin/README.md'],
  ['plugin/codex-workflow/.codex-plugin/plugin.json', 'dist/codex-workflow-plugin/.codex-plugin/plugin.json'],
  ['plugin/codex-workflow/.mcp.json', 'dist/codex-workflow-plugin/.mcp.json']
];
for (const [source, packaged] of packagedContracts) {
  assert.equal(
    await digest(resolve(root, packaged)),
    await digest(resolve(root, source)),
    'packaged plugin contract is stale: ' + packaged
  );
}
const tempRoot = await mkdtemp(join(process.env.TEMP ?? process.cwd(), 'codex-workflow-package-'));
const freshMcp = resolve(tempRoot, 'mcp-index.js');
try {
  await bundleFreshMcp(freshMcp);
  assert.equal(
    await digest(resolve(root, 'dist/codex-workflow-plugin/mcp/index.js')),
    await digest(freshMcp),
    'packaged MCP bundle is stale'
  );
} finally {
  await rm(tempRoot, { recursive: true, force: true });
}

console.log('plugin package contract passed');
