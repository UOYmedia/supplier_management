/**
 * Runtime proxy — forwards all /api/v1/* requests to the backend.
 * Reads BACKEND_URL at request time (not build time) so Railway env var works.
 * Forwards Authorization header so admin auth passes through.
 */
import { NextRequest, NextResponse } from "next/server";

const BACKEND = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");

async function proxy(req: NextRequest, { params }: { params: { path: string[] } }) {
  const path = (await params).path.join("/");
  const search = req.nextUrl.search;
  const targetUrl = `${BACKEND}/api/v1/${path}${search}`;

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

  // Pass binary/non-JSON responses through as-is (e.g. PDF label downloads)
  const buf = await resp.arrayBuffer();
  return new NextResponse(buf, {
    status: resp.status,
    headers: { "Content-Type": contentType },
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
