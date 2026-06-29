import { AlertTriangle } from "lucide-react"
import { SKUItem, fmt } from "@/lib/purchase-orders"

interface Props {
  items: SKUItem[]
}

export default function OversoldNotice({ items }: Props) {
  const oversoldItems = items.filter((i) => i.status === "oversold")
  if (oversoldItems.length === 0) return null

  const total = oversoldItems.reduce((s, i) => s + i.oversold_value, 0)
  const detail = oversoldItems
    .map((i) => `${i.sku} (short ${i.oversold} × $${fmt(i.unit_cost)} = $${fmt(i.oversold_value)})`)
    .join(" · ")

  return (
    <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-3">
      <div className="flex items-start gap-2">
        <AlertTriangle className="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
        <div className="text-sm text-red-700">
          <span className="font-semibold">Oversold items: </span>
          {detail}
          <div className="mt-1 font-semibold">Total A/R: ${fmt(total)}</div>
        </div>
      </div>
    </div>
  )
}
