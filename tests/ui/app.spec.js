import { test, expect } from '@playwright/test';

const pages = ['overview','usage','costs','models','forecasts','optimization','anomalies','budgets','scenario','reports','integrations','settings','import','pricing'];

test('all inner pages maintain readable text and usable controls', async ({ page, request }, testInfo) => {
  await completeSetup(request);
  const measurements = [];
  for (const name of pages) {
    await page.goto('/#'+name);
    await expect(page.locator('.shell')).toBeVisible();
    const result = await page.evaluate(() => {
      const visible = selector => [...document.querySelectorAll(selector)].filter(node => node.getClientRects().length && node.textContent.trim());
      return {
        body: parseFloat(getComputedStyle(document.body).fontSize),
        small: visible('main p, main label, main small, main button, main th, main td, main .tag').filter(node => parseFloat(getComputedStyle(node).fontSize)<14).map(node => node.className),
        inputs: [...document.querySelectorAll('main input:not([type=checkbox]):not([type=hidden]), main select')].filter(node => node.getClientRects().length).map(node => parseFloat(getComputedStyle(node).fontSize)),
        heading: parseFloat(getComputedStyle(document.querySelector('main h1')).fontSize),
      };
    });
    expect(result.body, name).toBeGreaterThanOrEqual(16);
    expect(result.small, name).toEqual([]);
    expect(result.inputs.every(size => size>=16), name).toBe(true);
    expect(result.heading, name).toBeGreaterThanOrEqual(30);
    measurements.push({page:name,...result});
  }
  await testInfo.attach('readability-page-audit', {body:JSON.stringify(measurements,null,2),contentType:'application/json'});
});

test('administration configuration and diagnostics are real and progressive', async ({page,request}) => {
  await completeSetup(request);
  await page.goto('/#settings');
  await expect(page.getByRole('heading',{name:'Enterprise / Administration'})).toBeVisible();
  await expect(page.locator('#enterprise-form')).toBeHidden();
  await page.getByText('Enterprise deployment configuration',{exact:true}).click();
  await page.getByLabel('Organization name',{exact:true}).fill('UI validation organization');
  await page.getByRole('button',{name:'Save deployment configuration'}).click();
  await expect(page.locator('#administration-status')).toContainText('configuration saved');
  await page.reload();
  await page.getByText('Enterprise deployment configuration',{exact:true}).click();
  await expect(page.getByLabel('Organization name',{exact:true})).toHaveValue('UI validation organization');
  await page.getByText('Diagnostics for IT support',{exact:true}).click();
  await expect(page.locator('#diagnostics-content')).toContainText('0.16.0');
  await expect(page.getByRole('button',{name:'Backup Application Data',exact:true})).toBeVisible();
});

test('destructive modal traps keyboard focus', async ({page,request}) => {
  await completeSetup(request);
  await page.goto('/#settings');
  await page.getByRole('button',{name:'Clear Telemetry Data',exact:true}).click();
  await expect(page.locator('#cancel-telemetry-clear')).toBeFocused();
  await page.keyboard.press('Shift+Tab');
  await expect(page.locator('#confirm-telemetry-clear')).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(page.locator('#cancel-telemetry-clear')).toBeFocused();
  await page.locator('#cancel-telemetry-clear').click();
  await expect(page.getByRole('button',{name:'Clear Telemetry Data',exact:true})).toBeFocused();
});

test('secondary text and table headers have readable contrast in both themes', async ({page,request}) => {
  await completeSetup(request);
  await page.goto('/#usage');
  await expect(page.locator('.analytics-row.head')).toBeVisible();
  for (const light of [false,true]) {
    const ratios=await page.evaluate(light => {
      document.body.classList.toggle('light-theme',light);
      const luminance=color => {
        const rgb=color.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>{v/=255;return v<=0.04045?v/12.92:((v+0.055)/1.055)**2.4;});
        return rgb[0]*0.2126+rgb[1]*0.7152+rgb[2]*0.0722;
      };
      return ['.analytics-row.head','header p','footer'].map(selector=>{
        const node=document.querySelector('main '+selector),fg=luminance(getComputedStyle(node).color);
        const swatch=document.createElement('span');swatch.style.backgroundColor=getComputedStyle(document.querySelector('main')).getPropertyValue('--panel');document.body.append(swatch);
        const bg=luminance(getComputedStyle(swatch).backgroundColor);swatch.remove();
        return (Math.max(fg,bg)+0.05)/(Math.min(fg,bg)+0.05);
      });
    },light);
    expect(ratios.every(ratio=>ratio>=4.5)).toBe(true);
  }
});

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

