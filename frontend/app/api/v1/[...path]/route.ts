/**
 * Runtime proxy — forwards all /api/v1/* requests to the backend.
 * Reads BACKEND_URL at request time (not build time) so Railway env var works.
 * Forwards Authorization header so admin auth passes through.
 */
import { NextRequest, NextResponse } from "next/server";

async function proxy(req: NextRequest, { params }: { params: { path: string[] } }) {
  const backend = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");
  const path = params.path.join("/");
  const search = req.nextUrl.search;
  const targetUrl = `${backend}/api/v1/${path}${search}`;

  try {
    const fwdHeaders: Record<string, string> = {};
    const auth = req.headers.get("authorization");
    if (auth) fwdHeaders["Authorization"] = auth;

    let body: BodyInit | undefined;
    if (req.method !== "GET" && req.method !== "HEAD") {
      const ct = req.headers.get("content-type") || "";
      if (ct.includes("multipart/form-data")) {
        body = await req.formData();
      } else {
        fwdHeaders["Content-Type"] = ct || "application/json";
        body = await req.text();
      }
    }

    const resp = await fetch(targetUrl, { method: req.method, headers: fwdHeaders, body });

    const contentType = resp.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const data = await resp.json().catch(() => null);
      return NextResponse.json(data, { status: resp.status });
    }

    // Pass binary responses through (e.g. PDF label downloads)
    const buf = await resp.arrayBuffer();
    return new NextResponse(buf, {
      status: resp.status,
      headers: { "Content-Type": contentType },
    });
  } catch (err) {
    console.error(`[proxy] ${req.method} ${targetUrl} failed:`, err);
    return NextResponse.json(
      { detail: `Backend unreachable (BACKEND_URL=${backend})` },
      { status: 502 }
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
