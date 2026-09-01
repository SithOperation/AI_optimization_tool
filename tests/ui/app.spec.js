import { test, expect } from '@playwright/test';

const pages = ['overview','usage','costs','models','forecasts','optimization','anomalies','budgets','scenario','reports','integrations','settings','import','pricing'];

async function completeSetup(request) {
  await request.put('http://127.0.0.1:8000/api/v1/application/setup', {
    data: { choice: 'demo', privacy: {} },
  });
}

test('first-run wizard renders with private defaults', async ({ page, request }) => {
  await request.delete('http://127.0.0.1:8000/api/v1/application/setup');
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Understand, forecast, and optimize AI usage.' })).toBeVisible();
  await page.getByRole('button', { name: 'Get Started' }).click();
  await page.getByRole('button', { name: /Explore Demo Data/ }).click();
  await page.getByRole('button', { name: 'Continue' }).click();
  await expect(page.getByText('Your metadata stays local.')).toBeVisible();
  await expect(page.locator('#wizard-content')).not.toBeChecked();
  await page.getByRole('button', { name: 'Finish Setup' }).click();
  await expect(page.getByText('DEMO DATA', { exact: true })).toBeVisible();
});

test('major pages navigate without fatal errors or viewport overflow', async ({ page, request }) => {
  await completeSetup(request);
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  for (const name of pages) {
    await page.goto(`/?smoke=${name}#${name}`);
    await page.waitForFunction(() => document.querySelector('.shell') || document.querySelector('.error-state'), null, { timeout: 15000 }).catch(() => {});
    if (!(await page.locator('.shell').count())) {
      throw new Error(`${name} did not render: ${errors.join('; ') || 'no browser exception was reported'}`);
    }
    await expect(page.locator('.shell'), `${name} did not finish loading`).toBeVisible({ timeout: 15000 });
    await expect(page.locator('.error-state')).toHaveCount(0);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `${name} has horizontal viewport overflow`).toBeLessThanOrEqual(1);
  }
  expect(errors).toEqual([]);
});

test('application modes switch and persist', async ({ page, request }) => {
  await completeSetup(request);
  await page.goto('/#overview');
  for (const mode of ['Executive','Operations','Engineering']) {
    await page.getByRole('button', { name: mode }).click();
    await expect(page.locator(`.mode-${mode.toLowerCase()}`)).toBeVisible();
  }
  await page.reload();
  await expect(page.locator('.mode-engineering')).toBeVisible();
});

test('long telemetry values remain contained', async ({ page, request }) => {
  await completeSetup(request);
  const long = suffix => `release-candidate-${suffix}-with-an-intentionally-long-value-that-must-not-break-layout`;
  await request.post('http://127.0.0.1:8000/api/v1/events', {
    data: {
      application: long('application'),
      workload: long('workload'),
      team: long('team'),
      provider: long('provider').slice(0, 80),
      model: long('model'),
      input_tokens: 1000,
      output_tokens: 200,
    },
  });
  for (const name of ['usage','models','pricing']) {
    await page.goto(`/#${name}`);
    await expect(page.locator('.shell')).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `${name} overflows with long values`).toBeLessThanOrEqual(1);
  }
});

for (const name of ['overview','pricing','models','forecasts','scenario']) {
  test(`${name} layout screenshot`, async ({ page, request }, testInfo) => {
    await completeSetup(request);
    await page.goto(`/#${name}`);
    await expect(page.locator('.shell')).toBeVisible();
    await expect(page).toHaveScreenshot(`${testInfo.project.name}-${name}.png`, { fullPage: true, animations: 'disabled', maxDiffPixelRatio: 0.02 });
  });
}
