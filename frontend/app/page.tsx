"use client";
import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { reportsApi, ordersApi } from "@/lib/api";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { TrendingUp, ShoppingCart, Package, AlertTriangle, Copy, Check } from "lucide-react";
import Link from "next/link";

// ─── Date range helpers ────────────────────────────────────────────────────────

type Period =
  | "today" | "yesterday" | "last3days"
  | "thisweek" | "last7days"
  | "thismonth" | "last30days"
  | "custom";

function startOfDay(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0, 0, 0, 0);
}

function computeDateRange(
  period: Period,
  customFrom: string,
  customTo: string,
): { from: Date; to: Date } {
  const now = new Date();
  const today = startOfDay(now);

  switch (period) {
    case "today":
      return { from: today, to: now };
    case "yesterday": {
      const y = new Date(today); y.setDate(y.getDate() - 1);
      const ye = new Date(today); ye.setMilliseconds(-1);
      return { from: y, to: ye };
    }
    case "last3days": {
      const f = new Date(today); f.setDate(f.getDate() - 2);
      return { from: f, to: now };
    }
    case "thisweek": {
      const f = new Date(today);
      f.setDate(f.getDate() - ((f.getDay() + 6) % 7)); // Monday
      return { from: f, to: now };
    }
    case "last7days": {
      const f = new Date(today); f.setDate(f.getDate() - 6);
      return { from: f, to: now };
    }
    case "thismonth": {
      const f = new Date(today.getFullYear(), today.getMonth(), 1);
      return { from: f, to: now };
    }
    case "last30days": {
      const f = new Date(today); f.setDate(f.getDate() - 29);
      return { from: f, to: now };
    }
    case "custom": {
      const f = customFrom ? new Date(customFrom + "T00:00:00") : today;
      const t = customTo ? new Date(customTo + "T23:59:59") : now;
      return { from: f, to: t };
    }
  }
}

function prevRange(period: Period, cur: { from: Date; to: Date }): { from: Date; to: Date } {
  const durationMs = cur.to.getTime() - cur.from.getTime();
  if (period === "yesterday") {
    const f = new Date(cur.from); f.setDate(f.getDate() - 1);
    const t = new Date(cur.to); t.setDate(t.getDate() - 1);
    return { from: f, to: t };
  }
  if (period === "thisweek" || period === "thismonth") {
    // previous equivalent: same duration ending at start of current
    const t = new Date(cur.from); t.setMilliseconds(-1);
    const f = new Date(t.getTime() - durationMs);
    return { from: f, to: t };
  }
  // default: shift back by same duration
  return {
    from: new Date(cur.from.getTime() - durationMs),
    to: new Date(cur.to.getTime() - durationMs),
  };
}

function toISO(d: Date) { return d.toISOString(); }

function pctChange(cur: number, prev: number) {
  if (!prev) return null;
  return ((cur - prev) / prev) * 100;
}

function fmtPct(p: number | null) {
  if (p === null) return null;
  const sign = p >= 0 ? "+" : "";
  return `${sign}${p.toFixed(1)}%`;
}

// ─── Period label for copy text ────────────────────────────────────────────────
function periodLabel(period: Period, from: Date): string {
  if (period === "today" || period === "yesterday") {
    return from.toLocaleDateString("en-US", { month: "short", day: "numeric" }).toUpperCase();
  }
  return from.toLocaleDateString("en-US", { month: "short", day: "numeric" }).toUpperCase();
}

