import { handleNodeRequest } from '../../server.js';

function nodeHeaders(requestUrl, requestHeaders) {
  const url = new URL(requestUrl);
  const headers = Object.fromEntries(requestHeaders.entries());
  headers.host ||= url.host;
  headers['x-forwarded-host'] ||= url.host;
  headers['x-forwarded-proto'] ||= url.protocol.replace(':', '');
  return headers;
}

export default async function handler(request) {
  const url = new URL(request.url);
  const req = {
    method: request.method,
    url: url.pathname + url.search,
    headers: nodeHeaders(request.url, request.headers)
  };

  return await new Promise((resolve, reject) => {
    let status = 200;
    let responseHeaders = {};
    let finished = false;

    const res = {
      writeHead(nextStatus, headers = {}) {
        status = Number(nextStatus) || 500;
        responseHeaders = { ...headers };
        return res;
      },
      end(body = '') {
        if (finished) return;
        finished = true;
        const noBody = status === 204 || status === 304;
        resolve(new Response(noBody ? null : body, {
          status,
          headers: responseHeaders
        }));
      }
    };

    Promise.resolve(handleNodeRequest(req, res)).catch(reject);
  });
}

export const config = {
  path: [
    '/',
    '/health',
    '/healthz',
    '/openapi.json',
    '/.well-known/x402',
    '/.well-known/agent.json',
    '/llms.txt',
    '/skill.md',
    '/icon.svg',
    '/api/*'
  ]
};
