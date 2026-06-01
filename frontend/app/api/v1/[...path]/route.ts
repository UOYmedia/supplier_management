/**
 * Runtime proxy — forwards all /api/v1/* requests to the backend.
 * Reads BACKEND_URL at request time (not build time) so Railway env var works.
 * Forwards Authorization header so admin auth passes through.
 *
 * Passes responses through as raw bytes, preserving the backend's
 * Content-Type / Content-Disposition. This is required for non-JSON
 * responses such as PDF shipping labels and CSV exports — re-encoding
 * those as JSON would corrupt them (a PDF body would come back as `null`).
 */
import { NextRequest, NextResponse } from "next/server";

const BACKEND = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "");

// Headers we forward back to the client from the backend response.
const PASSTHROUGH_RESPONSE_HEADERS = ["content-type", "content-disposition", "cache-control"];

function buildResponse(resp: Response, bodyBuffer: ArrayBuffer): NextResponse {
  const headers = new Headers();
  for (const h of PASSTHROUGH_RESPONSE_HEADERS) {
    const v = resp.headers.get(h);
    if (v) headers.set(h, v);
  }
  return new NextResponse(bodyBuffer, { status: resp.status, headers });
}

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

  let resp: Response;

  if (req.method !== "GET" && req.method !== "HEAD") {
    const ct = req.headers.get("content-type") || "";
    if (ct.includes("multipart/form-data")) {
      const formData = await req.formData();
      const fwdHeaders: Record<string, string> = {};
      if (auth) fwdHeaders["Authorization"] = auth;
      resp = await fetch(targetUrl, { method: req.method, headers: fwdHeaders, body: formData });
    } else {
      const body = await req.text();
      resp = await fetch(targetUrl, { method: req.method, headers, body });
    }
  } else {
    resp = await fetch(targetUrl, { method: req.method, headers });
  }

  // Pass the response through as raw bytes, preserving Content-Type so binary
  // payloads (PDF labels, CSV exports) survive the hop intact.
  const bodyBuffer = await resp.arrayBuffer();
  return buildResponse(resp, bodyBuffer);
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