// ─── Main Dashboard ────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [period, setPeriod] = useState<Period>("today");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");

  const { from, to } = useMemo(
    () => computeDateRange(period, customFrom, customTo),
    [period, customFrom, customTo],
  );
  const { from: prevFrom, to: prevTo } = useMemo(
    () => prevRange(period, { from, to }),
    [period, from, to],
  );

  const fromISO = toISO(from);
  const toISO_ = toISO(to);
  const prevFromISO = toISO(prevFrom);
  const prevToISO = toISO(prevTo);

  const { data: summary } = useQuery({
    queryKey: ["summary", fromISO, toISO_],
    queryFn: () => reportsApi.summary({ from_date: fromISO, to_date: toISO_ }),
  });
  const { data: prevSummary } = useQuery({
    queryKey: ["summary", prevFromISO, prevToISO],
    queryFn: () => reportsApi.summary({ from_date: prevFromISO, to_date: prevToISO }),
  });

  const { data: byMarket } = useQuery({
    queryKey: ["by-marketplace"],
    queryFn: reportsApi.byMarketplace,
  });
  const { data: bySupplier } = useQuery({
    queryKey: ["by-supplier"],
    queryFn: reportsApi.bySupplier,
  });
  const { data: alerts } = useQuery({
    queryKey: ["inventory-alert"],
    queryFn: () => reportsApi.inventoryAlert(5),
  });
  const { data: delayed = [] } = useQuery({
    queryKey: ["orders", "delayed"],
    queryFn: () => ordersApi.listDelayed(),
    refetchInterval: 5 * 60 * 1000,
  });

  const kpis = [
    {
      label: "Total Revenue",
      cur: summary?.total_revenue ?? 0,
      prev: prevSummary?.total_revenue ?? 0,
      fmt: (v: number) => `$${v.toLocaleString()}`,
      icon: TrendingUp,
      color: "text-green-600",
    },
    {
      label: "Orders",
      cur: summary?.order_count ?? 0,
      prev: prevSummary?.order_count ?? 0,
      fmt: (v: number) => v.toLocaleString(),
      icon: ShoppingCart,
      color: "text-blue-600",
    },
    {
      label: "Gross Profit",
      cur: summary?.gross_profit ?? 0,
      prev: prevSummary?.gross_profit ?? 0,
      fmt: (v: number) => `$${v.toLocaleString()}`,
      icon: Package,
      color: "text-purple-600",
    },
    {
      label: "Margin",
      cur: summary?.margin_pct ?? 0,
      prev: prevSummary?.margin_pct ?? 0,
      fmt: (v: number) => `${v}%`,
      icon: TrendingUp,
      color: "text-orange-600",
    },
  ];

  const prevLabel = period === "today" ? "yesterday"
    : period === "yesterday" ? "2 days ago"
    : period === "thisweek" ? "last week"
    : period === "thismonth" ? "last month"
    : "prev period";

  return (
    <div>
      {/* Header + filter */}
      <div className="page-header">
        <h1 className="page-title">Dashboard</h1>
        <PeriodSelector
          period={period}
          setPeriod={setPeriod}
          customFrom={customFrom}
          customTo={customTo}
          setCustomFrom={setCustomFrom}
          setCustomTo={setCustomTo}
        />
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {kpis.map((k) => {
          const pct = pctChange(k.cur, k.prev);
          const pctStr = fmtPct(pct);
          return (
            <div key={k.label} className="card p-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-gray-500 font-medium">{k.label}</span>
                <k.icon className={`w-4 h-4 ${k.color}`} />
              </div>
              <div className="text-2xl font-bold text-gray-900">{k.fmt(k.cur)}</div>
              {pctStr && (
                <div className={`text-xs mt-1 font-medium ${pct! >= 0 ? "text-green-600" : "text-red-500"}`}>
                  {pctStr} vs {prevLabel}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Row 2: Revenue chart + Delay Alert */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <div className="card p-5">
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Revenue by Marketplace <span className="text-xs font-normal text-gray-400">(all-time)</span></h2>
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

        <DelayAlertWidget delayed={delayed as any[]} />
      </div>

      {/* Row 3: By Supplier + Low Stock */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <BySupplierWidget bySupplier={bySupplier as any[] | undefined} />

        <div className="card p-5">
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle className="w-4 h-4 text-yellow-500" />
            <h2 className="text-sm font-semibold text-gray-700">Low Stock Alerts</h2>
          </div>
          {!alerts?.length ? (
            <p className="text-sm text-gray-400">No low stock items.</p>
          ) : (
            <div className="space-y-2 max-h-52 overflow-y-auto">
              {(alerts as any[]).map((a) => (
                <div key={`${a.product_id}-${a.supplier_id}`} className="flex items-center justify-between py-2 border-b border-gray-100 last:border-0">
                  <div>
                    <div className="text-sm font-medium">{a.display_name}</div>
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

      {/* Row 4: Order Summary */}
      <OrderSummaryWidget period={period} fromISO={fromISO} toISO={toISO_} from={from} />
    </div>
  );
}

// ─── Period Selector ───────────────────────────────────────────────────────────

function PeriodSelector({
  period, setPeriod, customFrom, customTo, setCustomFrom, setCustomTo,
}: {
  period: Period;
  setPeriod: (p: Period) => void;
  customFrom: string;
  customTo: string;
  setCustomFrom: (v: string) => void;
  setCustomTo: (v: string) => void;
}) {
  return (
    <div className="flex items-center gap-2">
      <select
        className="input w-44 text-sm"
        value={period}
        onChange={(e) => setPeriod(e.target.value as Period)}
      >
        <optgroup label="Daily">
          <option value="today">Today</option>
          <option value="yesterday">Yesterday</option>
          <option value="last3days">Last 3 days</option>
        </optgroup>
        <optgroup label="Weekly">
          <option value="thisweek">This week</option>
          <option value="last7days">Last 7 days</option>
        </optgroup>
        <optgroup label="Monthly">
          <option value="thismonth">This month</option>
          <option value="last30days">Last 30 days</option>
        </optgroup>
        <optgroup label="Custom">
          <option value="custom">Custom range…</option>
        </optgroup>
      </select>
      {period === "custom" && (
        <>
          <input
            type="date"
            className="input w-36 text-sm"
            value={customFrom}
            onChange={(e) => setCustomFrom(e.target.value)}
          />
          <span className="text-gray-400 text-sm">→</span>
          <input
            type="date"
            className="input w-36 text-sm"
            value={customTo}
            onChange={(e) => setCustomTo(e.target.value)}
          />
        </>
      )}
    </div>
  );
}

// ─── Delay Alert Widget ────────────────────────────────────────────────────────

function DelayAlertWidget({ delayed }: { delayed: any[] }) {
  const urgent = delayed.filter((o) => o.status === "urgent");
  const warning = delayed.filter((o) => o.status === "warning");
  const top3 = [...urgent].sort((a, b) => b.days_delayed - a.days_delayed).slice(0, 3);

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-gray-700">Delay Alerts</h2>
        <div className="flex gap-2">
          {urgent.length > 0 && (
            <span className="inline-flex items-center gap-1 text-xs font-bold px-2 py-0.5 rounded-full bg-red-100 text-red-700">
              <AlertTriangle className="w-3 h-3" />{urgent.length} URGENT
            </span>
          )}
          {warning.length > 0 && (
            <span className="inline-flex items-center gap-1 text-xs font-bold px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-700">
              <AlertTriangle className="w-3 h-3" />{warning.length} WARNING
            </span>
          )}
          {delayed.length === 0 && (
            <span className="text-xs text-green-600 font-medium">All on time</span>
          )}
        </div>
      </div>
      {top3.length === 0 ? (
        <p className="text-sm text-gray-400">No delayed orders.</p>
      ) : (
        <div className="space-y-2">
          {top3.map((o) => (
            <Link
              key={`${o.order_id}-${o.purchased_at}`}
              href={`/orders/${o.order_id}`}
              className="flex items-center justify-between py-2 px-3 rounded-lg bg-red-50 hover:bg-red-100 transition-colors"
            >
              <div>
                <span className="text-sm font-medium text-gray-800">#{o.order_id}</span>
                {o.order_name && o.order_name !== `#${o.order_id}` && (
                  <span className="ml-1 text-xs text-gray-500 font-mono">{o.order_name}</span>
                )}
                <div className="text-xs text-gray-500">{o.supplier_name}</div>
              </div>
              <div className="text-right">
                <div className="text-sm font-bold text-red-600">{o.days_delayed}d</div>
                <span className="text-xs font-semibold px-1.5 py-0.5 rounded-full bg-red-100 text-red-700">URGENT</span>
              </div>
            </Link>
          ))}
          {urgent.length > 3 && (
            <Link href="/orders" className="block text-xs text-center text-blue-500 hover:underline pt-1">
              +{urgent.length - 3} more urgent →
            </Link>
          )}
        </div>
      )}
    </div>
  );
}

// ─── By Supplier Widget ────────────────────────────────────────────────────────

function BySupplierWidget({ bySupplier }: { bySupplier: any[] | undefined }) {
  const sorted = useMemo(
    () => [...(bySupplier || [])].sort((a, b) => b.line_item_count - a.line_item_count).slice(0, 8),
    [bySupplier],
  );
  const max = sorted[0]?.line_item_count || 1;

  return (
    <div className="card p-5">
      <h2 className="text-sm font-semibold text-gray-700 mb-4">Orders by Supplier <span className="text-xs font-normal text-gray-400">(all-time)</span></h2>
      {!sorted.length ? (
        <p className="text-sm text-gray-400">No data.</p>
      ) : (
        <div className="space-y-2.5">
          {sorted.map((s) => (
            <div key={s.supplier_id} className="flex items-center gap-3">
              <div className="w-28 text-xs text-gray-600 truncate shrink-0">{s.supplier_name}</div>
              <div className="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
                <div
                  className="bg-blue-500 h-2 rounded-full transition-all"
                  style={{ width: `${(s.line_item_count / max) * 100}%` }}
                />
              </div>
              <div className="text-xs text-gray-500 w-10 text-right shrink-0">{s.line_item_count}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Order Summary Widget ──────────────────────────────────────────────────────

const LS_BALANCE_KEY = "ending_balance_yesterday";

function OrderSummaryWidget({
  period, fromISO, toISO, from,
}: {
  period: Period;
  fromISO: string;
  toISO: string;
  from: Date;
}) {
  const isToday = period === "today";

  // Starting balance: auto-load from localStorage when period=today
  const savedBalance = typeof window !== "undefined"
    ? localStorage.getItem(LS_BALANCE_KEY) ?? ""
    : "";
  const [startingBalance, setStartingBalance] = useState<string>(
    isToday ? savedBalance : "",
  );
  const [copied, setCopied] = useState(false);

  // When period changes, reset or restore balance
  const [lastPeriod, setLastPeriod] = useState<Period>(period);
  if (period !== lastPeriod) {
    setLastPeriod(period);
    if (period === "today") {
      setStartingBalance(
        typeof window !== "undefined" ? localStorage.getItem(LS_BALANCE_KEY) ?? "" : "",
      );
    } else {
      setStartingBalance("");
    }
  }

  const { data: orders = [] } = useQuery({
    queryKey: ["orders-summary", fromISO, toISO],
    queryFn: () => ordersApi.list({ from_date: fromISO, to_date: toISO }),
  });

  // Group line items by product_name
  const groups = useMemo(() => {
    const map = new Map<string, { qty: number; cost: number }>();
    for (const order of orders as any[]) {
      for (const li of (order.line_items ?? [])) {
        const getRawName = (li: any) => {
          const raw = li.catalog_name
            || li.mapping_suggestion?.catalog_name
            || li.product_name
            || "Unknown"
          const cleaned = raw.replace(/^\([^)]*\)\s*/g, "").trim()
          return cleaned.split(/[,|]/)[0].trim() || "Unknown"
        }
        const name = getRawName(li);
        const prev = map.get(name) ?? { qty: 0, cost: 0 };
        map.set(name, {
          qty: prev.qty + (Number(li.quantity) || 0),
          cost: prev.cost + (Number(li.base_cost ?? 0) || 0) * (Number(li.quantity) || 0),
        });
      }
    }
    return [...map.entries()]
      .map(([name, v]) => ({ name, qty: v.qty, cost: v.cost }))
      .sort((a, b) => b.cost - a.cost);
  }, [orders]);

  const orderCount = (orders as any[]).length;
  const total = groups.reduce((s, g) => s + g.cost, 0);
  const startNum = parseFloat(startingBalance.replace(/[^0-9.]/g, "")) || 0;
  const ending = startNum - total;

  const dateLabel = periodLabel(period, from);

  const handleCopy = () => {
    const lines = [
      `${dateLabel} – ${orderCount} ORDER${orderCount !== 1 ? "S" : ""}`,
      `Starting balance: $${startNum.toLocaleString()}`,
      ...groups.map((g) => `• ${g.qty} ${g.name} => $${g.cost.toFixed(0)}`),
      `TOTAL: $${total.toFixed(0)}`,
      `Ending balance: $${ending.toLocaleString()}`,
    ];
    navigator.clipboard.writeText(lines.join("\n"));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);

    // Save ending balance for tomorrow (only when period=today)
    if (isToday && typeof window !== "undefined") {
      localStorage.setItem(LS_BALANCE_KEY, ending.toFixed(2));
    }
  };

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-gray-700">
          Order Summary
          <span className="ml-2 text-xs font-normal text-gray-400">{dateLabel} · {orderCount} orders</span>
        </h2>
        <button
          className="flex items-center gap-1.5 btn-secondary text-xs py-1 px-2"
          onClick={handleCopy}
          disabled={orderCount === 0}
        >
          {copied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
          {copied ? "Copied!" : "Copy text"}
        </button>
      </div>

      {/* Starting balance input */}
      <div className="flex items-center gap-3 mb-4 pb-4 border-b border-gray-100">
        <label className="text-xs text-gray-500 w-32 shrink-0">
          Starting balance
          {isToday && savedBalance && (
            <span className="block text-[10px] text-blue-500">auto from yesterday</span>
          )}
        </label>
        <div className="relative">
          <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
          <input
            type="number"
            className="input pl-6 w-32 text-sm"
            placeholder="0.00"
            value={startingBalance}
            onChange={(e) => setStartingBalance(e.target.value)}
          />
        </div>
      </div>

      {/* Product groups */}
      {groups.length === 0 ? (
        <p className="text-sm text-gray-400">No orders in this period.</p>
      ) : (
        <div className="space-y-1.5 mb-4 max-h-48 overflow-y-auto">
          {groups.map((g) => (
            <div key={g.name} className="flex items-center justify-between text-sm">
              <span className="text-gray-700">
                <span className="font-semibold">{g.qty}</span> {g.name}
              </span>
              <span className="font-medium text-gray-800">${g.cost.toFixed(0)}</span>
            </div>
          ))}
        </div>
      )}

      {/* Totals */}
      <div className="border-t border-gray-100 pt-3 space-y-1.5">
        <div className="flex justify-between text-sm font-semibold">
          <span>TOTAL</span>
          <span>${total.toFixed(0)}</span>
        </div>
        {startNum > 0 && (
          <div className={`flex justify-between text-sm font-bold ${ending >= 0 ? "text-green-700" : "text-red-600"}`}>
            <span>Ending balance</span>
            <span>${ending.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}</span>
          </div>
        )}
      </div>
    </div>
  );
}