test('desktop startup recovers after initial fetch failure and retry reaches dashboard', async ({ page, request }) => {
  await completeSetup(request);
  let applicationAttempts = 0;
  await page.route('**/api/v1/application', async route => {
    applicationAttempts += 1;
    if (applicationAttempts <= 2) return route.abort('connectionrefused');
    return route.continue();
  });
  await page.addInitScript(() => {
    let phase = 'failed';
    window.__TAURI__ = { core: { invoke: async command => {
      if (command === 'startup_status') {
        if (phase === 'healthy') return { status: 'HEALTHY', failure: null };
        return { status: 'FAILED', failure: {
          category: 'PORT_IN_USE', summary: 'Port 8000 is already in use by another process.',
          timestamp_unix: 1788220800, backend_executable: 'C:\\Program Files\\AI Optimization Tool\\binaries\\aiopt-backend.exe',
          bind_address: '127.0.0.1:8000', health_check: 'The application refused to attach.',
          child_exit_code: null, application_version: '0.13.0',
        } };
      }
      if (command === 'open_logs') return 'C:\\Users\\test\\AppData\\Local\\AIOptimizationTool\\logs';
      if (command === 'retry_backend') { phase = 'healthy'; return; }
      if (command === 'exit_application') { window.__exitRequested = true; return; }
    } } };
  });
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Unable to start local services.' })).toBeVisible();
  await expect(page.getByText('Your telemetry data has not been deleted.')).toBeVisible();
  await expect(page.locator('#startup-detail-panel')).toBeHidden();
  await page.getByRole('button', { name: 'View Details' }).click();
  await expect(page.getByText('PORT_IN_USE')).toBeVisible();
  await expect(page.getByText('127.0.0.1:8000')).toBeVisible();
  await page.getByRole('button', { name: 'Open Logs' }).click();
  await expect(page.getByRole('status')).toContainText('AIOptimizationTool');
  await page.getByRole('button', { name: 'Retry' }).click();
  await expect(page.getByRole('heading', { name: /Overview/ })).toBeVisible();
  expect(applicationAttempts).toBe(3);
});

test('installed-style healthy startup reaches dashboard through loopback API', async ({ page, request }) => {
  await completeSetup(request);
  await page.addInitScript(() => {
    window.__TAURI__ = { core: { invoke: async command => {
      if (command === 'startup_status') return { status: 'HEALTHY', failure: null };
    } } };
  });
  const applicationRequest = page.waitForRequest('http://127.0.0.1:8000/api/v1/application');
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /Overview/ })).toBeVisible();
  expect((await applicationRequest).url()).toBe('http://127.0.0.1:8000/api/v1/application');
  await expect(page.locator('.error-state')).toHaveCount(0);
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

