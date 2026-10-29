// Buffer bounded upstream bodies while the deadline remains active.
export async function fetchWithTimeout(url, init = {}, timeoutMs = 10000, maxBytes = 2 * 1024 * 1024) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let reader;
  try {
    const response = await fetch(url, {...init, signal: controller.signal});
    const declared = response.headers.get('content-length');
    if (declared !== null && Number(declared) > maxBytes) throw new Error('upstream_body_too_large');
    reader = response.body?.getReader();
    const chunks = [];
    let bytes = 0;
    if (reader) {
      while (true) {
        const {done, value} = await reader.read();
        if (done) break;
        bytes += value.byteLength;
        if (bytes > maxBytes) throw new Error('upstream_body_too_large');
        chunks.push(value);
      }
    }
    const body = Buffer.concat(chunks, bytes).toString('utf8');
    return {ok: response.ok, status: response.status, headers: response.headers,
      text: async () => body, json: async () => JSON.parse(body)};
  } finally {
    controller.abort();
    if (reader) { await reader.cancel().catch(() => {}); reader.releaseLock(); }
    clearTimeout(timer);
  }
}
