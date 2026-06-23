"use client"

import { useState } from "react"
import { Copy, Download, Loader2 } from "lucide-react"
import toast from "react-hot-toast"
import { Supplier, SKUItem, SUPPLIER_INFO, computeBalance, fmt } from "@/lib/purchase-orders"
import SKUTable from "./SKUTable"
import OversoldNotice from "./OversoldNotice"
import RemittanceSlip from "./RemittanceSlip"

interface Props {
  supplier: Supplier
  items: SKUItem[]
  poNumber: string
  date?: string
}

const PILL: Record<Supplier, string> = {
  JOE:   "bg-blue-100 text-blue-700",
  SKY:   "bg-green-100 text-green-700",
  FAIRY: "bg-purple-100 text-purple-700",
}

const SUPPLIER_NAME: Record<Supplier, string> = {
  JOE:   "Terry Panter Nursery",
  SKY:   "Sky Nursery",
  FAIRY: "Fairy Garden Nursery",
}

const BUYER_INFO = {
  name:    "Purchasing Manager",
  company: "Maga Fulfillment",
  email:   "purchasing@maga.com",
  address: "123 Fulfillment Blvd, Nashville, TN 37201",
}

export default function SupplierPOCard({ supplier, items, poNumber, date }: Props) {
  const [pdfLoading, setPdfLoading] = useState(false)
  const total = items.reduce((s, i) => s + i.total_cost, 0)
  const balance = computeBalance(items, 0)

  async function handlePDF() {
    setPdfLoading(true)
    try {
      const res = await fetch("/api/v1/purchase-orders/generate-pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          supplier,
          po_number: poNumber,
          date: date ?? new Date().toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" }),
          items,
          supplier_info: SUPPLIER_INFO[supplier],
          buyer_info: BUYER_INFO,
          balance,
        }),
      })

      const contentType = res.headers.get("content-type") ?? ""

      if (res.ok && contentType.includes("application/pdf")) {
        const blob = await res.blob()
        const url = URL.createObjectURL(blob)
        window.open(url, "_blank")
        toast.success("PDF opened in new tab")
      } else {
        const json = await res.json()
        if (json.status === "mock") {
          toast("PDF export coming soon — data logged to console", { icon: "📋" })
        } else {
          toast.error("PDF generation failed")
        }
      }
    } catch {
      toast.error("Could not reach server")
    } finally {
      setPdfLoading(false)
    }
  }

  return (
    <div className="card mb-5 overflow-hidden">
      <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 bg-gray-50/50">
        <div className="flex items-center gap-3">
          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${PILL[supplier]}`}>
            {supplier}
          </span>
          <span className="font-semibold text-gray-800">{SUPPLIER_NAME[supplier]}</span>
          <span className="text-xs text-gray-400">{poNumber}</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="font-bold text-gray-900">${fmt(total)}</span>
          <button className="btn-secondary py-1.5 text-xs">
            <Copy className="w-3.5 h-3.5" /> Copy
          </button>
          <button
            className="btn-primary py-1.5 text-xs"
            onClick={handlePDF}
            disabled={pdfLoading}
          >
            {pdfLoading
              ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
              : <Download className="w-3.5 h-3.5" />}
            PDF
          </button>
        </div>
      </div>

      <div className="px-5 py-4">
        <SKUTable items={items} />
        <div className="my-4 border-t border-dashed border-gray-200" />
        <OversoldNotice items={items} />
        <RemittanceSlip supplier={supplier} poNumber={poNumber} items={items} />

        <div className="mt-3 text-sm space-y-1 text-right">
          <div className="flex justify-end gap-8 text-gray-600">
            <span>Subtotal</span>
            <span className="font-medium w-24">${fmt(total)}</span>
          </div>
          {items.some((i) => i.oversold_value > 0) && (
            <div className="flex justify-end gap-8 text-red-600">
              <span>Oversold A/R</span>
              <span className="font-medium w-24">
                −${fmt(items.reduce((s, i) => s + i.oversold_value, 0))}
              </span>
            </div>
          )}
          <div className="flex justify-end gap-8 font-semibold text-gray-900 pt-1 border-t border-gray-200">
            <span>Balance Due</span>
            <span className="w-24">
              ${fmt(total - items.reduce((s, i) => s + i.oversold_value, 0))}
            </span>
          </div>
        </div>
      </div>
    </div>
  )
}
