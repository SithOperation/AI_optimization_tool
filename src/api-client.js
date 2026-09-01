function validationMessage(issue) {
  if (!issue || typeof issue !== 'object') return String(issue ?? '');

  const message = typeof issue.msg === 'string' ? issue.msg : 'Validation error';
  const location = Array.isArray(issue.loc)
    ? issue.loc.filter((part) => part !== 'body').map(String)
    : [];

  return location.length ? `${message}: ${location.join('.')}` : message;
}

export function formatApiError(body, status) {
  const detail = body?.detail;

  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map(validationMessage).filter(Boolean);
    if (messages.length) return messages.join('; ');
  }
  if (detail && typeof detail === 'object') return validationMessage(detail);
  if (typeof body === 'string' && body.trim()) return body;
  if (typeof body?.message === 'string' && body.message.trim()) return body.message;

  return `Request failed (${status})`;
}

async function readResponseBody(response) {
  const text = await response.text();
  if (!text) return null;

  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function apiRequest(apiBase, path, options = {}) {
  const headers = new Headers(options.headers || {});
  const isFormData = typeof FormData !== 'undefined' && options.body instanceof FormData;

  // The user agent must set the multipart boundary for FormData requests.
  if (options.body && !isFormData && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(apiBase + path, { ...options, headers });
  const body = await readResponseBody(response);
  if (!response.ok) {
    const error = new Error(formatApiError(body, response.status));
    error.status = response.status;
    error.body = body;
    throw error;
  }
  return body;
}
