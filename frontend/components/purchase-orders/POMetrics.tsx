import { Receipt, CheckCircle, AlertTriangle } from "lucide-react"
import { POBalance, SKUItem, fmt } from "@/lib/purchase-orders"

interface Props {
  balance: POBalance
  items: SKUItem[]
}

export default function POMetrics({ balance, items }: Props) {
  const inStockCount = items.filter((i) => i.status !== "oversold").length
  const oversoldCount = items.filter((i) => i.status === "oversold").length

  return (
    <div className="grid grid-cols-3 gap-4 mb-6">
      <div className="card p-4 flex items-start gap-3">
        <div className="p-2 bg-blue-50 rounded-lg">
          <Receipt className="w-5 h-5 text-blue-600" />
        </div>
        <div>
          <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Total Cost Today</p>
          <p className="text-2xl font-bold text-gray-900 mt-0.5">${fmt(balance.total_cost)}</p>
          <p className="text-xs text-gray-500 mt-1">
            Ending balance: ${fmt(balance.ending_balance)}
          </p>
        </div>
      </div>

      <div className="card p-4 flex items-start gap-3">
        <div className="p-2 bg-green-50 rounded-lg">
          <CheckCircle className="w-5 h-5 text-green-600" />
        </div>
        <div>
          <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Available Value</p>
          <p className="text-2xl font-bold text-green-700 mt-0.5">${fmt(balance.available_value)}</p>
          <p className="text-xs text-gray-500 mt-1">{inStockCount} SKUs in stock</p>
        </div>
      </div>

      <div className="card p-4 flex items-start gap-3">
        <div className="p-2 bg-red-50 rounded-lg">
          <AlertTriangle className="w-5 h-5 text-red-500" />
        </div>
        <div>
          <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Oversold (A/R)</p>
          <p className={`text-2xl font-bold mt-0.5 ${balance.oversold_value > 0 ? "text-red-600" : "text-gray-400"}`}>
            ${fmt(balance.oversold_value)}
          </p>
          <p className="text-xs text-gray-500 mt-1">
            {oversoldCount > 0 ? `${oversoldCount} SKUs oversold` : "No oversold items"}
          </p>
        </div>
      </div>
    </div>
  )
}