test('sidebar, import controls, and required desktop sizes remain readable', async ({ page, request }, testInfo) => {
  test.skip(testInfo.project.name !== 'desktop-1920', 'Run viewport matrix once.');
  await completeSetup(request);
  for (const viewport of [
    { width: 1920, height: 1080 },
    { width: 1600, height: 900 },
    { width: 1366, height: 768 },
  ]) {
    await page.setViewportSize(viewport);
    await page.goto('/#import');
    await expect(page.getByRole('navigation')).toBeVisible();
    await expect(page.getByRole('link', { name: 'Import Data' })).toHaveClass(/active/);
    await expect(page.getByRole('heading', { level: 1, name: 'Import telemetry' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Browse Files' })).toBeVisible();
    await expect(page.locator('#file-input')).toHaveAttribute('accept', '.csv,.json,.jsonl');
    await expect(page.getByText('CSV · JSON · Up to 500 MB · Processed locally')).toBeVisible();
    const dimensions = await page.evaluate(() => ({
      overflow: document.documentElement.scrollWidth - innerWidth,
      bodySize: parseFloat(getComputedStyle(document.body).fontSize),
      navSize: parseFloat(getComputedStyle(document.querySelector('nav a')).fontSize),
    }));
    expect(dimensions.overflow, `${viewport.width}x${viewport.height} overflows`).toBeLessThanOrEqual(1);
    expect(dimensions.bodySize).toBeGreaterThanOrEqual(15);
    expect(dimensions.navSize).toBeGreaterThanOrEqual(15);
  }
});

test('desktop tray preference renders and persists through the native command', async ({ page, request }) => {
  await completeSetup(request);
  const calls = [];
  await page.addInitScript(() => {
    window.__trayEnabled = false;
    window.__TAURI__ = { core: { invoke: async (command, args) => {
      if (command === 'startup_status') return { status: 'HEALTHY', failure: null };
      if (command === 'get_keep_running_in_tray') return window.__trayEnabled;
      if (command === 'set_keep_running_in_tray') {
        window.__trayEnabled = args.enabled;
        window.__trayCalls = [...(window.__trayCalls || []), args.enabled];
      }
    } } };
  });
  await page.goto('/#settings');
  const setting = page.getByLabel('Keep running in system tray when closed');
  await expect(setting).not.toBeChecked();
  await setting.check();
  calls.push(...await page.evaluate(() => window.__trayCalls || []));
  expect(calls).toEqual([true]);
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

test('settings telemetry reset requires confirmation and refreshes clean baseline', async ({ page, request }) => {
  await completeSetup(request);
  let deleteCalls = 0;
  let cleared = false;
  await page.route('**/api/v1/telemetry', async route => {
    deleteCalls += 1;
    cleared = true;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ success: true, deleted: { telemetry_events: 1, import_jobs: 1, forecast_runs: 1 } }),
    });
  });
  await page.route('**/api/v1/overview?**', async route => {
    if (!cleared) return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ period_days: 30, is_empty: true, is_demo: false, totals: { requests: 0, tokens: 0, spend: 0, average_latency_ms: 0, success_rate: 0 }, models: [], applications: [], timeseries: [] }),
    });
  });
  await page.goto('/#settings');
  await expect(page.getByRole('button', { name: 'Clear Telemetry Data' })).toBeVisible();
  await page.getByRole('button', { name: 'Clear Telemetry Data' }).click();
  await expect(page.getByRole('dialog', { name: 'Clear Telemetry Data' })).toBeVisible();
  await expect(page.getByText('This permanently removes imported telemetry and telemetry-derived analysis from this device. Application settings and configuration will be preserved.')).toBeVisible();
  await page.getByRole('button', { name: 'Cancel' }).click();
  expect(deleteCalls).toBe(0);
  await page.getByRole('button', { name: 'Clear Telemetry Data' }).click();
  const telemetryDelete = page.waitForRequest(req => req.method() === 'DELETE' && req.url().endsWith('/api/v1/telemetry'));
  await page.getByRole('button', { name: 'Clear Telemetry', exact: true }).click();
  await telemetryDelete;
  await expect(page.getByText('Telemetry cleared. Baseline restored.')).toBeVisible();
  expect(deleteCalls).toBe(1);
  await page.goto('/#overview');
  await expect(page.getByRole('heading', { name: 'Welcome to TokenScope' })).toBeVisible();
});

test('telemetry reset cannot double-submit and shows readable API errors', async ({ page, request }) => {
  await completeSetup(request);
  let deleteCalls = 0;
  await page.route('**/api/v1/telemetry', async route => {
    deleteCalls += 1;
    await new Promise(resolve => setTimeout(resolve, 300));
    await route.fulfill({
      status: 422,
      contentType: 'application/json',
      body: JSON.stringify({ detail: [{ loc: ['body', 'telemetry'], msg: 'Field required', type: 'missing' }] }),
    });
  });
  await page.goto('/#settings');
  await page.getByRole('button', { name: 'Clear Telemetry Data' }).click();
  const confirm = page.getByRole('button', { name: 'Clear Telemetry', exact: true });
  await confirm.dblclick();
  await expect(page.getByRole('button', { name: 'Clearing...' })).toBeDisabled();
  await expect(page.getByText('Field required: telemetry')).toBeVisible();
  await expect(page.getByText('[object Object]')).toHaveCount(0);
  expect(deleteCalls).toBe(1);
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
