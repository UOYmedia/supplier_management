import { Supplier, SKUItem, SUPPLIER_INFO, fmt } from "@/lib/purchase-orders"

interface Props {
  supplier: Supplier
  poNumber: string
  items: SKUItem[]
}

export default function RemittanceSlip({ supplier, poNumber, items }: Props) {
  const info = SUPPLIER_INFO[supplier]
  const oversoldValue = items.reduce((s, i) => s + i.oversold_value, 0)
  const totalCost = items.reduce((s, i) => s + i.total_cost, 0)
  const balanceDue = totalCost - oversoldValue

  return (
    <div className="border border-dashed border-gray-300 rounded-lg p-3 mb-3">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-sm font-semibold text-gray-700">
            Remittance — {supplier} · {poNumber}
          </p>
          <p className="text-sm text-gray-600 mt-0.5">{info.name}</p>
          <p className="text-xs text-gray-400">{info.address}</p>
          <p className="text-xs text-gray-400">{info.city}</p>
          {oversoldValue > 0 && (
            <p className="text-xs text-red-500 mt-1">
              Oversold A/R: ${fmt(oversoldValue)} → accounting
            </p>
          )}
        </div>
        <div className="text-right shrink-0">
          <p className="text-xs text-gray-500 label mb-0">Balance Due</p>
          <p className="text-xl font-bold text-green-700">${fmt(balanceDue)}</p>
        </div>
      </div>
    </div>
  )
}
