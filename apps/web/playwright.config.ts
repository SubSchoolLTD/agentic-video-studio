import { defineConfig, devices } from '@playwright/test'

const externalBaseUrl = process.env.E2E_BASE_URL

export default defineConfig({
  testDir: './tests/e2e',
  outputDir: './test-results',
  timeout: 75_000,
  expect: { timeout: 12_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report', open: 'never' }]],
  use: {
    baseURL: externalBaseUrl || 'http://127.0.0.1:3100',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    { name: 'chromium-desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'chromium-mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: externalBaseUrl ? undefined : [
    {
      command: 'APP_ENV=test APP_AUTH_MODE=jwt JWT_SECRET=framewise-e2e-secret-with-more-than-32-characters TEST_SUPPORT_SECRET=framewise-e2e-support EMAIL_DELIVERY_MODE=log SEED_DEMO_DATA=false PROVIDER_MODE=mock GOOGLE_CLOUD_STORAGE_BUCKET= GOOGLE_PUBSUB_TOPIC= CLICKHOUSE_URL= ALLOWED_ORIGINS=http://127.0.0.1:3100 DATABASE_URL=sqlite:////tmp/avs-e2e-${RANDOM}-${RANDOM}.sqlite3 STORAGE_ROOT=./local_data/e2e_auth_media .venv/bin/uvicorn apps.api.app.main:app --host 127.0.0.1 --port 8100',
      cwd: '../..',
      url: 'http://127.0.0.1:8100/v1/health',
      timeout: 60_000,
      reuseExistingServer: false,
    },
    {
      command: 'NUXT_PUBLIC_API_BASE=http://127.0.0.1:8100 pnpm --filter @avs/web exec nuxt dev --host 127.0.0.1 --port 3100',
      cwd: '../..',
      url: 'http://127.0.0.1:3100',
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
})
