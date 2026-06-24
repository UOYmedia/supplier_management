"use client"

import { useState } from "react"
import { ChevronUp, ChevronDown, ChevronsUpDown, X } from "lucide-react"
import { SKUItem, fmt } from "@/lib/purchase-orders"

interface Props {
  items: SKUItem[]
}

type SortKey = "sku" | "available" | "ordered" | "gap" | "oversold" | "total_cost" | "avail_value" | "status"
type SortDir = "asc" | "desc" | null
type StatusFilter = "all" | "ok" | "low" | "oversold"

const STATUS_ORDER: Record<string, number> = { oversold: 0, low: 1, ok: 2 }

const FILTER_OPTS: { key: StatusFilter; label: string; cls: string; active: string }[] = [
  { key: "all",      label: "All",      cls: "text-gray-500 hover:text-gray-700",    active: "bg-gray-800 text-white" },
  { key: "ok",       label: "OK",       cls: "text-green-600 hover:bg-green-50",     active: "bg-green-600 text-white" },
  { key: "low",      label: "Low",      cls: "text-yellow-600 hover:bg-yellow-50",   active: "bg-yellow-500 text-white" },
  { key: "oversold", label: "Oversold", cls: "text-red-600 hover:bg-red-50",         active: "bg-red-500 text-white" },
]

interface ColFilters {
  sku: string
  available: string
  ordered: string
  gap: string
  oversold: string
}

const EMPTY_COL: ColFilters = { sku: "", available: "", ordered: "", gap: "", oversold: "" }

function sortItems(items: SKUItem[], key: SortKey, dir: SortDir): SKUItem[] {
  if (!dir) return items
  return [...items].sort((a, b) => {
    let va: number | string, vb: number | string
    if (key === "status") {
      va = STATUS_ORDER[a.status] ?? 99
      vb = STATUS_ORDER[b.status] ?? 99
    } else if (key === "sku") {
      va = a.sku.toLowerCase()
      vb = b.sku.toLowerCase()
    } else {
      va = a[key] as number
      vb = b[key] as number
    }
    if (va < vb) return dir === "asc" ? -1 : 1
    if (va > vb) return dir === "asc" ? 1 : -1
    return 0
  })
}

function applyColFilters(items: SKUItem[], f: ColFilters): SKUItem[] {
  return items.filter((i) => {
    if (f.sku && !i.sku.toLowerCase().includes(f.sku.toLowerCase())) return false
    if (f.available !== "") {
      const n = parseFloat(f.available)
      if (!isNaN(n) && i.available < n) return false
    }
    if (f.ordered !== "") {
      const n = parseFloat(f.ordered)
      if (!isNaN(n) && i.ordered < n) return false
    }
    if (f.gap !== "") {
      const n = parseFloat(f.gap)
      if (!isNaN(n) && Math.max(0, i.gap) < n) return false
    }
    if (f.oversold !== "") {
      const n = parseFloat(f.oversold)
      if (!isNaN(n) && i.oversold < n) return false
    }
    return true
  })
}

function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  if (!active || !dir) return <ChevronsUpDown className="w-3 h-3 text-gray-400 inline ml-0.5" />
  return dir === "asc"
    ? <ChevronUp className="w-3 h-3 text-blue-500 inline ml-0.5" />
    : <ChevronDown className="w-3 h-3 text-blue-500 inline ml-0.5" />
}

function Th({
  label, sub, colKey, sortKey, sortDir, onSort, className = "",
}: {
  label: string; sub?: string; colKey: SortKey
  sortKey: SortKey; sortDir: SortDir
  onSort: (k: SortKey) => void
  className?: string
}) {
  const active = sortKey === colKey
  return (
    <th
      className={`px-3 py-2 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide cursor-pointer select-none whitespace-nowrap hover:bg-gray-100 transition-colors ${className}`}
      onClick={() => onSort(colKey)}
    >
      <span className="inline-flex flex-col leading-tight">
        <span>{label} <SortIcon active={active} dir={active ? sortDir : null} /></span>
        {sub && <span className="text-[10px] font-normal text-gray-400 normal-case">{sub}</span>}
      </span>
    </th>
  )
}

// Thin input inside filter row cells
function FilterInput({
  value, onChange, placeholder, type = "text", className = "",
}: {
  value: string; onChange: (v: string) => void
  placeholder?: string; type?: string; className?: string
}) {
  return (
    <div className="relative">
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`w-full h-6 px-1.5 text-xs border border-gray-200 rounded focus:border-blue-400 outline-none bg-white placeholder-gray-300 ${className}`}
      />
      {value && (
        <button
          onClick={() => onChange("")}
          className="absolute right-0.5 top-1/2 -translate-y-1/2 text-gray-300 hover:text-gray-500"
        >
          <X className="w-3 h-3" />
        </button>
      )}
    </div>
  )
}

function StatusBadge({ status, gap, oversold }: { status: string; gap: number; oversold: number }) {
  if (status === "ok")  return <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">OK</span>
  if (status === "low") return <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-700">Low {gap > 0 ? `+${gap}` : ""}</span>
  return <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700">Oversold {oversold}</span>
}

