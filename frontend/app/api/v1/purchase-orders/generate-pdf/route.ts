import { NextRequest, NextResponse } from "next/server"

const BACKEND = (process.env.BACKEND_URL || "http://localhost:8000").replace(/\/$/, "")

export async function POST(req: NextRequest) {
  const body = await req.json()

  const auth = req.headers.get("authorization")
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (auth) headers["Authorization"] = auth

  try {
    const res = await fetch(`${BACKEND}/api/v1/purchase-orders/generate-pdf`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
    })

    if (res.ok) {
      const contentType = res.headers.get("content-type") ?? ""
      if (contentType.includes("application/pdf")) {
        const blob = await res.arrayBuffer()
        return new NextResponse(blob, {
          status: 200,
          headers: {
            "Content-Type": "application/pdf",
            "Content-Disposition": `attachment; filename="PO-${body.po_number ?? "export"}.pdf"`,
          },
        })
      }
      // Backend responded but not a PDF — fall through to mock
    }
    // 404 / non-ok → fall through to mock
  } catch {
    // Network error or backend unreachable → fall through to mock
  }

  console.log("[purchase-orders/generate-pdf] mock — body:", JSON.stringify(body, null, 2))

  return NextResponse.json(
    { status: "mock", message: "PDF generation coming soon" },
    { status: 200 }
  )
}
