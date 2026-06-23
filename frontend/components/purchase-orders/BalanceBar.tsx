import { POBalance, fmt } from "@/lib/purchase-orders"

interface Props {
  balance: POBalance
}

export default function BalanceBar({ balance }: Props) {
  const { total_cost, available_value, oversold_value } = balance

  if (total_cost === 0) {
    return (
      <div className="card p-4 mb-6">
        <p className="text-sm text-gray-400 text-center">No data</p>
      </div>
    )
  }

  const availPct = (available_value / total_cost) * 100
  const costPct = ((total_cost - oversold_value) / total_cost) * 100
  const oversoldPct = (oversold_value / total_cost) * 100

  return (
    <div className="card p-4 mb-6">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Balance Breakdown</p>
      <div className="h-2.5 rounded-full flex gap-0.5 overflow-hidden bg-gray-100">
        <div className="h-full rounded-l-full bg-green-400 transition-all" style={{ width: `${availPct}%` }} />
        <div className="h-full bg-blue-400 transition-all" style={{ width: `${Math.max(0, costPct - availPct)}%` }} />
        {oversoldPct > 0 && (
          <div className="h-full rounded-r-full bg-red-400 transition-all" style={{ width: `${oversoldPct}%` }} />
        )}
      </div>
      <div className="flex items-center gap-5 mt-3">
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-green-400 inline-block" />
          <span className="text-xs text-gray-600">Available value <span className="font-medium">${fmt(available_value)}</span></span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-blue-400 inline-block" />
          <span className="text-xs text-gray-600">Cost paid <span className="font-medium">${fmt(total_cost - oversold_value)}</span></span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="w-2.5 h-2.5 rounded-full bg-red-400 inline-block" />
          <span className="text-xs text-gray-600">Oversold A/R <span className="font-medium">${fmt(oversold_value)}</span></span>
        </div>
      </div>
    </div>
  )
}