export default function SKUTable({ items }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("sku")
  const [sortDir, setSortDir] = useState<SortDir>(null)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all")
  const [col, setCol] = useState<ColFilters>(EMPTY_COL)

  function handleSort(key: SortKey) {
    if (sortKey !== key) { setSortKey(key); setSortDir("asc"); return }
    setSortDir((d) => d === "asc" ? "desc" : d === "desc" ? null : "asc")
  }

  function setColField<K extends keyof ColFilters>(k: K, v: string) {
    setCol((prev) => ({ ...prev, [k]: v }))
  }

  const hasColFilter = Object.values(col).some(Boolean)

  const colFiltered = applyColFilters(items, col)
  const statusFiltered = statusFilter === "all" ? colFiltered : colFiltered.filter((i) => i.status === statusFilter)
  const sorted = sortItems(statusFiltered, sortKey, sortDir)

  const counts: Record<StatusFilter, number> = {
    all:      colFiltered.length,
    ok:       colFiltered.filter((i) => i.status === "ok").length,
    low:      colFiltered.filter((i) => i.status === "low").length,
    oversold: colFiltered.filter((i) => i.status === "oversold").length,
  }

  return (
    <div>
      {/* Status quick filter */}
      <div className="flex items-center gap-1 mb-2">
        {FILTER_OPTS.map(({ key, label, cls, active }) => (
          <button
            key={key}
            onClick={() => setStatusFilter(key)}
            className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-colors border ${
              statusFilter === key
                ? `${active} border-transparent`
                : `bg-white border-gray-200 ${cls}`
            }`}
          >
            {label}
            <span className={`text-[10px] font-semibold ${statusFilter === key ? "opacity-80" : "text-gray-400"}`}>
              {counts[key]}
            </span>
          </button>
        ))}
        {hasColFilter && (
          <button
            onClick={() => setCol(EMPTY_COL)}
            className="ml-auto inline-flex items-center gap-1 px-2 py-1 text-xs text-gray-400 hover:text-red-500 transition-colors"
          >
            <X className="w-3 h-3" /> Clear filters
          </button>
        )}
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-100">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-b border-gray-100">
              <Th label="Item"        colKey="sku"         sortKey={sortKey} sortDir={sortDir} onSort={handleSort} className="min-w-[160px]" />
              <Th label="Stock Avail" colKey="available"   sortKey={sortKey} sortDir={sortDir} onSort={handleSort} className="text-blue-600" />
              <Th label="Ordered"     colKey="ordered"     sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <Th label="Stock Left"  colKey="gap"         sub="avail − ordered" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <Th label="Oversold"    colKey="oversold"    sortKey={sortKey} sortDir={sortDir} onSort={handleSort} className="text-red-500" />
              <Th label="Today Cost"  colKey="total_cost"  sub="price × ordered" sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <Th label="Amt Left"    colKey="avail_value" sub="price × left"    sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
              <Th label="Status"      colKey="status"      sortKey={sortKey} sortDir={sortDir} onSort={handleSort} />
            </tr>

            {/* Column filter row */}
            <tr className="bg-white border-b border-gray-100">
              <td className="px-2 py-1">
                <FilterInput value={col.sku} onChange={(v) => setColField("sku", v)} placeholder="Search name…" />
              </td>
              <td className="px-2 py-1">
                <FilterInput type="number" value={col.available} onChange={(v) => setColField("available", v)} placeholder="≥" />
              </td>
              <td className="px-2 py-1">
                <FilterInput type="number" value={col.ordered} onChange={(v) => setColField("ordered", v)} placeholder="≥" />
              </td>
              <td className="px-2 py-1">
                <FilterInput type="number" value={col.gap} onChange={(v) => setColField("gap", v)} placeholder="≥" />
              </td>
              <td className="px-2 py-1">
                <FilterInput type="number" value={col.oversold} onChange={(v) => setColField("oversold", v)} placeholder="≥" />
              </td>
              <td />
              <td />
              <td />
            </tr>
          </thead>

          <tbody className="divide-y divide-gray-50">
            {sorted.length === 0 ? (
              <tr>
                <td colSpan={8} className="px-3 py-8 text-center text-sm text-gray-400">
                  No items match the current filters
                </td>
              </tr>
            ) : sorted.map((item) => {
              const rowBg = "hover:bg-gray-50"

              const stockLeftColor =
                item.status === "oversold" ? "text-red-600 font-semibold" :
                item.status === "low"      ? "text-amber-600 font-semibold" :
                                            "text-green-700"

              const amtLeftColor =
                item.avail_value < 0 ? "text-red-600 font-semibold" :
                item.avail_value === 0 ? "text-amber-600" : "text-green-700 font-medium"

              return (
                <tr key={item.sku} className={`transition-colors ${rowBg}`}>
                  <td className="px-3 py-2.5">
                    <span className="font-medium text-gray-800 cursor-default" title={`Unit price: $${fmt(item.unit_cost)}`}>
                      {item.sku}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-blue-700 font-medium text-right">{item.available}</td>
                  <td className="px-3 py-2.5 text-gray-700 text-right">{item.ordered}</td>
                  <td className={`px-3 py-2.5 text-right ${stockLeftColor}`}>{Math.max(0, item.gap)}</td>
                  <td className="px-3 py-2.5 text-right">
                    {item.oversold > 0
                      ? <span className="text-red-600 font-semibold">{item.oversold}</span>
                      : <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-3 py-2.5 text-right text-gray-800 font-medium">${fmt(item.total_cost)}</td>
                  <td className={`px-3 py-2.5 text-right ${amtLeftColor}`}>
                    {item.avail_value < 0
                      ? `−$${fmt(Math.abs(item.avail_value))}`
                      : `$${fmt(item.avail_value)}`}
                  </td>
                  <td className="px-3 py-2.5">
                    <StatusBadge status={item.status} gap={item.gap} oversold={item.oversold} />
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
