"use client"

import { useEffect, useRef, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import toast from "react-hot-toast"
import { Plus, X } from "lucide-react"
import { purchaseRequestsApi, suppliersApi } from "@/lib/api"

interface PurchaseRequest {
  id: number
  supplier: string
  sku: string
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
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setShowPartialInput(false)
      }
    }
    document.addEventListener("mousedown", handleClick)
    return () => document.removeEventListener("mousedown", handleClick)
  }, [])

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
    <div className="relative inline-block" ref={ref}>
      <button
        onClick={() => { setOpen((o) => !o); setShowPartialInput(false) }}
        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium cursor-pointer hover:opacity-80 transition-opacity ${STATUS_STYLES[request.status] ?? "bg-gray-100 text-gray-600"}`}
      >
        {STATUS_LABELS[request.status] ?? request.status}
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1 z-50 bg-white border border-gray-200 rounded-lg shadow-lg min-w-[170px] py-1">
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

const EMPTY_FORM = {
  supplier: "",
  sku: "",
  qty_ordered: "",
  qty_available: "",
  unit_cost: "",
  po_number: "",
  pic: "",
  requested_date: today(),
  notes: "",
}

interface RequestListProps {
  username: string
  onPaidSuccess?: () => void
}

export default function RequestList({ username, onPaidSuccess }: RequestListProps) {
  const qc = useQueryClient()
  const isJenny = username.toLowerCase() === "jenny"
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(EMPTY_FORM)

  const { data: suppliers = [] } = useQuery<{ id: number; name: string }[]>({
    queryKey: ["suppliers-list"],
    queryFn: () => suppliersApi.list(),
    select: (data: any[]) => data.map((s) => ({ id: s.id, name: s.name })),
  })

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
    mutationFn: (data: object) => purchaseRequestsApi.create(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["purchase-requests"] })
      toast.success("Request created")
      setShowForm(false)
      setForm(EMPTY_FORM)
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Failed to create request"),
  })

  function handleUpdate(id: number, status: string, extra?: { amount_paid?: number }) {
    mut.mutate({ id, status, extra })
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.supplier || !form.sku || !form.qty_ordered || !form.unit_cost || !form.po_number || !form.pic) {
      toast.error("Please fill in all required fields")
      return
    }
    createMut.mutate({
      supplier: form.supplier,
      sku: form.sku.trim(),
      qty_ordered: parseInt(form.qty_ordered),
      qty_available: form.qty_available ? parseInt(form.qty_available) : 0,
      unit_cost: parseFloat(form.unit_cost),
      po_number: form.po_number.trim(),
      pic: form.pic.trim(),
      requested_date: form.requested_date || today(),
      notes: form.notes.trim() || null,
    })
  }

  function set(field: string, value: string) {
    setForm((f) => ({ ...f, [field]: value }))
  }

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
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg mx-4 p-6">
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
                    onChange={(e) => set("supplier", e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                  >
                    <option value="">Select supplier…</option>
                    {suppliers.map((s) => (
                      <option key={s.id} value={s.name}>{s.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">PIC <span className="text-red-500">*</span></label>
                  <input
                    type="text"
                    value={form.pic}
                    onChange={(e) => set("pic", e.target.value)}
                    placeholder="Your name"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Product / SKU <span className="text-red-500">*</span></label>
                <input
                  type="text"
                  value={form.sku}
                  onChange={(e) => set("sku", e.target.value)}
                  placeholder="e.g. Meyer Lemon Tree"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Qty Ordered <span className="text-red-500">*</span></label>
                  <input
                    type="number"
                    min={1}
                    value={form.qty_ordered}
                    onChange={(e) => set("qty_ordered", e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="0"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Qty Available</label>
                  <input
                    type="number"
                    min={0}
                    value={form.qty_available}
                    onChange={(e) => set("qty_available", e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="0"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Unit Cost ($) <span className="text-red-500">*</span></label>
                  <input
                    type="number"
                    min={0}
                    step="0.01"
                    value={form.unit_cost}
                    onChange={(e) => set("unit_cost", e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="0.00"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">PO Number <span className="text-red-500">*</span></label>
                  <input
                    type="text"
                    value={form.po_number}
                    onChange={(e) => set("po_number", e.target.value)}
                    placeholder="e.g. PO-2026-0623-JOE"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-600 mb-1">Date</label>
                  <input
                    type="date"
                    value={form.requested_date}
                    onChange={(e) => set("requested_date", e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>

              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">Notes</label>
                <textarea
                  value={form.notes}
                  onChange={(e) => set("notes", e.target.value)}
                  rows={2}
                  placeholder="Optional notes..."
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                />
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
                  {createMut.isPending ? "Saving…" : "Submit Request"}
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
                      <td className="px-4 py-3 text-gray-700 max-w-[200px] truncate" title={r.sku}>{r.sku}</td>
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
                        {isJenny ? (
                          <StatusDropdown request={r} onUpdate={handleUpdate} />
                        ) : (
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[r.status] ?? "bg-gray-100 text-gray-600"}`}
                          >
                            {STATUS_LABELS[r.status] ?? r.status}
                          </span>
                        )}
                      </td>
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
