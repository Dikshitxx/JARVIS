import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

type RouteContext = { params: { path: string[] } };

const ALLOWED_ROOTS = new Set([
  "activity",
  "chat",
  "health",
  "llm",
  "reset",
  "status",
  "tasks",
  "voice",
]);

function isAllowedPath(segments: string[]): boolean {
  if (!segments.length || segments.some((segment) => !segment || segment === "." || segment === "..")) {
    return false;
  }
  if (!ALLOWED_ROOTS.has(segments[0])) return false;
  if (segments[0] === "tasks") return segments.length <= 3 && segments[2] !== "";
  if (segments[0] === "voice") return segments.length === 2 && segments[1] === "status";
  if (segments[0] === "llm") return segments.length === 2 && segments[1] === "status";
  return segments.length === 1;
}

async function forward(request: NextRequest, { params }: RouteContext): Promise<Response> {
  if (!isAllowedPath(params.path)) {
    return Response.json({ detail: "Backend route not found." }, { status: 404 });
  }

  const base = (process.env.JARVIS_API_BASE || "http://127.0.0.1:8000").replace(/\/+$/, "");
  const path = params.path.map((part) => encodeURIComponent(part)).join("/");
  const target = new URL(`${base}/${path}`);
  target.search = new URL(request.url).search;

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const secret = process.env.JARVIS_API_SECRET?.trim();
  if (secret) headers.set("X-Jarvis-Secret", secret);

  try {
    const response = await fetch(target, {
      method: request.method,
      headers,
      body: request.method === "GET" ? undefined : await request.text(),
      cache: "no-store",
    });
    const responseHeaders = new Headers();
    const responseType = response.headers.get("content-type");
    if (responseType) responseHeaders.set("content-type", responseType);
    responseHeaders.set("cache-control", "no-store");
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers: responseHeaders,
    });
  } catch {
    return Response.json({ detail: "JARVIS backend is unavailable." }, { status: 502 });
  }
}

export const GET = forward;
export const POST = forward;
