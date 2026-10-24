import { spawnSync } from 'node:child_process';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const cli = require.resolve('@playwright/test/cli');
const args = process.argv.slice(2);
const discovered = spawnSync(process.execPath, [
  cli, 'test', ...args, '--list', '--pass-with-no-tests', '--reporter=json',
], { encoding: 'utf8' });

if (discovered.error) throw discovered.error;
if (discovered.status !== 0) {
  process.stdout.write(discovered.stdout ?? '');
  process.stderr.write(discovered.stderr ?? '');
  process.exit(discovered.status ?? 1);
}

const report = JSON.parse(discovered.stdout);
const hasTests = (suites) => suites.some((suite) =>
  (suite.specs ?? []).some((spec) => (spec.tests ?? []).length > 0)
  || hasTests(suite.suites ?? []));

if (!hasTests(report.suites ?? [])) {
  console.log('No Playwright tests found; passing without building or starting Next.js.');
  process.exit(0);
}

const run = spawnSync(process.execPath, [cli, 'test', ...args], { stdio: 'inherit' });
if (run.error) throw run.error;
process.exit(run.status ?? 1);
