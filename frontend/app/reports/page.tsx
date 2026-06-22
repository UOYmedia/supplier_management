"use client";
import { useState, useMemo, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { ordersApi, reportsApi } from "@/lib/api";
import toast from "react-hot-toast";
import { Copy, Check, ShoppingCart, TrendingDown, Wallet, DollarSign, PlusCircle } from "lucide-react";

const LS_BALANCE_KEY = "ending_balance_yesterday";

type Period = "today" | "yesterday" | "last7days" | "last30days" | "thismonth" | "custom";

const PERIOD_BUTTONS: { key: Period; label: string }[] = [
  { key: "today", label: "Today" },
  { key: "yesterday", label: "Yesterday" },
  { key: "last7days", label: "7 Days" },
  { key: "last30days", label: "30 Days" },
  { key: "thismonth", label: "This Month" },
  { key: "custom", label: "Custom" },
];

function startOfDay(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate(), 0, 0, 0, 0);
}

function computeDateRange(period: Period, customFrom: string, customTo: string): { from: Date; to: Date } {
  const now = new Date();
  const today = startOfDay(now);
  switch (period) {
    case "today": return { from: today, to: now };
    case "yesterday": {
      const y = new Date(today); y.setDate(y.getDate() - 1);
      const ye = new Date(today); ye.setMilliseconds(-1);
      return { from: y, to: ye };
    }
    case "last7days": {
      const f = new Date(today); f.setDate(f.getDate() - 6);
      return { from: f, to: now };
    }
    case "last30days": {
      const f = new Date(today); f.setDate(f.getDate() - 29);
      return { from: f, to: now };
    }
    case "thismonth": {
      const f = new Date(today.getFullYear(), today.getMonth(), 1);
      return { from: f, to: now };
    }
    case "custom": {
      const f = customFrom ? new Date(customFrom + "T00:00:00") : today;
      const t = customTo ? new Date(customTo + "T23:59:59") : now;
      return { from: f, to: t };
    }
  }
}

function fmtDateLabel(period: Period, from: Date, to: Date): string {
  const opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  const f = from.toLocaleDateString("en-US", opts).toUpperCase();
  if (period === "today" || period === "yesterday") return f;
  const t = to.toLocaleDateString("en-US", opts).toUpperCase();
  return `${f} – ${t}`;
}

function toISO(d: Date) { return d.toISOString(); }

const getRawName = (li: any): string => {
  const raw = li.catalog_name
    || li.mapping_suggestion?.catalog_name
    || li.product_name
    || "Unknown"
  const cleaned = raw.replace(/\s*\([^)]*\)/g, "").trim()
  return cleaned.split(/[,|]/)[0].trim() || "Unknown"
}

