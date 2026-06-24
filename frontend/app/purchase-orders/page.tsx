"use client"

import { useEffect, useState, useMemo } from "react"
import { useRouter, useSearchParams } from "next/navigation"
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
type PeriodPreset = "today" | "this_week" | "last_week" | "this_month" | "custom"

const PERIOD_LABELS: Record<PeriodPreset, string> = {
  today:      "Today",
  this_week:  "This Week",
  last_week:  "Last Week",
  this_month: "This Month",
  custom:     "Custom",
}

function getMonday(d: Date): Date {
  const day = d.getDay()
  const diff = (day === 0 ? -6 : 1 - day)
  const m = new Date(d)
  m.setDate(d.getDate() + diff)
  return m
}

function computePresetRange(preset: PeriodPreset, today: Date): { from: Date; to: Date } {
  const from = new Date(today)
  const to = new Date(today)
  if (preset === "today") {
    return { from, to }
  }
  if (preset === "this_week") {
    const mon = getMonday(today)
    const sun = new Date(mon)
    sun.setDate(mon.getDate() + 6)
    return { from: mon, to: sun }
  }
  if (preset === "last_week") {
    const thisMonday = getMonday(today)
    const lastMon = new Date(thisMonday)
    lastMon.setDate(thisMonday.getDate() - 7)
    const lastSun = new Date(lastMon)
    lastSun.setDate(lastMon.getDate() + 6)
    return { from: lastMon, to: lastSun }
  }
  if (preset === "this_month") {
    return {
      from: new Date(today.getFullYear(), today.getMonth(), 1),
      to: new Date(today.getFullYear(), today.getMonth() + 1, 0),
    }
  }
  return { from, to }
}

async function fetchDailyPO(dateStr: string): Promise<PODailyResponse> {
  const res = await fetch(`/api/v1/purchase-orders/daily?date=${dateStr}`)
  if (!res.ok) throw new Error(`Server error ${res.status}`)
  return res.json()
}

