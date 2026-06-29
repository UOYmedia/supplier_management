"use client"

import { useState, useEffect } from "react"
import { useQuery } from "@tanstack/react-query"
import { RefreshCw, Database, Copy, Download, Loader2 } from "lucide-react"
import toast from "react-hot-toast"
import { suppliersApi, snapshotsApi } from "@/lib/api"
import { SKUItem, fmt } from "@/lib/purchase-orders"
import SKUTable from "./SKUTable"

// Real supplier as returned by GET /suppliers
interface RealSupplier {
  id: number
  name: string
  supplier_type?: string
  email?: string | null
  phone?: string | null
  city?: string | null
  state?: string | null
  country?: string | null
  zipcode?: string | null
  product_count: number
  total_stock: number
}

const BUYER_INFO = {
  name:    "Purchasing Manager",
  company: "Maga Fulfillment",
  email:   "purchasing@maga.com",
  address: "123 Fulfillment Blvd, Nashville, TN 37201",
}

// Catalog item as returned by GET /suppliers/{id}/products
interface CatalogProduct {
  id: number
  name: string
  sku: string
  unit_price: number | string
  stock_quantity: number
  sold_quantity: number
  pending_quantity: number
}

// Map a live catalog row into the PO table's SKUItem shape.
//   available = stock_quantity   (physical inventory on hand)
//   ordered   = pending_quantity (orders waiting to ship)
//   unit_cost = unit_price
function toSKUItem(p: CatalogProduct, supplierName: string): SKUItem {
  const available = p.stock_quantity
  const ordered = p.pending_quantity
  const unit_cost = Number(p.unit_price) || 0
  const gap = available - ordered
  const oversold = Math.max(0, -gap)
  const avail_final = Math.max(0, gap)
  const total_cost = ordered * unit_cost
  const oversold_value = oversold * unit_cost
  const avail_value = avail_final * unit_cost
  const status: SKUItem["status"] = gap > 5 ? "ok" : gap >= 0 ? "low" : "oversold"

  return {
    sku: p.name || p.sku,
    supplier: supplierName as SKUItem["supplier"],
    ordered, available, unit_cost,
    gap, oversold, avail_final,
    total_cost, oversold_value, avail_value,
    status,
    po_id: p.id,
    po_status: "LIVE",
  }
}

type LivePeriod = "today" | "this_week" | "this_month" | "all"

const PERIOD_OPTS: { key: LivePeriod; label: string }[] = [
  { key: "today",      label: "Today" },
  { key: "this_week",  label: "This Week" },
  { key: "this_month", label: "This Month" },
  { key: "all",        label: "All time" },
]

function getMonday(d: Date): Date {
  const day = d.getDay()
  const diff = day === 0 ? -6 : 1 - day
  const m = new Date(d)
  m.setDate(d.getDate() + diff)
  return m
}

// Returns ISO start/end-of-day strings for the chosen period, or null for "all".
function periodRange(period: LivePeriod): { from: string; to: string } | null {
  if (period === "all") return null
  const now = new Date()
  let from = new Date(now)
  let to = new Date(now)
  if (period === "this_week") {
    from = getMonday(now)
    to = new Date(from)
    to.setDate(from.getDate() + 6)
  } else if (period === "this_month") {
    from = new Date(now.getFullYear(), now.getMonth(), 1)
    to = new Date(now.getFullYear(), now.getMonth() + 1, 0)
  }
  from.setHours(0, 0, 0, 0)
  to.setHours(23, 59, 59, 999)
  return { from: from.toISOString(), to: to.toISOString() }
}

