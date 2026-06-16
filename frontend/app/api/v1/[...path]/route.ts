/**
 * Runtime proxy -- forwards all /api/v1/* requests to the backend.
 * Reads BACKEND_URL at request time (not build time) so Railway env var works.
 * Forwards Authorization header so admin auth passes through.
 */
import { NextRequest, NextResponse } from "next/server";

const BACKEND = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");

async function proxy(req: NextRequest, { params }: { params: { path: string[] } }) {
  const path = (await params).path.join("/");
  const search = req.nextUrl.search;
  const targetUrl = `${BACKEND}/api/v1/${path}${search}`;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };

  // Forward Authorization header (needed for admin + supplier auth)
  const auth = req.headers.get("authorization");
  if (auth) headers["Authorization"] = auth;

  let body: string | undefined;
  if (req.method !== "GET" && req.method !== "HEAD") {
    const ct = req.headers.get("content-type") || "";
    if (ct.includes("multipart/form-data")) {
      const fwdHeaders: Record<string, string> = { "Content-Type": ct };
      if (auth) fwdHeaders["Authorization"] = auth;
      const resp = await fetch(targetUrl, { method: req.method, headers: fwdHeaders, body: req.body, duplex: "half" } as RequestInit);
      const data = await resp.json().catch(() => null);
      return NextResponse.json(data, { status: resp.status });
    }
    body = await req.text();
  }

  const resp = await fetch(targetUrl, { method: req.method, headers, body, redirect: "manual" });

  // Pass through redirects (e.g. Shopify OAuth) directly to the browser
  if (resp.status >= 300 && resp.status < 400) {
    const location = resp.headers.get("location");
    if (location) return NextResponse.redirect(location, { status: resp.status });
  }

  const contentType = resp.headers.get("content-type") || "";

  // Pass through non-JSON responses (CSV, PDF, binary) as raw bytes
  if (!contentType.includes("application/json")) {
    const blob = await resp.arrayBuffer();
    return new NextResponse(blob, {
      status: resp.status,
      headers: {
        "Content-Type": contentType,
        "Content-Disposition": resp.headers.get("content-disposition") || "",
      },
    });
  }

  const data = await resp.json().catch(() => null);
  return NextResponse.json(data, { status: resp.status });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
