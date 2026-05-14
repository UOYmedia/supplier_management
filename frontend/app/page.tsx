"use client";
import { useQuery } from "@tanstack/react-query";
import { reportsApi } from "@/lib/api";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { TrendingUp, ShoppingCart, Package, AlertTriangle } from "lucide-react";

export default function DashboardPage() {
  const { data: summary } = useQuery({ queryKey: ["summary"], queryFn: () => reportsApi.summary() });
  const { data: byMarket } = useQuery({ queryKey: ["by-marketplace"], queryFn: reportsApi.byMarketplace });
  const { data: alerts } = useQuery({ queryKey: ["inventory-alert"], queryFn: () => reportsApi.inventoryAlert(5) });

  const stats = [
    { label: "Total Revenue", value: `$${(summary?.total_revenue ?? 0).toLocaleString()}`, icon: TrendingUp, color: "text-green-600" },
    { label: "Orders", value: summary?.order_count ?? 0, icon: ShoppingCart, color: "text-blue-600" },
    { label: "Gross Profit", value: `$${(summary?.gross_profit ?? 0).toLocaleString()}`, icon: Package, color: "text-purple-600" },
    { label: "Margin", value: `${summary?.margin_pct ?? 0}%`, icon: TrendingUp, color: "text-orange-600" },
  ];

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Dashboard</h1>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {stats.map((s) => (
          <div key={s.label} className="card p-5">
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs text-gray-500 font-medium">{s.label}</span>
              <s.icon className={`w-4 h-4 ${s.color}`} />
            </div>
            <div className="text-2xl font-bold text-gray-900">{s.value}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        {/* Revenue by Marketplace */}
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Revenue by Marketplace</h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={byMarket || []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="marketplace" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip formatter={(v: number) => `$${v.toLocaleString()}`} />
              <Bar dataKey="revenue" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Low Stock Alerts */}
        <div className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle className="w-4 h-4 text-yellow-500" />
            <h2 className="text-sm font-semibold text-gray-700">Low Stock Alerts</h2>
          </div>
          {!alerts?.length ? (
            <p className="text-sm text-gray-400">No low stock items.</p>
          ) : (
            <div className="space-y-2 max-h-52 overflow-y-auto">
              {alerts.map((a: any) => (
                <div key={`${a.product_id}-${a.supplier_id}`} className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0">
                  <div>
                    <div className="text-sm font-medium">{a.product_name}</div>
                    <div className="text-xs text-gray-500">{a.supplier_name} · {a.sku}</div>
                  </div>
                  <span className={`badge ${a.stock === 0 ? "badge-red" : "badge-yellow"}`}>
                    {a.stock} left
                  </span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
