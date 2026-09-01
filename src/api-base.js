const DESKTOP_PRODUCTION_API = 'http://127.0.0.1:8000/api/v1';

export function resolveApiBase({ mode = 'development', viteApiUrl, isTauri = false } = {}) {
  if (isTauri && mode === 'production') return DESKTOP_PRODUCTION_API;
  return viteApiUrl || DESKTOP_PRODUCTION_API;
}

export const desktopProductionApiBase = DESKTOP_PRODUCTION_API;