const _cache = new Map(); // path → { data, expiresAt }
const _CACHE_STORAGE_KEY = "xcg-api-cache-v1";

function _persistCache() {
  try {
    window.sessionStorage.setItem(_CACHE_STORAGE_KEY, JSON.stringify(Array.from(_cache.entries())));
  } catch {
    // no-op: best-effort persistence only
  }
}

function _loadCache() {
  try {
    const raw = window.sessionStorage.getItem(_CACHE_STORAGE_KEY);
    if (!raw) return;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return;
    const now = Date.now();
    for (const [path, value] of parsed) {
      if (!path || !value || typeof value.expiresAt !== "number" || value.expiresAt <= now) continue;
      _cache.set(path, value);
    }
  } catch {
    // no-op: best-effort persistence only
  }
}

_loadCache();

export function invalidateCache(path) {
  _cache.delete(path);
  _persistCache();
}

export function peekCache(path) {
  const hit = _cache.get(path);
  if (!hit || hit.expiresAt <= Date.now()) return null;
  return hit.data;
}

export async function apiJson(path, options = {}) {
  const { timeoutMs = 25000, cacheTtlMs, ...fetchOptions } = options;

  if (cacheTtlMs) {
    const hit = _cache.get(path);
    if (hit && hit.expiresAt > Date.now()) return hit.data;
    if (hit && hit.expiresAt <= Date.now()) {
      _cache.delete(path);
      _persistCache();
    }
  }

  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, {
      ...fetchOptions,
      headers: {
        "Content-Type": "application/json",
        ...(fetchOptions.headers || {}),
      },
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || `Request failed with ${response.status}`);
    }
    if (cacheTtlMs) {
      _cache.set(path, { data: payload, expiresAt: Date.now() + cacheTtlMs });
      _persistCache();
    }
    return payload;
  } finally {
    window.clearTimeout(timeout);
  }
}

export function postJson(path, body, options = {}) {
  return apiJson(path, {
    method: "POST",
    body: JSON.stringify(body),
    ...options,
  });
}
