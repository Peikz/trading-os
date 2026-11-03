// A fetch stub for page tests: routes are (method, path prefix) -> body or a function of the
// request. Records every call so a test can check what was sent.
type Handler = unknown | ((url: string, body: unknown) => unknown);

export interface Call {
  method: string;
  url: string;
  body: unknown;
}

export function mockApi(routes: Record<string, Handler>): Call[] {
  const calls: Call[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      calls.push({ method, url, body });
      // The longest matching "METHOD /path" prefix wins
      const key = Object.keys(routes)
        .filter((k) => {
          const [m, path] = k.split(" ");
          return m === method && url.startsWith(path);
        })
        .sort((a, b) => b.length - a.length)[0];
      if (!key) return new Response(JSON.stringify({ detail: `no route ${method} ${url}` }), { status: 404 });
      const h = routes[key];
      const out = typeof h === "function" ? (h as (u: string, b: unknown) => unknown)(url, body) : h;
      return new Response(JSON.stringify(out), { status: 200 });
    }),
  );
  return calls;
}