export default function ReportsPage() {
  const [period, setPeriod] = useState<Period>("today");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [startingBalance, setStartingBalance] = useState("");
  const [topUp, setTopUp] = useState("");
  const [extCogs, setExtCogs] = useState("");
  const [balanceAutoLoaded, setBalanceAutoLoaded] = useState(false);
  const [copied, setCopied] = useState(false);

  const { from, to } = useMemo(
    () => computeDateRange(period, customFrom, customTo),
    [period, customFrom, customTo],
  );
  const fromISO = toISO(from);
  const toISO_ = toISO(to);

  useEffect(() => {
    // Always load ending balance of the day before the period's start date
    const dayBefore = new Date(from);
    dayBefore.setDate(dayBefore.getDate() - 1);
    const prevDate = dayBefore.toISOString().split("T")[0];
    // Restore any manual top-up already recorded for this period's start date.
    const currentDate = from.toISOString().split("T")[0];
    reportsApi.getDailyBalance(currentDate).then((data: any) => {
      setTopUp(data?.top_up != null && Number(data.top_up) !== 0 ? String(data.top_up) : "");
      setExtCogs(data?.external_cogs != null && Number(data.external_cogs) !== 0 ? String(data.external_cogs) : "");
    });
    reportsApi.getDailyBalance(prevDate).then((data: any) => {
      if (data?.ending_balance != null) {
        setStartingBalance(String(data.ending_balance));
        setBalanceAutoLoaded(true);
      } else if (period === "today") {
        // Fallback to localStorage for today only
        const saved = typeof window !== "undefined" ? localStorage.getItem(LS_BALANCE_KEY) ?? "" : "";
        setStartingBalance(saved);
        setBalanceAutoLoaded(!!saved);
      } else {
        setStartingBalance("");
        setBalanceAutoLoaded(false);
      }
    });
  }, [period, fromISO]);

  const { data: orders = [], isLoading } = useQuery({
    queryKey: ["orders-report", fromISO, toISO_],
    queryFn: () => ordersApi.list({ from_date: fromISO, to_date: toISO_ }),
  });



  const groups = useMemo(() => {
    const map = new Map<string, {
      supplier: string;
      orderIds: Set<number>;
      qty: number;
      unitCost: number;
      total: number;
    }>();
    for (const order of orders as any[]) {
      for (const li of (order.line_items ?? [])) {
        const name = getRawName(li);
        const qty = Number(li.quantity) || 0;
        const unitCost = Number(li.base_cost ?? 0) || 0;
        const prev = map.get(name);
        if (prev) {
          prev.orderIds.add(order.id);
          prev.qty += qty;
          prev.total += unitCost * qty;
        } else {
          map.set(name, {
            supplier: li.supplier_name || "—",
            orderIds: new Set([order.id]),
            qty,
            unitCost,
            total: unitCost * qty,
          });
        }
      }
    }
    return [...map.entries()]
      .map(([name, v]) => ({
        name,
        supplier: v.supplier,
        orders: v.orderIds.size,
        qty: v.qty,
        unitCost: v.unitCost,
        total: v.total,
      }))
      .sort((a, b) => b.total - a.total);
  }, [orders]);

  const orderCount = (orders as any[]).length;
  const totalCOGS = groups.reduce((s, g) => s + g.total, 0);
  const startNum = parseFloat(startingBalance.replace(/[^0-9.]/g, "")) || 0;
  const topUpNum = parseFloat((topUp || "").replace(/[^0-9.]/g, "")) || 0;
  const extCogsNum = parseFloat((extCogs || "").replace(/[^0-9.]/g, "")) || 0;
  const ending = startNum + topUpNum - totalCOGS - extCogsNum;
  const dateLabel = fmtDateLabel(period, from, to);

  // Guardrail: products whose supplier cost is not recorded yet (base_cost 0) —
  // these contribute $0 to the auto COGS and are what the manual field covers.
  const uncountedGroups = groups.filter((g) => g.total === 0);
  const uncountedQty = uncountedGroups.reduce((s, g) => s + g.qty, 0);

  // Auto-save ending balance to server whenever it changes (debounced)
  useEffect(() => {
    if (!startingBalance.trim() || isLoading) return;
    const todayDate = from.toISOString().split("T")[0];
    const timer = setTimeout(() => {
      reportsApi.saveDailyBalance(todayDate, ending, topUpNum, extCogsNum);
    }, 1500);
    return () => clearTimeout(timer);
  }, [ending, startingBalance, topUpNum, extCogsNum, from, isLoading]);

  const handleCopy = () => {
    const lines = [
      `${dateLabel} – ${orderCount} ORDER${orderCount !== 1 ? "S" : ""}`,
      `Starting balance: $${startNum.toLocaleString()}`,
      ...(topUpNum ? [`Top-up: $${topUpNum.toLocaleString()}`] : []),
      ...groups.map((g) => `• ${g.orders} order${g.orders !== 1 ? "s" : ""} of ${g.qty} ${g.name} => $${g.total.toFixed(0)}`),
      `TOTAL: $${totalCOGS.toFixed(0)}`,
      ...(extCogsNum ? [`External COGS (Amazon): $${extCogsNum.toLocaleString()}`] : []),
      `Ending balance: $${ending.toLocaleString()}`,
    ];
    navigator.clipboard.writeText(lines.join("\n"));
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
    // Save today's ending balance to server so tomorrow auto-loads it
    if (startingBalance.trim()) {
      const todayDate = from.toISOString().split("T")[0];
      reportsApi.saveDailyBalance(todayDate, ending, topUpNum, extCogsNum);
      // Also keep localStorage as fallback
      if (typeof window !== "undefined") {
        localStorage.setItem(LS_BALANCE_KEY, ending.toFixed(2));
      }
    }
    toast.success("Copied to clipboard");
  };

  return (
    <div>
      {/* Header */}
      <div className="page-header">
        <div>
          <h1 className="page-title">Daily Reports</h1>
          <p className="text-sm text-gray-500 mt-0.5">COGS and balance summary by period</p>
        </div>
        <button
          className="flex items-center gap-1.5 btn-secondary text-sm"
          onClick={handleCopy}
          disabled={orderCount === 0}
        >
          {copied ? <Check className="w-4 h-4 text-green-500" /> : <Copy className="w-4 h-4" />}
          {copied ? "Copied!" : "Copy text"}
        </button>
      </div>

      {/* Period filter */}
      <div className="card mb-4 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          {PERIOD_BUTTONS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setPeriod(key)}
              className={`text-sm px-3 py-1.5 rounded-lg border transition-colors ${
                period === key
                  ? "bg-blue-500 text-white border-blue-500"
                  : "border-gray-200 text-gray-600 hover:border-blue-300"
              }`}
            >
              {label}
            </button>
          ))}
          {period === "custom" && (
            <div className="flex items-center gap-2 ml-1">
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
            </div>
          )}
        </div>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4 mb-4">
        <div className="card p-5">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-500 font-medium">Total Orders</span>
            <ShoppingCart className="w-4 h-4 text-blue-500" />
          </div>
          <div className="text-2xl font-bold text-gray-900">{orderCount}</div>
        </div>

        <div className="card p-5">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-500 font-medium">Total COGS</span>
            <TrendingDown className="w-4 h-4 text-red-500" />
          </div>
          <div className="text-2xl font-bold text-gray-900">${totalCOGS.toFixed(0)}</div>
        </div>

        <div className="card p-5">
          <div className="flex items-center justify-between mb-2">
            <div>
              <span className="text-xs text-gray-500 font-medium">Starting Balance</span>
              {balanceAutoLoaded && (
                <span className="block text-[10px] text-blue-500">auto from yesterday</span>
              )}
            </div>
            <Wallet className="w-4 h-4 text-gray-400" />
          </div>
          <div className="relative mt-1">
            <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
            <input
              type="number"
              className="input pl-6 w-full text-lg font-bold"
              placeholder="0"
              value={startingBalance}
              onChange={(e) => setStartingBalance(e.target.value)}
            />
          </div>
        </div>

        <div className="card p-5">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-500 font-medium">Top-up</span>
            <PlusCircle className="w-4 h-4 text-emerald-500" />
          </div>
          <div className="relative mt-1">
            <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
            <input
              type="number"
              className="input pl-6 w-full text-lg font-bold"
              placeholder="0"
              value={topUp}
              onChange={(e) => setTopUp(e.target.value)}
            />
          </div>
        </div>

        <div className="card p-5">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-gray-500 font-medium">Ending Balance</span>
            <DollarSign className="w-4 h-4 text-green-500" />
          </div>
          <div className={`text-2xl font-bold ${startingBalance.trim() ? (ending >= 0 ? "text-green-700" : "text-red-600") : "text-gray-300"}`}>
            {startingBalance.trim()
              ? `$${ending.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`
              : "—"}
          </div>
        </div>
      </div>

      {/* External / unmapped COGS guardrail + manual entry */}
      <div className="card mb-4 px-5 py-4">
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
          <div className="text-sm">
            <div className="font-medium text-gray-700">External / un-costed COGS (Amazon…)</div>
            <div className="text-xs text-gray-500 mt-0.5">
              Auto COGS: <span className="font-semibold text-gray-700">${totalCOGS.toFixed(0)}</span>
              {uncountedGroups.length > 0 ? (
                <span className="text-amber-600">
                  {"  ·  "}⚠️ {uncountedGroups.length} product{uncountedGroups.length !== 1 ? "s" : ""} with no recorded cost ({uncountedQty} unit{uncountedQty !== 1 ? "s" : ""}) — not counted in COGS
                </span>
              ) : (
                <span className="text-green-600">{"  ·  "}✓ all products have a recorded cost</span>
              )}
            </div>
          </div>
          <div className="shrink-0">
            <label className="block text-[11px] text-gray-500 mb-1">Cover cost for the un-costed orders above</label>
            <div className="relative w-44">
              <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
              <input
                type="number"
                className="input pl-6 w-full font-semibold"
                placeholder="0"
                value={extCogs}
                onChange={(e) => setExtCogs(e.target.value)}
              />
            </div>
          </div>
        </div>
        <p className="text-[11px] text-gray-400 mt-2">
          Only enter the cost of externally-fulfilled (Amazon) orders that have <strong>no</strong> recorded cost above, to avoid double-counting the auto COGS.
        </p>
      </div>

      {/* Balance summary row */}
      {startingBalance.trim() && (
        <div className="card mb-4 px-5 py-3 flex items-center gap-3 text-sm flex-wrap">
          <span className="font-medium text-gray-700">
            Starting <span className="text-blue-600 font-bold">${startNum.toLocaleString()}</span>
          </span>
          {topUpNum > 0 && (
            <>
              <span className="text-gray-400 font-medium">+</span>
              <span className="font-medium text-gray-700">
                Top-up <span className="text-emerald-600 font-bold">${topUpNum.toLocaleString()}</span>
              </span>
            </>
          )}
          <span className="text-gray-400 font-medium">−</span>
          <span className="font-medium text-gray-700">
            COGS <span className="text-red-500 font-bold">${totalCOGS.toFixed(0)}</span>
          </span>
          {extCogsNum > 0 && (
            <>
              <span className="text-gray-400 font-medium">−</span>
              <span className="font-medium text-gray-700">
                External COGS <span className="text-red-500 font-bold">${extCogsNum.toLocaleString()}</span>
              </span>
            </>
          )}
          <span className="text-gray-400 font-medium">=</span>
          <span className={`font-bold text-base ${ending >= 0 ? "text-green-700" : "text-red-600"}`}>
            Ending ${ending.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
          </span>
          {balanceAutoLoaded && (
            <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-blue-50 text-blue-500 border border-blue-100">
              auto from yesterday
            </span>
          )}
        </div>
      )}

      {/* Data table */}
      <div className="card table-wrapper mb-4">
        <table>
          <thead>
            <tr>
              <th>Product</th>
              <th>Supplier</th>
              <th className="text-center">Orders</th>
              <th className="text-center">Qty</th>
              <th className="text-right">COGS/unit</th>
              <th className="text-right">Total</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={6} className="text-center py-8 text-gray-400">Loading…</td></tr>
            ) : groups.length === 0 ? (
              <tr><td colSpan={6} className="text-center py-8 text-gray-400">No orders in this period.</td></tr>
            ) : groups.map((g) => (
              <tr key={g.name}>
                <td className="font-medium text-sm">{g.name}</td>
                <td className="text-sm text-gray-500">{g.supplier}</td>
                <td className="text-center text-sm">{g.orders}</td>
                <td className="text-center text-sm font-medium">{g.qty}</td>
                <td className="text-right text-sm text-gray-500">${g.unitCost.toFixed(2)}</td>
                <td className="text-right text-sm font-semibold">${g.total.toFixed(0)}</td>
              </tr>
            ))}
          </tbody>
          {groups.length > 0 && (
            <tfoot>
              <tr className="border-t-2 border-gray-200 bg-gray-50">
                <td colSpan={3} className="py-3 px-4 text-xs text-gray-500 font-medium">
                  {orderCount} ORDER{orderCount !== 1 ? "S" : ""} · {groups.length} product{groups.length !== 1 ? "s" : ""}
                </td>
                <td colSpan={3} className="py-3 px-4 text-right font-bold text-gray-900">
                  TOTAL ${totalCOGS.toFixed(0)}
                </td>
              </tr>
            </tfoot>
          )}
        </table>
      </div>

      {/* Ending balance display */}
      {startingBalance.trim() && (
        <div className={`card px-5 py-4 flex items-center justify-between ${
          ending >= 0 ? "border-green-200 bg-green-50" : "border-red-200 bg-red-50"
        }`}>
          <span className="text-sm font-medium text-gray-700">Ending Balance</span>
          <span className={`text-xl font-bold ${ending >= 0 ? "text-green-700" : "text-red-600"}`}>
            ${ending.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}
          </span>
        </div>
      )}
    </div>
  );
}
