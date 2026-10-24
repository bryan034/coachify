import { defineConfig, devices } from '@playwright/test';

if (!process.env.MAILPIT_BASE_URL) throw new Error('Set MAILPIT_BASE_URL to the disposable local test inbox.');
if (!process.env.PROFILE_E2E_BASE_URL) throw new Error('Set PROFILE_E2E_BASE_URL to a disposable local-test gateway. These tests save profile data.');
export default defineConfig({
  outputDir: './test-results/integration',
  testDir: './tests/integration',
  forbidOnly: !!process.env.CI,
  workers: 1,
  retries: 0,
  reporter: 'list',
  use: { baseURL: process.env.PROFILE_E2E_BASE_URL, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
});
