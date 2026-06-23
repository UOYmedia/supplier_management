import { SKUItem, fmt } from "@/lib/purchase-orders"

interface Props {
  items: SKUItem[]
}

function StatusBadge({ item }: { item: SKUItem }) {
  if (item.status === "ok")
    return <span className="badge-green">OK</span>
  if (item.status === "low")
    return <span className="badge-yellow">Low +{item.gap}</span>
  if (item.status === "exact")
    return <span className="badge-yellow">Exact</span>
  return <span className="badge-red">Oversold {item.oversold}</span>
}

function GapCell({ item }: { item: SKUItem }) {
  if (item.gap < 0)
    return <span className="text-red-600 font-semibold">{item.gap}</span>
  if (item.gap === 0)
    return <span className="text-amber-600 font-semibold">0</span>
  return <span className="text-green-700">+{item.gap}</span>
}

export default function SKUTable({ items }: Props) {
  return (
    <div className="table-wrapper">
      <table>
        <thead>
          <tr>
            <th>Item</th>
            <th>Ordered</th>
            <th>Available</th>
            <th>Gap</th>
            <th className="text-center">Oversold</th>
            <th>Unit $</th>
            <th>Total</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item, idx) => (
            <tr
              key={item.sku}
              className={
                item.status === "oversold"
                  ? "bg-red-50"
                  : item.status === "exact"
                  ? "bg-amber-50/40"
                  : idx % 2 === 0
                  ? "bg-white"
                  : "bg-gray-50"
              }
            >
              <td className="font-medium text-gray-800">{item.sku}</td>
              <td>{item.ordered}</td>
              <td>{item.available}</td>
              <td><GapCell item={item} /></td>
              <td className="text-center">
                {item.gap < 0
                  ? <span className="text-red-700 font-semibold">{item.oversold}</span>
                  : <span className="text-gray-300">—</span>}
              </td>
              <td>${fmt(item.unit_cost)}</td>
              <td className="font-medium">${fmt(item.total_cost)}</td>
              <td><StatusBadge item={item} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
