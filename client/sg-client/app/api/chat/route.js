// Server-only proxy to the FastAPI backend in server/src/app.py.
// BACKEND_URL is read on the Next.js server -- never NEXT_PUBLIC_*, so the
// Python host stays invisible to the browser. CORS is therefore a non-issue.
//
// NOTE (Next.js 16.2.6): per client/sg-client/AGENTS.md, verify route-handler
// conventions against node_modules/next/dist/docs/ after `npm install` if
// anything here breaks.

export async function POST(req) {
  let payload;
  try {
    payload = await req.json();
  } catch {
    return Response.json({ error: "invalid json" }, { status: 400 });
  }

  const query = payload?.query;
  if (typeof query !== "string" || !query.trim()) {
    return Response.json({ error: "query required" }, { status: 400 });
  }

  const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

  let upstream;
  try {
    upstream = await fetch(`${backend}/answer`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
  } catch (err) {
    return Response.json(
      { error: "backend unreachable", detail: String(err) },
      { status: 502 }
    );
  }

  const body = await upstream.text();
  return new Response(body, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