export default function LiveSupplierPO() {
  const [activeId, setActiveId] = useState<number | null>(null)
  const [period, setPeriod] = useState<LivePeriod>("today")
  const [pdfLoading, setPdfLoading] = useState(false)
  // "" = current live numbers; a date = the frozen end-of-day snapshot for that
  // day. Drives both the on-screen table and the PO PDF.
  const [viewDate, setViewDate] = useState("")
  const range = periodRange(period)

  // Dates that have a stored end-of-day snapshot, for the date picker.
  const datesQuery = useQuery<string[]>({
    queryKey: ["snapshot-dates"],
    queryFn: () => snapshotsApi.dates(),
  })
  const snapshotDates = datesQuery.data ?? []

  const suppliersQuery = useQuery<RealSupplier[]>({
    queryKey: ["live-suppliers"],
    queryFn: () => suppliersApi.list({ is_active: true, limit: 100 }),
  })

  const suppliers = suppliersQuery.data ?? []

  // Default to the supplier with the most catalog items (most useful to look at)
  useEffect(() => {
    if (activeId === null && suppliers.length > 0) {
      const best = [...suppliers].sort((a, b) => b.product_count - a.product_count)[0]
      setActiveId(best.id)
    }
  }, [suppliers, activeId])

  const activeSupplier = suppliers.find((s) => s.id === activeId) ?? null

  const productsQuery = useQuery<CatalogProduct[]>({
    queryKey: ["live-catalog", activeId, period],
    queryFn: () =>
      suppliersApi.listProducts(
        activeId as number,
        range ? { date_from: range.from, date_to: range.to } : undefined
      ),
    enabled: activeId !== null && !viewDate,
  })

  // Frozen snapshot for the chosen day + supplier (only when a date is picked).
  const snapshotQuery = useQuery<any[]>({
    queryKey: ["snapshot-view", viewDate, activeId],
    queryFn: () => snapshotsApi.get(viewDate, activeId as number),
    enabled: !!viewDate && activeId !== null,
  })

  const items: SKUItem[] = viewDate
    ? (snapshotQuery.data ?? []).map(snapshotRowToItem)
    : (productsQuery.data ?? []).map((p) => toSKUItem(p, activeSupplier?.name ?? ""))

  const loading = viewDate ? snapshotQuery.isLoading : productsQuery.isLoading
  const loadError = viewDate ? snapshotQuery.isError : productsQuery.isError

  // Stock-supplier economics (catalog data is inventory-based):
  //   goodsValue     = value of orders waiting to ship (ordered × price)
  //   inventoryValue = value of stock still on hand
  //   debt           = value of units sold beyond available stock (công nợ)
  const goodsValue = items.reduce((s, i) => s + i.total_cost, 0)
  const inventoryValue = items.reduce((s, i) => s + i.avail_value, 0)
  const debt = items.reduce((s, i) => s + i.oversold_value, 0)
  const oversoldCount = items.filter((i) => i.oversold > 0).length

  // Plain-text PO summary for the active supplier — handy to paste into chat/email.
  function copySummary() {
    if (!activeSupplier || items.length === 0) {
      toast.error("Nothing to copy")
      return
    }
    const lines = items
      .filter((i) => i.ordered > 0)
      .map((i) => `• ${i.sku} x${i.ordered} @ $${fmt(i.unit_cost)} = $${fmt(i.total_cost)}`)
    const text = [
      `${activeSupplier.name} — orders to ship`,
      ...lines,
      `Total: $${fmt(goodsValue)}`,
    ].join("\n")
    navigator.clipboard.writeText(text).then(
      () => toast.success("Summary copied"),
      () => toast.error("Copy failed"),
    )
  }

  // Map a stored snapshot row into the same item shape the PDF generator reads.
  function snapshotRowToItem(r: any): SKUItem {
    const available = r.available
    const ordered = r.ordered
    const gap = available - ordered
    const status: SKUItem["status"] = gap > 5 ? "ok" : gap >= 0 ? "low" : "oversold"
    return {
      sku: r.product_name || r.sku,
      supplier: r.supplier_name as SKUItem["supplier"],
      ordered, available,
      unit_cost: Number(r.unit_cost) || 0,
      gap,
      oversold: r.oversold,
      avail_final: Math.max(0, gap),
      total_cost: Number(r.total_cost) || 0,
      oversold_value: Number(r.oversold_value) || 0,
      avail_value: Number(r.avail_value) || 0,
      status,
      po_id: 0,
      po_status: "SNAPSHOT",
    }
  }

  // Daily PO statement PDF for the active supplier: Available / Cost / Total /
  // Oversold + estimated oversold cost per product (the supplier-facing daily doc).
  // Uses current live numbers, or a frozen end-of-day snapshot when a date is picked.
  async function handlePDF() {
    if (!activeSupplier) {
      toast.error("Nothing to export")
      return
    }
    if (items.length === 0) {
      toast.error("Nothing to export")
      return
    }
    setPdfLoading(true)
    try {
      // items / totals already reflect the picked day (or live) via the table.
      const stampSource = viewDate ? new Date(viewDate + "T00:00:00") : new Date()
      const dateLabel = stampSource.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" })
      const stamp = `${stampSource.getFullYear()}${String(stampSource.getMonth() + 1).padStart(2, "0")}${String(stampSource.getDate()).padStart(2, "0")}`
      const cityLine = [activeSupplier.city, activeSupplier.state, activeSupplier.zipcode]
        .filter(Boolean).join(", ")
      const res = await fetch("/api/v1/purchase-orders/generate-pdf", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          supplier: activeSupplier.name,
          po_number: `PO-${stamp}-${activeSupplier.name}`,
          date: dateLabel,
          items,
          supplier_info: {
            name: activeSupplier.name,
            address: "",
            city: cityLine,
            phone: activeSupplier.phone ?? "",
            email: activeSupplier.email ?? "",
          },
          buyer_info: BUYER_INFO,
          balance: {
            total_cost: goodsValue,
            available_value: inventoryValue,
            oversold_value: debt,
            starting_balance: 0,
            ending_balance: 0,
          },
        }),
      })
      const contentType = res.headers.get("content-type") ?? ""
      if (res.ok && contentType.includes("application/pdf")) {
        const blob = await res.blob()
        window.open(URL.createObjectURL(blob), "_blank")
      } else {
        toast.error("PDF generation failed")
      }
    } catch {
      toast.error("Could not reach server")
    } finally {
      setPdfLoading(false)
    }
  }

  return (
    <div>
      {/* Supplier tabs from real DB */}
      <div className="flex items-center gap-2 mb-4 flex-wrap">
        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2.5 py-1">
          <Database className="w-3 h-3" /> Live data
        </span>
        {suppliersQuery.isLoading ? (
          <span className="text-sm text-gray-400">Loading suppliers…</span>
        ) : suppliers.length === 0 ? (
          <span className="text-sm text-gray-400">No active suppliers found</span>
        ) : (
          suppliers.map((s) => (
            <button
              key={s.id}
              onClick={() => setActiveId(s.id)}
              className={`px-3 py-1.5 text-sm font-medium rounded-md border transition-colors ${
                activeId === s.id
                  ? "bg-blue-600 text-white border-transparent"
                  : "bg-white text-gray-600 border-gray-200 hover:border-blue-300 hover:text-blue-600"
              }`}
            >
              {s.name}
              <span className="ml-1.5 text-[10px] opacity-70">{s.product_count}</span>
            </button>
          ))
        )}
        <select
          value={viewDate || period}
          onChange={(e) => {
            const v = e.target.value
            if (PERIOD_OPTS.some((p) => p.key === v)) {
              setPeriod(v as LivePeriod)
              setViewDate("")
            } else {
              setViewDate(v)
            }
          }}
          title="Live period, or a saved end-of-day snapshot"
          className="ml-auto border border-gray-200 rounded-md py-1.5 px-2 text-xs text-gray-600 bg-white"
        >
          <optgroup label="Live">
            {PERIOD_OPTS.map((p) => (
              <option key={p.key} value={p.key}>{p.label}</option>
            ))}
          </optgroup>
          {snapshotDates.length > 0 && (
            <optgroup label="Saved end-of-day">
              {snapshotDates.map((d) => (
                <option key={d} value={d}>{d}</option>
              ))}
            </optgroup>
          )}
        </select>
        <button
          className="btn-secondary py-1.5 text-xs"
          onClick={handlePDF}
          disabled={!activeSupplier || items.length === 0 || pdfLoading}
        >
          {pdfLoading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />}
          PO PDF
        </button>
        <button
          className="btn-secondary py-1.5 text-xs"
          onClick={copySummary}
          disabled={!activeSupplier || items.length === 0}
        >
          <Copy className="w-3.5 h-3.5" /> Copy Summary
        </button>
        <button
          className="btn-secondary py-1.5 text-xs"
          onClick={() => { suppliersQuery.refetch(); productsQuery.refetch(); snapshotQuery.refetch(); datesQuery.refetch() }}
        >
          <RefreshCw className="w-3.5 h-3.5" /> Refresh
        </button>
      </div>

      {/* A frozen snapshot ignores the live period; flag it so the numbers read clearly. */}
      {viewDate && (
        <div className="flex items-center gap-1.5 mb-4">
          <span className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-2.5 py-1">
            Viewing saved end-of-day snapshot for {viewDate}
          </span>
        </div>
      )}

      {activeSupplier && (
        <div className="card overflow-hidden">
          {/* Card header */}
          <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100 bg-gray-50/50">
            <div className="flex items-center gap-3">
              <span className="font-semibold text-gray-800">{activeSupplier.name}</span>
              {activeSupplier.supplier_type === "stock" ? (
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide bg-amber-100 text-amber-700">
                  Stock
                </span>
              ) : (
                <span className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide bg-sky-100 text-sky-700">
                  Balance
                </span>
              )}
              <span className="text-xs text-gray-400">
                {items.length} SKUs · {viewDate ? `snapshot ${viewDate}` : "live catalog"}
              </span>
            </div>
            <div className="text-right leading-tight">
              <span className={`block font-bold ${debt > 0 ? "text-red-600" : "text-gray-900"}`}>
                ${fmt(debt)}
              </span>
              <span className="block text-[10px] text-gray-400">debt owed</span>
            </div>
          </div>

          <div className="px-5 py-4">
            {loading ? (
              <p className="text-sm text-gray-400 py-8 text-center">Loading…</p>
            ) : loadError ? (
              <p className="text-sm text-red-500 py-8 text-center">Failed to load</p>
            ) : items.length === 0 ? (
              <p className="text-sm text-gray-400 py-8 text-center">
                {viewDate ? "No snapshot saved for this day" : "This supplier has no catalog items"}
              </p>
            ) : (
              <>
                <SKUTable items={items} supplierType="stock" />

                <div className="mt-4 text-sm space-y-1 text-right border-t border-dashed border-gray-200 pt-3">
                  <div className="flex justify-end gap-8 text-gray-500">
                    <span>Orders to ship (value)</span>
                    <span className="font-medium w-28">${fmt(goodsValue)}</span>
                  </div>
                  <div className="flex justify-end gap-8 text-green-700">
                    <span>Inventory value on hand</span>
                    <span className="font-medium w-28">${fmt(inventoryValue)}</span>
                  </div>
                  <div className="flex justify-end gap-8 font-semibold pt-1 border-t border-gray-200 text-red-600">
                    <span>Debt owed (shortage{oversoldCount > 0 ? `, ${oversoldCount} SKUs` : ""})</span>
                    <span className="w-28">${fmt(debt)}</span>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
