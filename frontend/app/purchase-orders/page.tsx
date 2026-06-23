"use client"

import { useEffect, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Plus, Copy, RefreshCw, ChevronLeft, ChevronRight } from "lucide-react"
import toast from "react-hot-toast"
import { Supplier, PODailyResponse, SKUItem, computeItem, computeBalance, fmtDate, toISODate, RAW_ITEMS } from "@/lib/purchase-orders"
import POMetrics from "@/components/purchase-orders/POMetrics"
import BalanceBar from "@/components/purchase-orders/BalanceBar"
import SupplierPOCard from "@/components/purchase-orders/SupplierPOCard"
import RequestList from "@/components/purchase-orders/RequestList"
import { purchaseRequestsApi } from "@/lib/api"

const SUPPLIERS: Supplier[] = ["JOE", "SKY", "FAIRY"]

type Filter = "ALL" | Supplier
type PageTab = "orders" | "requests"

async function fetchDailyPO(dateStr: string): Promise<PODailyResponse> {
  const res = await fetch(`/api/v1/purchase-orders/daily?date=${dateStr}`)
  if (!res.ok) throw new Error(`Server error ${res.status}`)
  return res.json()
}

function POSkeleton() {
  return (
    <div className="animate-pulse space-y-4">
      <div className="grid grid-cols-3 gap-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="card p-4 h-24 bg-gray-100 rounded-xl" />
        ))}
      </div>
      <div className="card p-4 h-14 bg-gray-100 rounded-xl" />
      <div className="card p-6 h-48 bg-gray-100 rounded-xl" />
      <div className="card p-6 h-48 bg-gray-100 rounded-xl" />
    </div>
  )
}

export default function PurchaseOrdersPage() {
  const [selectedDate, setSelectedDate] = useState<Date>(new Date())
  const [activeSupplier, setActiveSupplier] = useState<Filter>("ALL")
  const [pageTab, setPageTab] = useState<PageTab>("orders")
  const [username, setUsername] = useState("")

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem("admin_user") || "{}")
    setUsername(user.username || "")
  }, [])

  const { data: pendingRequests = [] } = useQuery({
    queryKey: ["purchase-requests"],
    queryFn: () => purchaseRequestsApi.list(),
    select: (data: any[]) => data.filter((r) => r.status === "PENDING"),
  })

  const dateStr = toISODate(selectedDate)

  const { data, isLoading, isError, error, refetch } = useQuery<PODailyResponse>({
    queryKey: ["purchase-orders-daily", dateStr],
    queryFn: () => fetchDailyPO(dateStr),
    retry: 1,
  })

  function shiftDate(days: number) {
    setSelectedDate((d) => {
      const next = new Date(d)
      next.setDate(next.getDate() + days)
      return next
    })
  }

  const SAMPLE_ITEMS: SKUItem[] = RAW_ITEMS.map(computeItem)
  const SAMPLE_BALANCE = computeBalance(SAMPLE_ITEMS, 1000)

  const apiItems = data?.items ?? []
  const items: SKUItem[] = apiItems.length > 0 ? apiItems : SAMPLE_ITEMS
  const balance = apiItems.length > 0 ? (data?.balance ?? SAMPLE_BALANCE) : SAMPLE_BALANCE
  const isUsingFallback = !isLoading && !isError && apiItems.length === 0

  const visibleSuppliers = activeSupplier === "ALL" ? SUPPLIERS : [activeSupplier]
  const uniqueSupplierCount = new Set(items.map((i) => i.supplier)).size

  const PO_NUMBERS: Record<Supplier, string> = {
    JOE:   `PO-${dateStr.replace(/-/g, "").slice(0, 8)}-JOE`,
    SKY:   `PO-${dateStr.replace(/-/g, "").slice(0, 8)}-SKY`,
    FAIRY: `PO-${dateStr.replace(/-/g, "").slice(0, 8)}-FAIRY`,
  }

  if (isError) {
    toast.error(`Failed to load: ${(error as Error).message}`, { id: "po-error" })
  }

  return (
    <div>
      {/* Page-level tabs */}
      <div className="flex items-center gap-1 mb-0 border-b border-gray-200">
        <button
          onClick={() => setPageTab("orders")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            pageTab === "orders"
              ? "border-blue-600 text-blue-700"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          Daily Orders
        </button>
        <button
          onClick={() => setPageTab("requests")}
          className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            pageTab === "requests"
              ? "border-blue-600 text-blue-700"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          Requests
          {pendingRequests.length > 0 && (
            <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold bg-red-500 text-white">
              {pendingRequests.length}
            </span>
          )}
        </button>
      </div>

      {pageTab === "requests" ? (
        <div className="mt-6">
          <div className="page-header">
            <div>
              <h1 className="page-title">Purchase Requests</h1>
              <p className="text-sm text-gray-500 mt-1">{pendingRequests.length} pending</p>
            </div>
          </div>
          <RequestList username={username} onPaidSuccess={() => refetch()} />
        </div>
      ) : null}

      {pageTab === "orders" && <>
      <div className="page-header">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="page-title">Purchase Orders</h1>
            {/* Date navigator */}
            <div className="flex items-center gap-1 ml-3 bg-white border border-gray-200 rounded-lg px-2 py-1">
              <button
                onClick={() => shiftDate(-1)}
                className="p-0.5 text-gray-400 hover:text-gray-700 transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <input
                type="date"
                value={dateStr}
                onChange={(e) => setSelectedDate(new Date(e.target.value + "T00:00:00"))}
                className="text-sm font-medium text-gray-700 border-none outline-none bg-transparent cursor-pointer"
              />
              <button
                onClick={() => shiftDate(1)}
                className="p-0.5 text-gray-400 hover:text-gray-700 transition-colors"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
          <p className="text-sm text-gray-500 mt-1 flex items-center gap-2">
            {isLoading
              ? "Loading…"
              : `${items.length} SKUs · ${uniqueSupplierCount} suppliers · NET 0`}
            {isUsingFallback && (
              <span className="badge-yellow">Sample data — no DB records for this date</span>
            )}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn-secondary" onClick={() => refetch()}>
            <RefreshCw className="w-4 h-4" /> Refresh
          </button>
          <button className="btn-secondary">
            <Plus className="w-4 h-4" /> Add SKU
          </button>
          <button className="btn-secondary">
            <Copy className="w-4 h-4" /> Copy Summary
          </button>
        </div>
      </div>

      {isLoading ? (
        <POSkeleton />
      ) : isError ? (
        <div className="card p-8 text-center">
          <p className="text-red-600 font-medium mb-2">Failed to load purchase orders</p>
          <p className="text-sm text-gray-500 mb-4">{(error as Error).message}</p>
          <button className="btn-secondary" onClick={() => refetch()}>
            <RefreshCw className="w-4 h-4" /> Retry
          </button>
        </div>
      ) : (
        <>
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

          {items.length === 0 ? (
            <div className="card p-12 text-center">
              <p className="text-gray-400 font-medium">No purchase orders for {fmtDate(selectedDate)}</p>
              <p className="text-sm text-gray-400 mt-1">Add SKUs or select a different date</p>
            </div>
          ) : (
            visibleSuppliers.map((supplier) => {
              const supplierItems = items.filter((i) => i.supplier === supplier)
              if (supplierItems.length === 0) return null
              return (
                <SupplierPOCard
                  key={supplier}
                  supplier={supplier}
                  items={supplierItems}
                  poNumber={PO_NUMBERS[supplier]}
                  date={fmtDate(selectedDate)}
                />
              )
            })
          )}
        </>
      )}
      </>}
    </div>
  )
}
