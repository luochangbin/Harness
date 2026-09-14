import fs from 'node:fs/promises';
import { after } from 'node:test';

const created = new Set();
const mkdtemp = fs.mkdtemp.bind(fs);
fs.mkdtemp = async (...args) => {
  const directory = await mkdtemp(...args);
  created.add(directory);
  return directory;
};

after(async () => {
  await Promise.all([...created].map(directory => fs.rm(directory, { recursive: true, force: true })));
});
