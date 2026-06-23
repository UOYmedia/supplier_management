"use client"

import { useEffect, useRef, useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import toast from "react-hot-toast"
import { purchaseRequestsApi } from "@/lib/api"

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

interface RequestListProps {
  username: string
  onPaidSuccess?: () => void
}

export default function RequestList({ username, onPaidSuccess }: RequestListProps) {
  const qc = useQueryClient()
  const isJenny = username.toLowerCase() === "jenny"

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
      if (vars.status === "PAID") {
        onPaidSuccess?.()
      }
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Update failed"),
  })

  function handleUpdate(id: number, status: string, extra?: { amount_paid?: number }) {
    mut.mutate({ id, status, extra })
  }

  if (isLoading) {
    return (
      <div className="animate-pulse space-y-2">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-10 bg-gray-100 rounded-lg" />
        ))}
      </div>
    )
  }

  if (requests.length === 0) {
    return (
      <div className="card p-12 text-center">
        <p className="text-gray-400 font-medium">No purchase requests yet</p>
      </div>
    )
  }

  return (
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
  )
}
