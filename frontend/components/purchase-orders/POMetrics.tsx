import { ArrowRight, TrendingDown, CheckCircle, AlertTriangle } from "lucide-react"
import { POBalance, SKUItem, fmt } from "@/lib/purchase-orders"

interface Props {
  balance: POBalance
  items: SKUItem[]
}

export default function POMetrics({ balance, items }: Props) {
  const inStockCount  = items.filter((i) => i.status !== "oversold").length
  const oversoldCount = items.filter((i) => i.status === "oversold").length
  const endingColor   = balance.ending_balance >= 0 ? "text-green-700" : "text-red-600"

  return (
    <div className="space-y-3 mb-6">
      {/* Row 1 — Balance flow: Starting → Cost → Ending */}
      <div className="card p-4">
        <p className="text-xs text-gray-400 font-medium uppercase tracking-wide mb-3">Daily Balance</p>
        <div className="flex items-center gap-2">
          {/* Starting */}
          <div className="flex-1 text-center">
            <p className="text-[11px] text-gray-400 mb-0.5">Starting Balance</p>
            <p className="text-xl font-bold text-gray-700">${fmt(balance.starting_balance)}</p>
          </div>

          {/* Arrow + cost */}
          <div className="flex flex-col items-center px-2">
            <div className="flex items-center gap-1 text-red-500">
              <TrendingDown className="w-3.5 h-3.5" />
              <span className="text-xs font-semibold">−${fmt(balance.total_cost)}</span>
            </div>
            <ArrowRight className="w-5 h-5 text-gray-300 mt-0.5" />
            <span className="text-[10px] text-gray-400">Today cost</span>
          </div>

          {/* Ending */}
          <div className="flex-1 text-center">
            <p className="text-[11px] text-gray-400 mb-0.5">Ending Balance</p>
            <p className={`text-xl font-bold ${endingColor}`}>${fmt(balance.ending_balance)}</p>
          </div>
        </div>
      </div>

      {/* Row 2 — Available Value + Oversold */}
      <div className="grid grid-cols-2 gap-3">
        <div className="card p-4 flex items-start gap-3">
          <div className="p-2 bg-green-50 rounded-lg">
            <CheckCircle className="w-4 h-4 text-green-600" />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Available Value</p>
            <p className="text-xl font-bold text-green-700 mt-0.5">${fmt(balance.available_value)}</p>
            <p className="text-xs text-gray-400 mt-0.5">{inStockCount} SKUs in stock</p>
          </div>
        </div>

        <div className="card p-4 flex items-start gap-3">
          <div className="p-2 bg-red-50 rounded-lg">
            <AlertTriangle className="w-4 h-4 text-red-500" />
          </div>
          <div>
            <p className="text-xs text-gray-500 font-medium uppercase tracking-wide">Oversold (A/R)</p>
            <p className={`text-xl font-bold mt-0.5 ${balance.oversold_value > 0 ? "text-red-600" : "text-gray-400"}`}>
              ${fmt(balance.oversold_value)}
            </p>
            <p className="text-xs text-gray-400 mt-0.5">
              {oversoldCount > 0 ? `${oversoldCount} SKUs oversold` : "No oversold items"}
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
