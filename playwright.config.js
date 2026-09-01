import { defineConfig } from '@playwright/test';
import path from 'node:path';

const dataDir = path.resolve('.test-data/playwright');

export default defineConfig({
  testDir: './tests/ui',
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : 'list',
  snapshotPathTemplate: '{testDir}/__screenshots__/{arg}{ext}',
  use: { baseURL: 'http://127.0.0.1:3000', trace: 'retain-on-failure' },
  webServer: [
    {
      command: 'python -m uvicorn tokenscope_api.main:app --app-dir apps/api --host 127.0.0.1 --port 8000',
      url: 'http://127.0.0.1:8000/api/v1/health',
      env: { ...process.env, AIOPT_DATA_DIR: dataDir },
      reuseExistingServer: !process.env.CI,
      timeout: 120000,
    },
    {
      command: 'npm run dev -- --host 127.0.0.1 --port 3000',
      url: 'http://127.0.0.1:3000',
      reuseExistingServer: !process.env.CI,
      timeout: 120000,
    },
  ],
  projects: [
    { name: 'desktop-1920', use: { browserName: 'chromium', viewport: { width: 1920, height: 1080 } } },
    { name: 'minimum-1100', use: { browserName: 'chromium', viewport: { width: 1100, height: 700 } } },
    { name: 'scale-125', use: { browserName: 'chromium', viewport: { width: 1100, height: 700 }, deviceScaleFactor: 1.25 } },
    { name: 'scale-150', use: { browserName: 'chromium', viewport: { width: 1100, height: 700 }, deviceScaleFactor: 1.5 } },
    { name: 'scale-200', use: { browserName: 'chromium', viewport: { width: 1100, height: 700 }, deviceScaleFactor: 2 } },
  ],
});
