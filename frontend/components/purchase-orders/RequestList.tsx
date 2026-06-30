"use client"

import { useEffect, useRef, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import toast from "react-hot-toast"
import { Plus, X, Trash2, ChevronDown } from "lucide-react"
import { purchaseRequestsApi, suppliersApi } from "@/lib/api"

interface PurchaseRequest {
  id: number
  supplier: string
  sku: string
  product_name?: string | null
  qty_ordered: number
  unit_cost: string
  amount_paid: number
  status: string
  pic: string
  requested_date: string
  approved_by: string | null
  approved_date: string | null
  po_number: string
  notes: string | null
}

const PIC_COLORS: Record<string, string> = {
  zoe: "bg-pink-100 text-pink-700",
  grace: "bg-purple-100 text-purple-700",
  jenny: "bg-blue-100 text-blue-700",
}

const STATUS_STYLES: Record<string, string> = {
  PENDING: "bg-yellow-100 text-yellow-700",
  PARTIALLY_PAID: "bg-orange-100 text-orange-700",
  PAID: "bg-green-100 text-green-700",
  CANCELLED: "bg-red-100 text-red-700",
}

const STATUS_LABELS: Record<string, string> = {
  PENDING: "Pending",
  PARTIALLY_PAID: "Partially Paid",
  PAID: "Paid",
  CANCELLED: "Cancelled",
}

function PicBadge({ name }: { name: string }) {
  const cls = PIC_COLORS[name.toLowerCase()] ?? "bg-gray-100 text-gray-600"
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${cls}`}>
      {name}
    </span>
  )
}

function StatusDropdown({
  request,
  onUpdate,
}: {
  request: PurchaseRequest
  onUpdate: (id: number, status: string, extra?: { amount_paid?: number }) => void
}) {
  const [open, setOpen] = useState(false)
  const [partialAmt, setPartialAmt] = useState("")
  const [showPartialInput, setShowPartialInput] = useState(false)
  const [dropdownPos, setDropdownPos] = useState({ top: 0, left: 0 })
  const ref = useRef<HTMLDivElement>(null)
  const btnRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node) &&
          btnRef.current && !btnRef.current.contains(e.target as Node)) {
        setOpen(false)
        setShowPartialInput(false)
      }
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [])

  function handleOpen() {
    if (btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect()
      setDropdownPos({ top: rect.bottom + window.scrollY + 4, left: rect.left + window.scrollX })
    }
    setOpen((o) => !o)
    setShowPartialInput(false)
  }

  const canClick = request.status === "PENDING" || request.status === "PARTIALLY_PAID"
  if (!canClick) {
    return (
      <span
        className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[request.status] ?? "bg-gray-100 text-gray-600"}`}
      >
        {STATUS_LABELS[request.status] ?? request.status}
      </span>
    )
  }

  return (
    <div className="inline-block">
      <button
        ref={btnRef}
        onClick={handleOpen}
        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium cursor-pointer hover:opacity-80 transition-opacity ${STATUS_STYLES[request.status] ?? "bg-gray-100 text-gray-600"}`}
      >
        {STATUS_LABELS[request.status] ?? request.status}
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div
          ref={ref}
          style={{ position: "fixed", top: dropdownPos.top, left: dropdownPos.left }}
          className="z-50 bg-white border border-gray-200 rounded-lg shadow-lg min-w-[170px] py-1">
          <button
            className="w-full text-left px-3 py-2 text-sm text-green-700 hover:bg-green-50 transition-colors"
            onClick={() => {
              onUpdate(request.id, "PAID")
              setOpen(false)
            }}
          >
            Mark Paid
          </button>

          {showPartialInput ? (
            <div className="px-3 py-2 space-y-1">
              <p className="text-xs text-gray-500">Amount paid ($)</p>
              <input
                autoFocus
                type="number"
                min={0}
                step="0.01"
                value={partialAmt}
                onChange={(e) => setPartialAmt(e.target.value)}
                className="w-full border border-gray-300 rounded px-2 py-1 text-sm"
                placeholder="0.00"
              />
              <button
                className="w-full text-center bg-orange-500 text-white text-xs rounded py-1 hover:bg-orange-600 transition-colors"
                onClick={() => {
                  onUpdate(request.id, "PARTIALLY_PAID", { amount_paid: parseFloat(partialAmt) || 0 })
                  setOpen(false)
                  setShowPartialInput(false)
                }}
              >
                Confirm
              </button>
            </div>
          ) : (
            <button
              className="w-full text-left px-3 py-2 text-sm text-orange-700 hover:bg-orange-50 transition-colors"
              onClick={() => setShowPartialInput(true)}
            >
              Mark Partially Paid
            </button>
          )}

          <div className="border-t border-gray-100 my-1" />
          <button
            className="w-full text-left px-3 py-2 text-sm text-red-600 hover:bg-red-50 transition-colors"
            onClick={() => {
              onUpdate(request.id, "CANCELLED")
              setOpen(false)
            }}
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  )
}

function fmt(n: number) {
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtDate(d: string) {
  return new Date(d + "T00:00:00").toLocaleDateString("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
  })
}

function today() {
  return new Date().toISOString().slice(0, 10)
}

const EMPTY_HEADER = { supplier: "", pic: "", requested_date: today(), notes: "" }
const EMPTY_LINE = { sku: "", qty_ordered: "", unit_cost: "" }
type Line = typeof EMPTY_LINE

type CatalogItem = { sku: string; name: string; short_name?: string | null; unit_price: number | string }

// Searchable product picker: a button that opens a panel with a type-to-filter
// search box and the matching products below. Uses fixed positioning so the
// panel escapes the modal's scroll clipping (like StatusDropdown).
function ProductCombobox({
  products, value, onSelect, disabled, error, getLabel,
}: {
  products: CatalogItem[]
  value: string
  onSelect: (sku: string) => void
  disabled?: boolean
  error?: boolean
  getLabel: (c: CatalogItem) => string
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [pos, setPos] = useState({ top: 0, left: 0, width: 0 })
  const btnRef = useRef<HTMLButtonElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (
        panelRef.current && !panelRef.current.contains(e.target as Node) &&
        btnRef.current && !btnRef.current.contains(e.target as Node)
      ) setOpen(false)
    }
    document.addEventListener("mousedown", onDoc)
    return () => document.removeEventListener("mousedown", onDoc)
  }, [])

  const selected = products.find((p) => p.sku === value)
  const q = query.trim().toLowerCase()
  const filtered = q
    ? products.filter((p) => `${p.name} ${p.sku}`.toLowerCase().includes(q))
    : products

  function toggle() {
    if (disabled) return
    if (btnRef.current) {
      const r = btnRef.current.getBoundingClientRect()
      setPos({ top: r.bottom + window.scrollY + 4, left: r.left + window.scrollX, width: r.width })
    }
    setQuery("")
    setOpen((o) => !o)
  }

  return (
    <div className="flex-1 min-w-0">
      <button
        type="button"
        ref={btnRef}
        onClick={toggle}
        disabled={disabled}
        className={`w-full h-10 border rounded-lg px-2 text-sm text-left flex items-center justify-between gap-1 bg-white disabled:bg-gray-50 disabled:text-gray-400 ${error ? "border-red-500" : "border-gray-300"}`}
      >
        <span className={`truncate ${selected ? "text-gray-900" : "text-gray-400"}`}>
          {selected ? getLabel(selected) : (disabled ? "Select a supplier first" : "Select product…")}
        </span>
        <ChevronDown className="w-4 h-4 text-gray-400 shrink-0" />
      </button>
      {open && (
        <div
          ref={panelRef}
          style={{ position: "fixed", top: pos.top, left: pos.left, width: pos.width }}
          className="z-50 bg-white border border-gray-200 rounded-lg shadow-lg"
        >
          <div className="p-2 border-b border-gray-100">
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search product…"
              className="w-full h-8 px-2 text-sm border border-gray-200 rounded focus:outline-none focus:border-blue-400"
            />
          </div>
          <div className="max-h-60 overflow-y-auto py-1">
            {filtered.length === 0 ? (
              <p className="px-3 py-2 text-sm text-gray-400">No match</p>
            ) : filtered.map((p) => (
              <button
                type="button"
                key={p.sku}
                onClick={() => { onSelect(p.sku); setOpen(false) }}
                title={p.name}
                className={`w-full text-left px-3 py-1.5 text-sm hover:bg-blue-50 truncate ${p.sku === value ? "bg-blue-50 text-blue-700" : "text-gray-700"}`}
              >
                {getLabel(p)} <span className="text-gray-400">({p.sku})</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

interface RequestListProps {
  username: string
  canApprove?: boolean
  isAdmin?: boolean
  onPaidSuccess?: () => void
}

export default function RequestList({ username, canApprove = false, isAdmin = false, onPaidSuccess }: RequestListProps) {
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(EMPTY_HEADER)
  const [lines, setLines] = useState<Line[]>([{ ...EMPTY_LINE }])
  const [errors, setErrors] = useState<Record<string, boolean>>({})

  // Only stock-type suppliers (e.g. JOE) use the request flow — balance
  // suppliers ship direct and are paid per order via invoices, not requests.
  const { data: suppliers = [] } = useQuery<{ id: number; name: string }[]>({
    queryKey: ["suppliers-list"],
    queryFn: () => suppliersApi.list(),
    select: (data: any[]) =>
      data.filter((s) => s.supplier_type === "stock").map((s) => ({ id: s.id, name: s.name })),
  })

  const selectedSupplier = suppliers.find((s) => s.name === form.supplier)

  // Catalog SKUs for the chosen supplier — the request item is picked from here
  // so its sku matches a SupplierProduct exactly (stock increment on PAID relies on it).
  const { data: catalog = [] } = useQuery<{ sku: string; name: string; short_name?: string | null; unit_price: number | string }[]>({
    queryKey: ["supplier-catalog", selectedSupplier?.id],
    queryFn: () => suppliersApi.listProducts(selectedSupplier!.id),
    enabled: !!selectedSupplier,
  })

  // Product names are full marketplace titles; a native <select> grows as wide
  // as its longest option and overflows. Show the short name (or a clipped name).
  function optionLabel(c: { name: string; short_name?: string | null }) {
    const short = c.short_name?.trim()
    if (short) return short
    return c.name.length > 55 ? c.name.slice(0, 55).trimEnd() + "…" : c.name
  }

  const { data: requests = [], isLoading } = useQuery<PurchaseRequest[]>({
    queryKey: ["purchase-requests"],
    queryFn: () => purchaseRequestsApi.list(),
  })

  const mut = useMutation({
    mutationFn: ({ id, status, extra }: { id: number; status: string; extra?: { amount_paid?: number } }) =>
      purchaseRequestsApi.updateStatus(id, { status, ...extra }),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ["purchase-requests"] })
      toast.success(`Marked as ${STATUS_LABELS[vars.status] ?? vars.status}`)
      if (vars.status === "PAID") onPaidSuccess?.()
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Update failed"),
  })

  const createMut = useMutation({
    mutationFn: (data: object) => purchaseRequestsApi.createBatch(data),
    onSuccess: (rows: any[]) => {
      qc.invalidateQueries({ queryKey: ["purchase-requests"] })
      toast.success(`${Array.isArray(rows) ? rows.length : 0} request(s) created`)
      setShowForm(false)
      setForm(EMPTY_HEADER)
      setLines([{ ...EMPTY_LINE }])
      setErrors({})
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Failed to create requests"),
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => purchaseRequestsApi.remove(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["purchase-requests"] })
      toast.success("Request deleted")
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Delete failed"),
  })

  function handleUpdate(id: number, status: string, extra?: { amount_paid?: number }) {
    mut.mutate({ id, status, extra })
  }

  function handleDelete(r: PurchaseRequest) {
    const label = `${r.supplier} · ${r.sku}`
    if (confirm(`Delete this request?\n\n${label}\n\nIf it was already Paid, the stock it added will be reversed.`)) {
      deleteMut.mutate(r.id)
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    const newErrors: Record<string, boolean> = {
      supplier: !form.supplier,
      pic: !form.pic.trim(),
    }
    lines.forEach((l, i) => {
      if (!l.sku.trim()) newErrors[`line_${i}_sku`] = true
      if (!l.qty_ordered) newErrors[`line_${i}_qty`] = true
      if (!l.unit_cost) newErrors[`line_${i}_cost`] = true
    })
    setErrors(newErrors)
    if (Object.values(newErrors).some(Boolean)) return
    createMut.mutate({
      supplier: form.supplier,
      supplier_id: selectedSupplier?.id,
      pic: form.pic.trim(),
      requested_date: form.requested_date || today(),
      notes: form.notes.trim() || null,
      items: lines.map((l) => ({
        sku: l.sku.trim(),
        qty_ordered: parseInt(l.qty_ordered),
        qty_available: 0,
        unit_cost: parseFloat(l.unit_cost),
      })),
    })
  }

  function setHeader(field: string, value: string) {
    setForm((f) => ({ ...f, [field]: value }))
    // Changing supplier invalidates SKUs/costs picked from the old catalog.
    if (field === "supplier") setLines([{ ...EMPTY_LINE }])
    if (errors[field]) setErrors((e) => ({ ...e, [field]: false }))
  }

  function setLine(idx: number, field: keyof Line, value: string) {
    setLines((ls) => ls.map((l, i) => (i === idx ? { ...l, [field]: value } : l)))
    const key = field === "qty_ordered" ? `line_${idx}_qty` : field === "unit_cost" ? `line_${idx}_cost` : `line_${idx}_sku`
    if (errors[key]) setErrors((e) => ({ ...e, [key]: false }))
  }

  // Picking a catalog SKU auto-fills that line's unit cost (still editable).
  function pickSkuLine(idx: number, sku: string) {
    const prod = catalog.find((c) => c.sku === sku)
    setLines((ls) => ls.map((l, i) => (i === idx ? { ...l, sku, unit_cost: prod ? String(prod.unit_price) : l.unit_cost } : l)))
    if (errors[`line_${idx}_sku`]) setErrors((e) => ({ ...e, [`line_${idx}_sku`]: false }))
  }

  function addLine() { setLines((ls) => [...ls, { ...EMPTY_LINE }]) }
  function removeLine(idx: number) { setLines((ls) => (ls.length > 1 ? ls.filter((_, i) => i !== idx) : ls)) }

  const grandTotal = lines.reduce(
    (s, l) => s + (parseFloat(l.qty_ordered) || 0) * (parseFloat(l.unit_cost) || 0),
    0,
  )

  return (
    <div>
      {/* Header row */}
      <div className="flex items-center justify-between mb-4">
        <p className="text-sm text-gray-500">
          {requests.filter((r) => r.status === "PENDING").length} pending
        </p>
        <button
          className="btn-primary flex items-center gap-1.5 text-sm"
          onClick={() => setShowForm(true)}
        >
          <Plus className="w-4 h-4" />
          Add Request
        </button>
      </div>

      {/* Add Request modal */}
      {showForm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl mx-4 p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-5">
              <h2 className="text-base font-semibold text-gray-900">New Purchase Request</h2>
              <button onClick={() => setShowForm(false)} className="text-gray-400 hover:text-gray-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Supplier <span className="text-red-500">*</span></label>
                  <select
                    value={form.supplier}
                    onChange={(e) => setHeader("supplier", e.target.value)}
                    className={`w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white ${errors.supplier ? "border-red-500" : "border-gray-300"}`}
                  >
                    <option value="">Select supplier…</option>
                    {suppliers.map((s) => (
                      <option key={s.id} value={s.name}>{s.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">PIC <span className="text-red-500">*</span></label>
                  <select
                    value={form.pic}
                    onChange={(e) => setHeader("pic", e.target.value)}
                    className={`w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white ${errors.pic ? "border-red-500" : "border-gray-300"}`}
                  >
                    <option value="">Select PIC…</option>
                    <option value="Zoe">Zoe</option>
                    <option value="Grace">Grace</option>
                    <option value="Jenny">Jenny</option>
                  </select>
                </div>
              </div>

              {/* Product lines */}
              <div>
                <div className="flex items-center justify-between mb-1">
                  <label className="block text-xs font-medium text-gray-600">Products <span className="text-red-500">*</span></label>
                  <button
                    type="button"
                    onClick={addLine}
                    disabled={!selectedSupplier}
                    className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline disabled:text-gray-300 disabled:no-underline"
                  >
                    <Plus className="w-3 h-3" /> Add product
                  </button>
                </div>

                {/* Column labels */}
                <div className="flex items-center gap-2 mb-1 text-[10px] font-medium text-gray-400 uppercase tracking-wide">
                  <div className="flex-1 min-w-0">Product / SKU</div>
                  <div className="w-16 text-center shrink-0">Qty</div>
                  <div className="w-24 shrink-0">Unit Cost</div>
                  <div className="w-24 text-right shrink-0">Total</div>
                  <div className="w-7 shrink-0" />
                </div>

                <div className="space-y-2">
                  {lines.map((l, idx) => {
                    const lineTotal = (parseFloat(l.qty_ordered) || 0) * (parseFloat(l.unit_cost) || 0)
                    return (
                    <div key={idx} className="flex items-center gap-2">
                      <ProductCombobox
                        products={catalog}
                        value={l.sku}
                        onSelect={(sku) => pickSkuLine(idx, sku)}
                        disabled={!selectedSupplier}
                        error={!!errors[`line_${idx}_sku`]}
                        getLabel={optionLabel}
                      />
                      <input
                        type="number"
                        min={1}
                        value={l.qty_ordered}
                        onChange={(e) => setLine(idx, "qty_ordered", e.target.value)}
                        className={`w-16 shrink-0 h-10 border rounded-lg px-2 text-sm text-center focus:outline-none focus:ring-2 focus:ring-blue-500 ${errors[`line_${idx}_qty`] ? "border-red-500" : "border-gray-300"}`}
                        placeholder="0"
                      />
                      <input
                        type="number"
                        min={0}
                        step="0.01"
                        value={l.unit_cost}
                        onChange={(e) => setLine(idx, "unit_cost", e.target.value)}
                        className={`w-24 shrink-0 h-10 border rounded-lg px-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${errors[`line_${idx}_cost`] ? "border-red-500" : "border-gray-300"}`}
                        placeholder="0.00"
                      />
                      <div className="w-24 shrink-0 text-right text-sm font-medium text-gray-800 tabular-nums">
                        ${fmt(lineTotal)}
                      </div>
                      <button
                        type="button"
                        onClick={() => removeLine(idx)}
                        disabled={lines.length === 1}
                        title="Remove"
                        className="w-7 shrink-0 flex justify-center p-1 text-gray-400 hover:text-red-500 disabled:opacity-30 disabled:cursor-not-allowed"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  )})}
                </div>

                {/* Grand total */}
                <div className="flex items-center gap-2 mt-2 pt-2 border-t border-gray-200">
                  <div className="flex-1 min-w-0 text-right text-xs font-medium text-gray-500 uppercase tracking-wide">
                    Total ({lines.length} product{lines.length !== 1 ? "s" : ""})
                  </div>
                  <div className="w-24 shrink-0 text-right text-sm font-bold text-gray-900 tabular-nums">
                    ${fmt(grandTotal)}
                  </div>
                  <div className="w-7 shrink-0" />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Date</label>
                  <input
                    type="date"
                    value={form.requested_date}
                    onChange={(e) => setHeader("requested_date", e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Notes</label>
                  <input
                    value={form.notes}
                    onChange={(e) => setHeader("notes", e.target.value)}
                    placeholder="Optional notes…"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>

              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={() => setShowForm(false)}
                  className="btn-secondary text-sm"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createMut.isPending}
                  className="btn-primary text-sm"
                >
                  {createMut.isPending ? "Saving…" : `Submit Request${lines.length > 1 ? ` (${lines.length})` : ""}`}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* List */}
      {isLoading ? (
        <div className="animate-pulse space-y-2">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-10 bg-gray-100 rounded-lg" />
          ))}
        </div>
      ) : requests.length === 0 ? (
        <div className="card p-12 text-center">
          <p className="text-gray-400 font-medium">No purchase requests yet</p>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50">
                  {["DATE", "PIC", "SUPPLIER", "PRODUCT", "QTY", "COST", "AMOUNT PAID", "STATUS"].map((h) => (
                    <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">
                      {h}
                    </th>
                  ))}
                  {isAdmin && <th className="px-4 py-3" />}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {requests.map((r) => {
                  const unitCost = parseFloat(r.unit_cost)
                  const total = unitCost * r.qty_ordered
                  return (
                    <tr key={r.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3 text-gray-600 whitespace-nowrap">{fmtDate(r.requested_date)}</td>
                      <td className="px-4 py-3 whitespace-nowrap">
                        <PicBadge name={r.pic} />
                      </td>
                      <td className="px-4 py-3 font-medium text-gray-800">{r.supplier}</td>
                      <td className="px-4 py-3 max-w-[240px]" title={r.product_name || r.sku}>
                        {r.product_name ? (
                          <div className="leading-tight">
                            <div className="text-gray-800 truncate">{r.product_name}</div>
                            <div className="text-[11px] text-gray-400 font-mono truncate">{r.sku}</div>
                          </div>
                        ) : (
                          <span className="text-gray-700 font-mono text-xs">{r.sku}</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-700 text-right">{r.qty_ordered}</td>
                      <td className="px-4 py-3 text-gray-700 text-right">${fmt(total)}</td>
                      <td className="px-4 py-3 text-right">
                        {r.amount_paid > 0 ? (
                          <span className="text-green-700 font-medium">${fmt(r.amount_paid)}</span>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {canApprove ? (
                          <StatusDropdown request={r} onUpdate={handleUpdate} />
                        ) : (
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[r.status] ?? "bg-gray-100 text-gray-600"}`}
                          >
                            {STATUS_LABELS[r.status] ?? r.status}
                          </span>
                        )}
                      </td>
                      {isAdmin && (
                        <td className="px-4 py-3 text-right">
                          <button
                            onClick={() => handleDelete(r)}
                            disabled={deleteMut.isPending}
                            title="Delete request"
                            className="p-1 text-gray-400 hover:text-red-500 transition-colors disabled:opacity-40"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
