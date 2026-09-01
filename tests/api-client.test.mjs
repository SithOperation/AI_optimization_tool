import assert from 'node:assert/strict';
import test from 'node:test';

import { apiRequest, formatApiError } from '../src/api-client.js';
import { createUploadFormData } from '../src/import-workflow.js';

test('multipart upload uses the file field without overriding the boundary', async () => {
  const originalFetch = globalThis.fetch;
  let captured;
  globalThis.fetch = async (url, options) => {
    captured = { url, options };
    return new Response(JSON.stringify({ uploaded: 3 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };

  try {
    const file = new File(['a,b'], 'sample.csv');
    const formData = createUploadFormData(file, file);
    await apiRequest('/api/v1', '/import/test-id/upload', {
      method: 'POST',
      body: formData,
    });

    assert.equal(captured.url, '/api/v1/import/test-id/upload');
    assert.deepEqual([...captured.options.body.keys()], ['file']);
    assert.equal(captured.options.headers.has('Content-Type'), false);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test('FastAPI detail strings and validation arrays are readable', () => {
  assert.equal(formatApiError({ detail: 'Import not found' }, 404), 'Import not found');
  assert.equal(
    formatApiError({
      detail: [{ loc: ['body', 'file'], msg: 'Field required', type: 'missing' }],
    }, 422),
    'Field required: file',
  );
});

test('structured upload errors never render as [object Object]', async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    detail: [{ loc: ['body', 'file'], msg: 'Field required', type: 'missing' }],
  }), {
    status: 422,
    headers: { 'Content-Type': 'application/json' },
  });

  try {
    await assert.rejects(
      apiRequest('/api/v1', '/import/test-id/upload', { method: 'POST', body: new FormData() }),
      (error) => {
        assert.equal(error.status, 422);
        assert.equal(error.message, 'Field required: file');
        assert.equal(error.message.includes('[object Object]'), false);
        return true;
      },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
});
