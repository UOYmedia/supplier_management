"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ordersApi } from "@/lib/api";
import toast from "react-hot-toast";
import { Plus, ChevronRight, RefreshCw } from "lucide-react";
import Link from "next/link";

const STATUSES = ["", "pending", "processing", "partially_fulfilled", "fulfilled", "cancelled"];
const MARKETS = ["", "amazon", "shopify", "manual"];

export default function OrdersPage() {
  const [status, setStatus] = useState("");
  const [marketplace, setMarketplace] = useState("");

  const { data: orders = [], isLoading, refetch } = useQuery({
    queryKey: ["orders", status, marketplace],
    queryFn: () => ordersApi.list({ status: status || undefined, marketplace: marketplace || undefined }),
  });

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Orders</h1>
        <button className="btn-secondary" onClick={() => refetch()}><RefreshCw className="w-4 h-4" />Refresh</button>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <select className="input w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
          {STATUSES.map((s) => <option key={s} value={s}>{s || "All statuses"}</option>)}
        </select>
        <select className="input w-40" value={marketplace} onChange={(e) => setMarketplace(e.target.value)}>
          {MARKETS.map((m) => <option key={m} value={m}>{m || "All channels"}</option>)}
        </select>
      </div>

      <div className="card table-wrapper">
        <table>
          <thead><tr>
            <th>Order ID</th><th>Channel</th><th>Buyer</th><th>Total</th><th>Status</th><th>Items</th><th>Date</th><th></th>
          </tr></thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={8} className="text-center py-8 text-gray-400">Loading…</td></tr>
            ) : orders.length === 0 ? (
              <tr><td colSpan={8} className="text-center py-8 text-gray-400">No orders found.</td></tr>
            ) : orders.map((o: any) => (
              <tr key={o.id}>
                <td>
                  <div className="font-medium">#{o.id}</div>
                  {o.external_order_id && <div className="text-xs text-gray-400 font-mono">{o.external_order_id}</div>}
                </td>
                <td><span className="capitalize badge-gray">{o.marketplace}</span></td>
                <td>
                  <div>{o.buyer_name || "—"}</div>
                  <div className="text-xs text-gray-400">{o.buyer_email}</div>
                </td>
                <td className="font-medium">${parseFloat(o.total).toFixed(2)} <span className="text-xs text-gray-400">{o.currency}</span></td>
                <td><OrderStatusBadge status={o.status} /></td>
                <td>{o.line_items?.length ?? 0}</td>
                <td className="text-xs text-gray-500">{new Date(o.ordered_at).toLocaleDateString()}</td>
                <td>
                  <Link href={`/orders/${o.id}`} className="p-1 hover:bg-gray-100 rounded text-gray-500">
                    <ChevronRight className="w-4 h-4" />
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function OrderStatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    pending: "badge-yellow",
    processing: "badge-blue",
    partially_fulfilled: "badge-blue",
    fulfilled: "badge-green",
    cancelled: "badge-red",
    refunded: "badge-gray",
  };
  return <span className={map[status] || "badge-gray"}>{status.replace(/_/g, " ")}</span>;
}
