"use client"

import { useState, useMemo } from "react"
import { Download, Plus, Copy } from "lucide-react"
import { computeItem, computeBalance, RAW_ITEMS, Supplier } from "@/lib/purchase-orders"
import POMetrics from "@/components/purchase-orders/POMetrics"
import BalanceBar from "@/components/purchase-orders/BalanceBar"
import SupplierPOCard from "@/components/purchase-orders/SupplierPOCard"

const SUPPLIERS: Supplier[] = ["JOE", "SKY", "FAIRY"]
const PO_NUMBERS: Record<Supplier, string> = {
  JOE:   "PO-2024-JOE-001",
  SKY:   "PO-2024-SKY-001",
  FAIRY: "PO-2024-FAI-001",
}

const today = new Date()
const DATE_LABEL = today.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric" })

type Filter = "ALL" | Supplier

export default function PurchaseOrdersPage() {
  const [activeSupplier, setActiveSupplier] = useState<Filter>("ALL")
  const startingBalance = 1000

  const items = useMemo(() => RAW_ITEMS.map(computeItem), [])
  const balance = useMemo(() => computeBalance(items, startingBalance), [items])

  const visibleSuppliers = activeSupplier === "ALL" ? SUPPLIERS : [activeSupplier]

  const uniqueSupplierCount = new Set(items.map((i) => i.supplier)).size

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">Purchase Orders — {DATE_LABEL}</h1>
          <p className="text-sm text-gray-500 mt-1">
            {items.length} SKUs · {uniqueSupplierCount} suppliers · NET 0
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn-secondary">
            <Plus className="w-4 h-4" /> Add SKU
          </button>
          <button className="btn-secondary">
            <Copy className="w-4 h-4" /> Copy Summary
          </button>
          <button className="btn-primary">
            <Download className="w-4 h-4" /> Download PDF
          </button>
        </div>
      </div>

      <POMetrics balance={balance} items={items} />
      <BalanceBar balance={balance} />

      <div className="flex items-center gap-1 mb-5 border-b border-gray-200">
        {(["ALL", ...SUPPLIERS] as Filter[]).map((s) => (
          <button
            key={s}
            onClick={() => setActiveSupplier(s)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeSupplier === s
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {s === "ALL" ? "All Suppliers" : s}
          </button>
        ))}
      </div>

      {visibleSuppliers.map((supplier) => {
        const supplierItems = items.filter((i) => i.supplier === supplier)
        return (
          <SupplierPOCard
            key={supplier}
            supplier={supplier}
            items={supplierItems}
            poNumber={PO_NUMBERS[supplier]}
          />
        )
      })}
    </div>
  )
}
