export async function apiJson(path, options = {}) {
  const timeoutMs = options.timeoutMs ?? 25000;
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(options.headers || {}),
      },
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.error || `Request failed with ${response.status}`);
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
