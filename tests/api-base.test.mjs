import test from 'node:test';
import assert from 'node:assert/strict';
import { desktopProductionApiBase, resolveApiBase } from '../src/api-base.js';

test('installed Tauri production always uses the loopback backend', () => {
  assert.equal(resolveApiBase({ mode: 'production', isTauri: true, viteApiUrl: 'http://wrong-host/api/v1' }), desktopProductionApiBase);
});

test('development API configuration remains overridable', () => {
  assert.equal(resolveApiBase({ mode: 'development', isTauri: true, viteApiUrl: 'http://127.0.0.1:9000/api/v1' }), 'http://127.0.0.1:9000/api/v1');
  assert.equal(resolveApiBase({ mode: 'development', isTauri: false }), desktopProductionApiBase);
});

test('browser production keeps the configured API base', () => {
  assert.equal(resolveApiBase({ mode: 'production', isTauri: false, viteApiUrl: 'http://127.0.0.1:9000/api/v1' }), 'http://127.0.0.1:9000/api/v1');
});