async function fetchPeriodPO(fromStr: string, toStr: string): Promise<PODailyResponse> {
  const res = await fetch(`/api/v1/purchase-orders/period?from_date=${fromStr}&to_date=${toStr}`)
  if (!res.ok) throw new Error(`Server error ${res.status}`)
  const d = await res.json()
  // normalise period response to same shape as daily (use from_date as date)
  return { date: d.from_date, items: d.items, balance: d.balance }
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

function PurchaseOrdersPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const today = useMemo(() => new Date(), [])

  const [preset, setPreset] = useState<PeriodPreset>("today")
  const [selectedDate, setSelectedDate] = useState<Date>(today)
  const [customFrom, setCustomFrom] = useState<Date>(today)
  const [customTo, setCustomTo] = useState<Date>(today)

  const [activeSupplier, setActiveSupplier] = useState<Filter>("ALL")
  const pageTab = (searchParams.get("tab") === "requests" ? "requests" : "orders") as PageTab
  const [username, setUsername] = useState("")
  const [userRole, setUserRole] = useState("")

  function setPageTab(tab: PageTab) {
    const params = new URLSearchParams(searchParams.toString())
    if (tab === "requests") params.set("tab", "requests")
    else params.delete("tab")
    router.push(`/purchase-orders?${params.toString()}`)
  }

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem("admin_user") || "{}")
    setUsername(user.username || "")
    setUserRole(user.role || "")
  }, [])

  const { data: pendingRequests = [] } = useQuery({
    queryKey: ["purchase-requests"],
    queryFn: () => purchaseRequestsApi.list(),
    select: (data: any[]) => data.filter((r) => r.status === "PENDING"),
  })

  // Resolve the actual date range based on preset
  const { fromDate, toDate, isSingleDay } = useMemo(() => {
    if (preset === "today") {
      return { fromDate: selectedDate, toDate: selectedDate, isSingleDay: true }
    }
    if (preset === "custom") {
      const single = toISODate(customFrom) === toISODate(customTo)
      return { fromDate: customFrom, toDate: customTo, isSingleDay: single }
    }
    const { from, to } = computePresetRange(preset, today)
    const single = toISODate(from) === toISODate(to)
    return { fromDate: from, toDate: to, isSingleDay: single }
  }, [preset, selectedDate, customFrom, customTo, today])

  const fromStr = toISODate(fromDate)
  const toStr = toISODate(toDate)

  const { data, isLoading, isError, error, refetch } = useQuery<PODailyResponse>({
    queryKey: ["purchase-orders", fromStr, toStr, isSingleDay],
    queryFn: () => isSingleDay ? fetchDailyPO(fromStr) : fetchPeriodPO(fromStr, toStr),
    retry: 1,
  })

  function shiftDate(days: number) {
    setSelectedDate((d) => {
      const next = new Date(d)
      next.setDate(next.getDate() + days)
      return next
    })
  }

  function handlePreset(p: PeriodPreset) {
    setPreset(p)
    if (p === "today") setSelectedDate(new Date())
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
    JOE:   `PO-${fromStr.replace(/-/g, "").slice(0, 8)}-JOE`,
    SKY:   `PO-${fromStr.replace(/-/g, "").slice(0, 8)}-SKY`,
    FAIRY: `PO-${fromStr.replace(/-/g, "").slice(0, 8)}-FAIRY`,
  }

  if (isError) {
    toast.error(`Failed to load: ${(error as Error).message}`, { id: "po-error" })
  }

  const periodLabel = preset === "today"
    ? fmtDate(selectedDate)
    : preset === "custom"
      ? `${fmtDate(customFrom)} – ${fmtDate(customTo)}`
      : `${fmtDate(fromDate)} – ${fmtDate(toDate)}`

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
            </div>
          </div>
          <RequestList username={username} canApprove={userRole === "admin" || username.toLowerCase() === "jenny" || username.toLowerCase() === "admin"} onPaidSuccess={() => refetch()} />
        </div>
      ) : null}

      {pageTab === "orders" && <>
      <div className="page-header">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="page-title">Purchase Orders</h1>

            {/* Period preset pills */}
            <div className="flex items-center gap-1 ml-2">
              {(Object.keys(PERIOD_LABELS) as PeriodPreset[]).map((p) => (
                <button
                  key={p}
                  onClick={() => handlePreset(p)}
                  className={`px-2.5 py-1 text-xs font-medium rounded-md border transition-colors ${
                    preset === p
                      ? "bg-blue-600 text-white border-transparent"
                      : "bg-white text-gray-600 border-gray-200 hover:border-blue-300 hover:text-blue-600"
                  }`}
                >
                  {PERIOD_LABELS[p]}
                </button>
              ))}
            </div>

            {/* Today: date navigator; Custom: from/to inputs */}
            {preset === "today" && (
              <div className="flex items-center gap-1 bg-white border border-gray-200 rounded-lg px-2 py-1">
                <button onClick={() => shiftDate(-1)} className="p-0.5 text-gray-400 hover:text-gray-700 transition-colors">
                  <ChevronLeft className="w-4 h-4" />
                </button>
                <input
                  type="date"
                  value={toISODate(selectedDate)}
                  onChange={(e) => setSelectedDate(new Date(e.target.value + "T00:00:00"))}
                  className="text-sm font-medium text-gray-700 border-none outline-none bg-transparent cursor-pointer"
                />
                <button onClick={() => shiftDate(1)} className="p-0.5 text-gray-400 hover:text-gray-700 transition-colors">
                  <ChevronRight className="w-4 h-4" />
                </button>
              </div>
            )}

            {preset === "custom" && (
              <div className="flex items-center gap-1.5 bg-white border border-gray-200 rounded-lg px-2 py-1">
                <input
                  type="date"
                  value={toISODate(customFrom)}
                  onChange={(e) => setCustomFrom(new Date(e.target.value + "T00:00:00"))}
                  className="text-sm text-gray-700 border-none outline-none bg-transparent cursor-pointer"
                />
                <span className="text-gray-400 text-xs">–</span>
                <input
                  type="date"
                  value={toISODate(customTo)}
                  onChange={(e) => setCustomTo(new Date(e.target.value + "T00:00:00"))}
                  className="text-sm text-gray-700 border-none outline-none bg-transparent cursor-pointer"
                />
              </div>
            )}

            {preset !== "today" && preset !== "custom" && (
              <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
                {periodLabel}
              </span>
            )}
          </div>
          <p className="text-sm text-gray-500 mt-1 flex items-center gap-2">
            {isLoading
              ? "Loading…"
              : `${items.length} SKUs · ${uniqueSupplierCount} suppliers`}
            {isUsingFallback && (
              <span className="badge-yellow">Sample data — no DB records for this period</span>
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
              <p className="text-gray-400 font-medium">No purchase orders for {periodLabel}</p>
              <p className="text-sm text-gray-400 mt-1">Add SKUs or select a different period</p>
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
                  date={periodLabel}
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

import { Suspense } from "react"
export default function PurchaseOrdersPageWrapper() {
  return (
    <Suspense>
      <PurchaseOrdersPage />
    </Suspense>
  )
}
