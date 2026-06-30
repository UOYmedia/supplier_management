"use client";
import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { reportsApi, ordersApi, marketplaceApi } from "@/lib/api";
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from "recharts";
import { TrendingUp, ShoppingCart, Package, AlertTriangle, Copy, Check, ChevronRight } from "lucide-react";
import Link from "next/link";
import DrillDownDrawer from "@/components/DrillDownDrawer";

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
  const [openDrawer, setOpenDrawer] = useState<string | null>(null);
  const [scSupplier, setScSupplier] = useState<{ id: number; name: string } | null>(null);
  const [mkt, setMkt] = useState<string | null>(null);

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
    <div className="h-[calc(100vh-2.5rem)] flex flex-col">
      {/* Header + filter (fixed) */}
      <div className="page-header shrink-0">
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

      {/* Scrollable content */}
      <div className="flex-1 min-h-0 overflow-y-auto -mx-1 px-1">
      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {kpis.map((k) => {
          const pct = pctChange(k.cur, k.prev);
          const pctStr = fmtPct(pct);
          const drawerKey =
            k.label === "Gross Profit" || k.label === "Margin" ? "margin"
            : k.label === "Total Revenue" ? "revenue"
            : k.label === "Orders" ? "orders"
            : null;
          return (
            <div
              key={k.label}
              onClick={drawerKey ? () => setOpenDrawer(drawerKey) : undefined}
              className={`card p-5 ${drawerKey ? "cursor-pointer hover:shadow-md transition-shadow" : ""}`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-gray-500 font-medium flex items-center gap-1">
                  {k.label}
                  {drawerKey && <ChevronRight className="w-3 h-3 text-blue-400" />}
                </span>
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
          <h2 className="text-sm font-semibold text-gray-700 mb-4">Revenue by Marketplace <span className="text-xs font-normal text-gray-400">(all-time · click a bar)</span></h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={byMarket || []}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="marketplace" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <Tooltip formatter={(v: number) => `$${v.toLocaleString()}`} />
              <Bar
                dataKey="revenue"
                fill="#3b82f6"
                radius={[4, 4, 0, 0]}
                style={{ cursor: "pointer" }}
                onClick={(d: any) => { if (d?.marketplace) { setMkt(d.marketplace); setOpenDrawer("marketplace"); } }}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <DelayAlertWidget delayed={delayed as any[]} onOpen={() => setOpenDrawer("delays")} />
      </div>

      {/* Row 3: By Supplier + Low Stock */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <BySupplierWidget
          bySupplier={bySupplier as any[] | undefined}
          onSelect={(s) => { setScSupplier({ id: s.supplier_id, name: s.supplier_name }); setOpenDrawer("supplier"); }}
        />

        <div
          className="card p-5 cursor-pointer hover:shadow-md transition-shadow"
          onClick={() => setOpenDrawer("lowstock")}
          title="Click for reorder detail"
        >
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 text-yellow-500" />
              <h2 className="text-sm font-semibold text-gray-700">Low Stock Alerts</h2>
            </div>
            <span className="flex items-center text-xs text-blue-500">
              Reorder view <ChevronRight className="w-3 h-3" />
            </span>
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

      {/* Drill-down: Low Stock & Reorder */}
      <DrillDownDrawer
        open={openDrawer === "lowstock"}
        onClose={() => setOpenDrawer(null)}
        title="Low Stock & Reorder"
        subtitle="Stock vs pending demand · sales velocity · projected days of cover"
        footer={
          <Link href="/suppliers" className="text-sm text-blue-600 hover:underline">
            Open Suppliers to update stock / reorder →
          </Link>
        }
      >
        <StockInsightsContent />
      </DrillDownDrawer>

      {/* Drill-down: Supplier scorecard */}
      <DrillDownDrawer
        open={openDrawer === "supplier" && !!scSupplier}
        onClose={() => setOpenDrawer(null)}
        title={scSupplier ? `Supplier · ${scSupplier.name}` : "Supplier"}
        subtitle="Last 30 days · spend, fulfilment, speed, stock"
        footer={
          scSupplier && (
            <Link href={`/suppliers/${scSupplier.id}`} className="text-sm text-blue-600 hover:underline">
              Open supplier page →
            </Link>
          )
        }
      >
        {scSupplier && <SupplierScorecardContent supplierId={scSupplier.id} />}
      </DrillDownDrawer>

      {/* Drill-down: Delays by supplier */}
      <DrillDownDrawer
        open={openDrawer === "delays"}
        onClose={() => setOpenDrawer(null)}
        title="Delayed orders by supplier"
        subtitle="Who to chase first — grouped by supplier, most urgent on top"
        footer={
          <Link href="/orders" className="text-sm text-blue-600 hover:underline">
            Open Orders →
          </Link>
        }
      >
        <DelayBySupplierContent delayed={delayed as any[]} />
      </DrillDownDrawer>

      {/* Drill-down: Margin / profit accuracy */}
      <DrillDownDrawer
        open={openDrawer === "margin"}
        onClose={() => setOpenDrawer(null)}
        title="Gross Profit & Margin"
        subtitle="Profit for the selected period · cost coverage flag"
        footer={
          <Link href="/products" className="text-sm text-blue-600 hover:underline">
            Open Products to map / set cost →
          </Link>
        }
      >
        <MarginBreakdownContent fromISO={fromISO} toISO={toISO_} />
      </DrillDownDrawer>

      {/* Drill-down: Revenue */}
      <DrillDownDrawer
        open={openDrawer === "revenue"}
        onClose={() => setOpenDrawer(null)}
        title="Revenue"
        subtitle="Daily trend · AOV · marketplace split (selected period)"
      >
        <RevenueDrawerContent fromISO={fromISO} toISO={toISO_} />
      </DrillDownDrawer>

      {/* Drill-down: Orders */}
      <DrillDownDrawer
        open={openDrawer === "orders"}
        onClose={() => setOpenDrawer(null)}
        title="Orders"
        subtitle="Daily trend · status breakdown (selected period)"
      >
        <OrdersDrawerContent fromISO={fromISO} toISO={toISO_} />
      </DrillDownDrawer>

      {/* Drill-down: Marketplace */}
      <DrillDownDrawer
        open={openDrawer === "marketplace" && !!mkt}
        onClose={() => setOpenDrawer(null)}
        title={mkt ? `Marketplace · ${mkt}` : "Marketplace"}
        subtitle="Period performance · all-time · connection sync"
      >
        {mkt && <MarketplaceDrawerContent marketplace={mkt} fromISO={fromISO} toISO={toISO_} byMarket={byMarket as any[] | undefined} />}
      </DrillDownDrawer>
    </div>
  );
}

// ─── Stock Insights (Low Stock drill-down) ──────────────────────────────────────

function StockStat({ label, value, tone = "" }: { label: string; value: any; tone?: string }) {
  return (
    <div>
      <div className={`text-sm font-bold ${tone || "text-gray-800"}`}>{value}</div>
      <div className="text-[10px] text-gray-400 uppercase tracking-wide">{label}</div>
    </div>
  );
}

function StockInsightsContent() {
  const { data, isLoading } = useQuery({
    queryKey: ["stock-insights"],
    queryFn: () => reportsApi.stockInsights({ days: 30, threshold: 5, target_days: 14 }),
  });
  const items: any[] = data?.items ?? [];
  const outOfStock = items.filter((i) => i.available <= 0).length;
  const urgent = items.filter((i) => i.days_of_cover != null && i.days_of_cover <= 7).length;

  if (isLoading) return <p className="text-sm text-gray-400">Loading…</p>;
  if (!items.length)
    return <p className="text-sm text-gray-400">No items at risk — stock looks healthy. 🎉</p>;

  return (
    <div>
      <div className="flex gap-2 mb-4 flex-wrap items-center">
        <span className="badge badge-red">{outOfStock} out / oversold</span>
        <span className="badge badge-yellow">{urgent} running out ≤7d</span>
        <span className="text-xs text-gray-400">
          window {data.days}d · target {data.target_days}d cover
        </span>
      </div>
      <div className="space-y-2">
        {items.map((it) => {
          const dc = it.days_of_cover;
          const tone =
            it.available <= 0
              ? "border-red-200 bg-red-50"
              : dc != null && dc <= 7
              ? "border-amber-200 bg-amber-50"
              : "border-gray-100";
          return (
            <div key={it.supplier_product_id} className={`border rounded-lg p-3 ${tone}`}>
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-sm font-medium text-gray-800 truncate">{it.name}</div>
                  <div className="text-xs text-gray-500 font-mono truncate">
                    {it.supplier_name} · {it.sku}
                  </div>
                </div>
                {it.suggested_reorder > 0 && (
                  <span className="shrink-0 text-xs font-semibold px-2 py-0.5 rounded-full bg-blue-100 text-blue-700">
                    reorder {it.suggested_reorder}
                  </span>
                )}
              </div>
              <div className="grid grid-cols-4 gap-2 mt-2 text-center">
                <StockStat label="Stock" value={it.stock} />
                <StockStat label="Pending" value={it.pending} />
                <StockStat
                  label="Available"
                  value={it.available}
                  tone={it.available < 0 ? "text-red-600" : ""}
                />
                <StockStat
                  label="Days left"
                  value={dc == null ? "∞" : dc}
                  tone={dc != null && dc <= 7 ? "text-amber-600" : ""}
                />
              </div>
              <div className="text-[11px] text-gray-400 mt-1.5">
                Sold {it.sold_window} in {data.days}d · {it.velocity_per_day}/day
              </div>
            </div>
          );
        })}
      </div>
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

function DelayAlertWidget({ delayed, onOpen }: { delayed: any[]; onOpen: () => void }) {
  const urgent = delayed.filter((o) => o.status === "urgent");
  const warning = delayed.filter((o) => o.status === "warning");
  const top3 = [...urgent].sort((a, b) => b.days_delayed - a.days_delayed).slice(0, 3);

  return (
    <div className="card p-5">
      <div className="flex items-center justify-between mb-4">
        <button onClick={onOpen} className="flex items-center text-sm font-semibold text-gray-700 hover:text-blue-600">
          Delay Alerts <ChevronRight className="w-3.5 h-3.5 text-blue-500" />
        </button>
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

function BySupplierWidget({ bySupplier, onSelect }: { bySupplier: any[] | undefined; onSelect: (s: any) => void }) {
  const sorted = useMemo(
    () => [...(bySupplier || [])].sort((a, b) => b.line_item_count - a.line_item_count).slice(0, 8),
    [bySupplier],
  );
  const max = sorted[0]?.line_item_count || 1;

  return (
    <div className="card p-5">
      <h2 className="text-sm font-semibold text-gray-700 mb-4">Orders by Supplier <span className="text-xs font-normal text-gray-400">(all-time · click for scorecard)</span></h2>
      {!sorted.length ? (
        <p className="text-sm text-gray-400">No data.</p>
      ) : (
        <div className="space-y-1">
          {sorted.map((s) => (
            <button
              key={s.supplier_id}
              onClick={() => onSelect(s)}
              className="w-full flex items-center gap-3 py-1.5 px-1 rounded-lg hover:bg-gray-50 transition-colors text-left"
            >
              <div className="w-28 text-xs text-gray-600 truncate shrink-0">{s.supplier_name}</div>
              <div className="flex-1 bg-gray-100 rounded-full h-2 overflow-hidden">
                <div
                  className="bg-blue-500 h-2 rounded-full transition-all"
                  style={{ width: `${(s.line_item_count / max) * 100}%` }}
                />
              </div>
              <div className="text-xs text-gray-500 w-10 text-right shrink-0">{s.line_item_count}</div>
              <ChevronRight className="w-3 h-3 text-gray-300 shrink-0" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Order Summary Widget ──────────────────────────────────────────────────────

const LS_BALANCE_KEY = "ending_balance_yesterday";

function getRawName(li: any): string {
  const raw = li.catalog_name
    || li.mapping_suggestion?.catalog_name
    || li.product_name
    || "Unknown"
  const cleaned = raw.replace(/\s*\([^)]*\)/g, "").trim()
  return cleaned.split(/[,|]/)[0].trim() || "Unknown"
}

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

// ─── Supplier Scorecard (drill-down) ────────────────────────────────────────────

function SupplierScorecardContent({ supplierId }: { supplierId: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ["supplier-scorecard", supplierId],
    queryFn: () => reportsApi.supplierScorecard(supplierId, 30),
  });
  if (isLoading || !data) return <p className="text-sm text-gray-400">Loading…</p>;

  const kpis = [
    { label: "Orders", value: data.order_count },
    { label: "Units", value: data.units },
    { label: "Spend (COGS)", value: `$${Number(data.total_cogs).toLocaleString()}` },
    { label: "Fulfilment", value: `${data.fulfillment_rate}%` },
    { label: "Avg ship", value: data.avg_days_to_ship == null ? "—" : `${data.avg_days_to_ship}d` },
    { label: "Open items", value: data.open_count },
    { label: "Low stock", value: data.low_stock_count },
  ];

  return (
    <div>
      <div className="grid grid-cols-3 gap-3 mb-5">
        {kpis.map((k) => (
          <div key={k.label} className="rounded-lg border border-gray-100 p-3">
            <div className="text-base font-bold text-gray-800">{k.value}</div>
            <div className="text-[10px] text-gray-400 uppercase tracking-wide">{k.label}</div>
          </div>
        ))}
      </div>
      <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Top products (30d)</h3>
      {!data.top_products?.length ? (
        <p className="text-sm text-gray-400">No orders in this window.</p>
      ) : (
        <div className="space-y-1.5">
          {data.top_products.map((p: any) => (
            <div key={p.name} className="flex items-center justify-between text-sm">
              <span className="text-gray-700 truncate pr-2">
                <span className="font-semibold">{p.qty}</span> {p.name}
              </span>
              <span className="text-gray-500 shrink-0">${Number(p.cogs).toFixed(0)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── Delays by Supplier (drill-down) ────────────────────────────────────────────

function DelayBySupplierContent({ delayed }: { delayed: any[] }) {
  const groups = useMemo(() => {
    const map = new Map<string, { supplier: string; orders: any[]; urgent: number; warning: number }>();
    for (const o of delayed) {
      const key = o.supplier_name || "—";
      const g = map.get(key) ?? { supplier: key, orders: [] as any[], urgent: 0, warning: 0 };
      g.orders.push(o);
      if (o.status === "urgent") g.urgent++;
      else if (o.status === "warning") g.warning++;
      map.set(key, g);
    }
    return [...map.values()]
      .map((g) => ({
        ...g,
        maxDays: Math.max(...g.orders.map((o) => o.days_delayed || 0)),
        avgDays: g.orders.reduce((s, o) => s + (o.days_delayed || 0), 0) / g.orders.length,
      }))
      .sort((a, b) => b.urgent - a.urgent || b.maxDays - a.maxDays);
  }, [delayed]);

  if (!delayed.length) return <p className="text-sm text-gray-400">No delayed orders. 🎉</p>;

  return (
    <div className="space-y-4">
      {groups.map((g) => (
        <div key={g.supplier}>
          <div className="flex items-center justify-between mb-1.5">
            <div className="text-sm font-semibold text-gray-800">{g.supplier}</div>
            <div className="flex items-center gap-1.5 text-xs">
              {g.urgent > 0 && <span className="badge badge-red">{g.urgent} urgent</span>}
              {g.warning > 0 && <span className="badge badge-yellow">{g.warning} warning</span>}
              <span className="text-gray-400">avg {g.avgDays.toFixed(1)}d · max {g.maxDays}d</span>
            </div>
          </div>
          <div className="space-y-1">
            {[...g.orders].sort((a, b) => b.days_delayed - a.days_delayed).slice(0, 5).map((o) => (
              <Link
                key={`${o.order_id}-${o.purchased_at}`}
                href={`/orders/${o.order_id}`}
                className="flex items-center justify-between py-1.5 px-2 rounded-lg hover:bg-gray-50 text-sm"
              >
                <span className="text-gray-700">
                  #{o.order_id}
                  {o.order_name && o.order_name !== `#${o.order_id}` && (
                    <span className="ml-1 text-xs text-gray-400 font-mono">{o.order_name}</span>
                  )}
                </span>
                <span className={`font-bold ${o.status === "urgent" ? "text-red-600" : "text-yellow-600"}`}>
                  {o.days_delayed}d
                </span>
              </Link>
            ))}
            {g.orders.length > 5 && (
              <div className="text-[11px] text-gray-400 px-2">+{g.orders.length - 5} more</div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── Margin / Profit accuracy (drill-down) ──────────────────────────────────────

function MarginBreakdownContent({ fromISO, toISO }: { fromISO: string; toISO: string }) {
  const { data, isLoading } = useQuery({
    queryKey: ["margin-breakdown", fromISO, toISO],
    queryFn: () => reportsApi.marginBreakdown({ from_date: fromISO, to_date: toISO }),
  });
  if (isLoading || !data) return <p className="text-sm text-gray-400">Loading…</p>;

  const hasMissing = data.missing_cost_count > 0;

  return (
    <div>
      {/* Totals */}
      <div className="grid grid-cols-2 gap-3 mb-4">
        <div className="rounded-lg border border-gray-100 p-3">
          <div className="text-base font-bold text-gray-800">${Number(data.revenue).toLocaleString()}</div>
          <div className="text-[10px] text-gray-400 uppercase tracking-wide">Revenue</div>
        </div>
        <div className="rounded-lg border border-gray-100 p-3">
          <div className="text-base font-bold text-gray-800">${Number(data.cost).toLocaleString()}</div>
          <div className="text-[10px] text-gray-400 uppercase tracking-wide">COGS</div>
        </div>
        <div className="rounded-lg border border-gray-100 p-3">
          <div className={`text-base font-bold ${data.gross_profit >= 0 ? "text-green-700" : "text-red-600"}`}>
            ${Number(data.gross_profit).toLocaleString()}
          </div>
          <div className="text-[10px] text-gray-400 uppercase tracking-wide">Gross profit</div>
        </div>
        <div className="rounded-lg border border-gray-100 p-3">
          <div className="text-base font-bold text-gray-800">{data.margin_pct}%</div>
          <div className="text-[10px] text-gray-400 uppercase tracking-wide">Margin</div>
        </div>
      </div>

      {/* Cost coverage flag */}
      <div className={`rounded-lg border p-3 mb-4 ${hasMissing ? "border-amber-200 bg-amber-50" : "border-green-200 bg-green-50"}`}>
        {hasMissing ? (
          <>
            <div className="text-sm font-medium text-amber-800">
              ⚠️ Margin may be overstated
            </div>
            <div className="text-xs text-amber-700 mt-1">
              {data.missing_cost_count} of {data.line_items_total} line items ({data.missing_cost_units} units) have no
              recorded cost — counted as 100% profit. Cost coverage: {data.cost_coverage_pct}%.
            </div>
          </>
        ) : (
          <div className="text-sm font-medium text-green-700">✓ All line items have a recorded cost.</div>
        )}
      </div>

      {/* Products missing cost */}
      {hasMissing && data.top_missing?.length > 0 && (
        <div className="mb-4">
          <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Products missing cost</h3>
          <div className="space-y-1.5">
            {data.top_missing.map((p: any) => (
              <div key={p.name} className="flex items-center justify-between text-sm">
                <span className="text-gray-700 truncate pr-2">{p.name}</span>
                <span className="text-amber-600 shrink-0">{p.units} units</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Top COGS products */}
      {data.top_cost_products?.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Top COGS products</h3>
          <div className="space-y-1.5">
            {data.top_cost_products.map((p: any) => (
              <div key={p.name} className="flex items-center justify-between text-sm">
                <span className="text-gray-700 truncate pr-2">{p.name}</span>
                <span className="text-gray-500 shrink-0">${Number(p.cogs).toFixed(0)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Revenue / Orders / Marketplace (drill-downs) ───────────────────────────────

function MiniStat({ label, value, tone = "" }: { label: string; value: any; tone?: string }) {
  return (
    <div className="rounded-lg border border-gray-100 p-3">
      <div className={`text-base font-bold ${tone || "text-gray-800"}`}>{value}</div>
      <div className="text-[10px] text-gray-400 uppercase tracking-wide">{label}</div>
    </div>
  );
}

function useOrdersBreakdown(fromISO: string, toISO: string) {
  return useQuery({
    queryKey: ["orders-breakdown", fromISO, toISO],
    queryFn: () => reportsApi.ordersBreakdown({ from_date: fromISO, to_date: toISO }),
  });
}

function RevenueDrawerContent({ fromISO, toISO }: { fromISO: string; toISO: string }) {
  const { data, isLoading } = useOrdersBreakdown(fromISO, toISO);
  if (isLoading || !data) return <p className="text-sm text-gray-400">Loading…</p>;
  const daily: any[] = data.daily ?? [];
  return (
    <div>
      <div className="grid grid-cols-3 gap-3 mb-4">
        <MiniStat label="Revenue" value={`$${Number(data.revenue).toLocaleString()}`} />
        <MiniStat label="Orders" value={data.orders} />
        <MiniStat label="Avg order" value={`$${Number(data.aov).toLocaleString()}`} />
      </div>
      <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Daily revenue</h3>
      <ResponsiveContainer width="100%" height={180}>
        <LineChart data={daily}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d: string) => d.slice(5)} />
          <YAxis tick={{ fontSize: 11 }} />
          <Tooltip formatter={(v: number) => `$${v.toLocaleString()}`} />
          <Line type="monotone" dataKey="revenue" stroke="#22c55e" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
      <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2 mt-4">By marketplace</h3>
      <div className="space-y-1.5">
        {(data.by_marketplace ?? []).map((m: any) => (
          <div key={m.marketplace} className="flex items-center justify-between text-sm">
            <span className="text-gray-700">{m.marketplace}</span>
            <span className="text-gray-500">${Number(m.revenue).toLocaleString()} · {m.orders} orders</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function OrdersDrawerContent({ fromISO, toISO }: { fromISO: string; toISO: string }) {
  const { data, isLoading } = useOrdersBreakdown(fromISO, toISO);
  if (isLoading || !data) return <p className="text-sm text-gray-400">Loading…</p>;
  const daily: any[] = data.daily ?? [];
  const statuses = Object.entries(data.status_counts ?? {}) as [string, number][];
  return (
    <div>
      <div className="grid grid-cols-3 gap-3 mb-4">
        <MiniStat label="Orders" value={data.orders} />
        <MiniStat label="Units" value={data.units} />
        <MiniStat label="Avg order" value={`$${Number(data.aov).toLocaleString()}`} />
      </div>
      <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Daily orders</h3>
      <ResponsiveContainer width="100%" height={180}>
        <BarChart data={daily}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={(d: string) => d.slice(5)} />
          <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
          <Tooltip />
          <Bar dataKey="orders" fill="#3b82f6" radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
      <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2 mt-4">Status breakdown</h3>
      <div className="space-y-1.5">
        {statuses.length === 0 ? (
          <p className="text-sm text-gray-400">No orders.</p>
        ) : statuses.map(([s, c]) => (
          <div key={s} className="flex items-center justify-between text-sm">
            <span className="text-gray-700 capitalize">{s.replace(/_/g, " ")}</span>
            <span className="text-gray-500">{c}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function MarketplaceDrawerContent({
  marketplace, fromISO, toISO, byMarket,
}: {
  marketplace: string; fromISO: string; toISO: string; byMarket: any[] | undefined;
}) {
  const { data } = useOrdersBreakdown(fromISO, toISO);
  const { data: connections = [] } = useQuery({
    queryKey: ["connections"],
    queryFn: () => marketplaceApi.listConnections(),
  });
  const period = (data?.by_marketplace ?? []).find((m: any) => m.marketplace === marketplace);
  const allTime = (byMarket ?? []).find((m: any) => m.marketplace === marketplace);
  const conns = (connections as any[]).filter(
    (c) => String(c.marketplace).toLowerCase() === marketplace.toLowerCase(),
  );

  return (
    <div>
      <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Selected period</h3>
      <div className="grid grid-cols-2 gap-3 mb-4">
        <MiniStat label="Revenue" value={`$${Number(period?.revenue ?? 0).toLocaleString()}`} />
        <MiniStat label="Orders" value={period?.orders ?? 0} />
      </div>
      <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">All-time</h3>
      <div className="grid grid-cols-2 gap-3 mb-4">
        <MiniStat label="Revenue" value={`$${Number(allTime?.revenue ?? 0).toLocaleString()}`} />
        <MiniStat label="Orders" value={allTime?.order_count ?? 0} />
      </div>
      <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Connections</h3>
      {conns.length === 0 ? (
        <p className="text-sm text-gray-400">No connection configured.</p>
      ) : (
        <div className="space-y-2">
          {conns.map((c) => (
            <div key={c.id} className="border border-gray-100 rounded-lg p-3">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-800">{c.name}</span>
                <span className={`badge ${c.status === "active" ? "badge-green" : c.status === "error" ? "badge-red" : "badge-yellow"}`}>
                  {c.status}
                </span>
              </div>
              <div className="text-xs text-gray-500 mt-1">
                Last synced: {c.last_synced_at ? new Date(c.last_synced_at).toLocaleString() : "never"}
              </div>
              {c.error_message && <div className="text-xs text-red-600 mt-1 truncate">{c.error_message}</div>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
