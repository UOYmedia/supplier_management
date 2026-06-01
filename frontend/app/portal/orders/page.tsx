"use client";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";
import { Printer, ChevronDown, ChevronUp, Package, Truck, X, Tag, Loader2, AlertTriangle } from "lucide-react";

const SUPPLIER_STATUS_TABS = [
  { value: "pending_label", label: "Pending Label" },
  { value: "unfulfilled", label: "Unfulfilled" },
  { value: "fulfilled", label: "Fulfilled" },
  { value: "shipped", label: "Shipped" },
  { value: "", label: "All" },
];

const SUPPLIER_STATUS_COLORS: Record<string, string> = {
  pending_label: "badge-red",
  unfulfilled: "badge-yellow",
  fulfilled: "badge-blue",
  shipped: "badge-green",
};

const SUPPLIER_STATUS_LABELS: Record<string, string> = {
  pending_label: "Pending Label",
  unfulfilled: "Unfulfilled",
  fulfilled: "Fulfilled",
  shipped: "Shipped",
};

interface PortalItem {
  item_key: string;
  order_id: number;
  order_line_item_id: number;
  external_order_id: string | null;
  marketplace: string;
  ordered_at: string;
  buyer_name: string | null;
  shipping_address: any;
  product_name: string;
  sku: string | null;
  image_url: string | null;
  quantity: number;
  supplier_status: string;
  tracking_number: string | null;
  label_id: number | null;
  label_url: string | null;
  label_has_pdf: boolean;
  fulfilled_at: string | null;
}

export default function PortalOrdersPage() {
  const [items, setItems] = useState<PortalItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("unfulfilled");
  const [expandedOrder, setExpandedOrder] = useState<number | null>(null);
  const [canBuyLabels, setCanBuyLabels] = useState(false);
  const [buyingFor, setBuyingFor] = useState<number | null>(null);
  const [confirmReprintOrder, setConfirmReprintOrder] = useState<number | null>(null);

  const load = () => {
    const token = localStorage.getItem("supplier_token");
    const q = filter ? `?supplier_status=${filter}` : "";
    fetch(`/api/v1/portal/orders${q}`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then(setItems)
      .catch(() => toast.error("Failed to load orders"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { setLoading(true); load(); }, [filter]);

  useEffect(() => {
    const token = localStorage.getItem("supplier_token");
    if (!token) return;
    fetch("/api/v1/portal/me", { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setCanBuyLabels(!!d.can_buy_labels))
      .catch(() => {});
  }, []);

  const labelInfoForOrder = (orderItems: PortalItem[]) => {
    const withLabel = orderItems.find((i) => i.label_id);
    if (!withLabel) return null;
    const url = withLabel.label_has_pdf
      ? `/api/v1/orders/${withLabel.order_id}/labels/${withLabel.label_id}/download`
      : withLabel.label_url;
    return url ? { url, labelId: withLabel.label_id!, orderId: withLabel.order_id } : null;
  };

  const printLabel = (url: string, orderId: number, labelId: number) => {
    const win = window.open(url, "_blank");
    if (!win) { toast.error("Popup blocked — allow popups to print labels"); return; }
    try { win.focus(); setTimeout(() => { try { win.print(); } catch {} }, 800); } catch {}

    const token = localStorage.getItem("supplier_token");
    fetch(`/api/v1/portal/orders/${orderId}/labels/${labelId}/mark-printed`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => { if (r.ok) { toast.success("Label printed — order marked as Fulfilled"); load(); } })
      .catch(() => {});
  };

  const handlePrintClick = (orderId: number, orderItems: PortalItem[]) => {
    const info = labelInfoForOrder(orderItems);
    if (!info) return;
    const alreadyPrinted = orderItems.every(
      (i) => i.supplier_status === "fulfilled" || i.supplier_status === "shipped"
    );
    if (alreadyPrinted) {
      setConfirmReprintOrder(orderId);
    } else {
      printLabel(info.url, info.orderId, info.labelId);
    }
  };

  const addrText = (a: any) =>
    a ? [a.name, a.line1, a.line2, a.city, a.state, a.zip, a.country].filter(Boolean).join(", ") : "—";

  if (loading) return <div className="text-gray-400">Loading…</div>;

  const orderGroups = items.reduce((acc, item) => {
    if (!acc[item.order_id]) acc[item.order_id] = [];
    acc[item.order_id].push(item);
    return acc;
  }, {} as Record<number, PortalItem[]>);

  const orderIds = Object.keys(orderGroups).map(Number);

  const orderBadge = (orderItems: PortalItem[]) => {
    const statuses = orderItems.map((i) => i.supplier_status);
    if (statuses.every((s) => s === "shipped")) return { label: "Shipped", cls: "badge-green" };
    if (statuses.every((s) => s === "fulfilled" || s === "shipped")) return { label: "Fulfilled", cls: "badge-blue" };
    if (statuses.some((s) => s === "pending_label")) return { label: "Pending Label", cls: "badge-red" };
    return { label: "Unfulfilled", cls: "badge-yellow" };
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="page-title">Orders to Fulfill</h1>
        <div className="flex gap-2 flex-wrap">
          {SUPPLIER_STATUS_TABS.map((tab) => (
            <button key={tab.value} onClick={() => setFilter(tab.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${filter === tab.value ? "bg-blue-600 text-white" : "bg-white border border-gray-200 text-gray-600 hover:bg-gray-50"}`}>
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {orderIds.length === 0 ? (
        <div className="card p-12 text-center text-gray-400">No orders found.</div>
      ) : (
        <div className="space-y-3">
          {orderIds.map((orderId) => {
            const orderItems = orderGroups[orderId];
            const first = orderItems[0];
            const isExpanded = expandedOrder === orderId;
            const alreadyPrinted = orderItems.every(
              (i) => i.supplier_status === "fulfilled" || i.supplier_status === "shipped"
            );
            const labelInfo = labelInfoForOrder(orderItems);
            const badge = orderBadge(orderItems);

            return (
              <div key={orderId} className="card overflow-hidden">
                <div
                  className="p-4 flex items-center gap-4 cursor-pointer hover:bg-gray-50 transition-colors"
                  onClick={() => setExpandedOrder(isExpanded ? null : orderId)}
                >
                  <Package className="w-4 h-4 text-gray-400 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-sm">Order #{orderId}</span>
                      {first.external_order_id && (
                        <span className="text-xs text-gray-400 font-mono">{first.external_order_id}</span>
                      )}
                      <span className="text-xs text-gray-400 capitalize">{first.marketplace}</span>
                      <span className={`badge text-xs ${badge.cls}`}>{badge.label}</span>
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5">
                      {orderItems.length} item(s) · {first.buyer_name || "—"} · {new Date(first.ordered_at).toLocaleDateString()}
                    </div>
                  </div>

                  {labelInfo ? (
                    <button
                      onClick={(e) => { e.stopPropagation(); handlePrintClick(orderId, orderItems); }}
                      className={`text-xs py-1.5 shrink-0 flex items-center gap-1.5 ${alreadyPrinted ? "btn-secondary" : "btn-primary"}`}
                    >
                      <Printer className="w-3 h-3" />
                      {alreadyPrinted ? "Reprint Label" : "Print Label"}
                    </button>
                  ) : canBuyLabels && !alreadyPrinted ? (
                    <button
                      onClick={(e) => { e.stopPropagation(); setBuyingFor(orderId); }}
                      className="btn-secondary text-xs py-1.5 shrink-0 flex items-center gap-1.5"
                    >
                      <Truck className="w-3 h-3" /> Buy Label
                    </button>
                  ) : null}

                  <button className="p-1.5 hover:bg-gray-100 rounded text-gray-400 shrink-0">
                    {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  </button>
                </div>

                {isExpanded && (
                  <div className="border-t border-gray-100">
                    <div className="px-4 py-3 bg-gray-50 text-xs text-gray-600">
                      <span className="font-medium text-gray-500 uppercase mr-2">Ship to:</span>
                      {addrText(first.shipping_address)}
                    </div>
                    <div className="divide-y divide-gray-100">
                      {orderItems.map((item) => (
                        <div key={item.item_key} className="px-4 py-4 flex items-start gap-3">
                          {item.image_url ? (
                            <img
                              src={item.image_url}
                              alt={item.product_name}
                              className="w-16 h-16 rounded-lg object-cover shrink-0 border border-gray-200"
                            />
                          ) : (
                            <div className="w-16 h-16 rounded-lg bg-gray-100 flex items-center justify-center shrink-0 border border-gray-200">
                              <Package className="w-6 h-6 text-gray-300" />
                            </div>
                          )}
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-1 flex-wrap">
                              <span className="font-semibold text-sm">{item.product_name}</span>
                              <span className={`badge text-xs ${SUPPLIER_STATUS_COLORS[item.supplier_status] || "badge-gray"}`}>
                                {SUPPLIER_STATUS_LABELS[item.supplier_status] || item.supplier_status}
                              </span>
                            </div>
                            {item.sku && (
                              <div className="text-xs text-gray-500 font-mono mb-0.5">SKU: {item.sku}</div>
                            )}
                            <div className="text-xs text-gray-500 font-medium">Qty: {item.quantity}</div>
                            {item.tracking_number && (
                              <div className="text-xs text-gray-600 mt-0.5">
                                Tracking: <span className="font-mono">{item.tracking_number}</span>
                              </div>
                            )}
                            {item.supplier_status === "shipped" && item.fulfilled_at && (
                              <div className="text-xs text-green-600 mt-0.5">
                                Shipped {new Date(item.fulfilled_at).toLocaleString()}
                              </div>
                            )}
                            {item.supplier_status === "fulfilled" && item.fulfilled_at && (
                              <div className="text-xs text-blue-600 mt-0.5">
                                Label printed {new Date(item.fulfilled_at).toLocaleString()}
                              </div>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {buyingFor !== null && (
        <BuyLabelModal
          orderId={buyingFor}
          onClose={() => setBuyingFor(null)}
          onBought={() => { setBuyingFor(null); load(); }}
        />
      )}

      {confirmReprintOrder !== null && (() => {
        const orderItems = orderGroups[confirmReprintOrder];
        const info = labelInfoForOrder(orderItems);
        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
            <div className="card w-full max-w-sm p-6">
              <div className="flex items-start gap-3 mb-4">
                <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0 mt-0.5" />
                <div>
                  <h2 className="font-semibold">Reprint label?</h2>
                  <p className="text-sm text-gray-500 mt-1">
                    Order #{confirmReprintOrder} label has already been printed. Print again?
                  </p>
                </div>
              </div>
              <div className="flex justify-end gap-2">
                <button className="btn-secondary" onClick={() => setConfirmReprintOrder(null)}>Cancel</button>
                <button
                  className="btn-primary flex items-center gap-1.5"
                  onClick={() => {
                    setConfirmReprintOrder(null);
                    if (info) printLabel(info.url, info.orderId, info.labelId);
                  }}
                >
                  <Printer className="w-4 h-4" /> Print anyway
                </button>
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}

function BuyLabelModal({ orderId, onClose, onBought }: {
  orderId: number;
  onClose: () => void;
  onBought: () => void;
}) {
  const [parcel, setParcel] = useState({ weight: "", length: "", width: "", height: "" });
  const [step, setStep] = useState<"parcel" | "rates">("parcel");
  const [shipmentId, setShipmentId] = useState<string | null>(null);
  const [rates, setRates] = useState<any[]>([]);
  const [selectedRate, setSelectedRate] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [estimateInfo, setEstimateInfo] = useState<{ complete: boolean; missing: any[] } | null>(null);
  const [debug, setDebug] = useState<any | null>(null);
  const [showRawDebug, setShowRawDebug] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("supplier_token");
    if (!token) return;
    fetch(`/api/v1/portal/orders/${orderId}/parcel-estimate`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((est: any) => {
        if (!est) return;
        setParcel({
          weight: est.weight > 0 ? String(est.weight) : "",
          length: est.length > 0 ? String(est.length) : "",
          width: est.width > 0 ? String(est.width) : "",
          height: est.height > 0 ? String(est.height) : "",
        });
        setEstimateInfo({ complete: !!est.complete, missing: est.missing || [] });
      })
      .catch(() => {});
  }, [orderId]);

  const pf = (k: string) => (e: any) => setParcel((p) => ({ ...p, [k]: e.target.value }));
  const parcelValid = parcel.weight && parcel.length && parcel.width && parcel.height;

  const authFetch = (url: string, init: RequestInit = {}) => {
    const token = localStorage.getItem("supplier_token");
    return fetch(url, {
      ...init,
      headers: { ...(init.headers || {}), Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
    });
  };

  const getRates = async () => {
    setBusy(true);
    try {
      const resp = await authFetch("/api/v1/portal/orders/easypost/rates", {
        method: "POST",
        body: JSON.stringify({
          order_id: orderId,
          parcel: {
            weight: parseFloat(parcel.weight),
            length: parseFloat(parcel.length),
            width: parseFloat(parcel.width),
            height: parseFloat(parcel.height),
          },
        }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => null);
        throw new Error(err?.detail || "Failed to get rates");
      }
      const data = await resp.json();
      setShipmentId(data.shipment_id);
      setRates(data.rates);
      setDebug(data.debug);
      if (data.rates.length > 0) setSelectedRate(data.rates[0].id);
      setStep("rates");
    } catch (e: any) {
      toast.error(e.message || "Failed to get rates");
    } finally {
      setBusy(false);
    }
  };

  const buy = async () => {
    if (!shipmentId || !selectedRate) return;
    setBusy(true);
    try {
      const resp = await authFetch("/api/v1/portal/orders/easypost/buy", {
        method: "POST",
        body: JSON.stringify({ order_id: orderId, shipment_id: shipmentId, rate_id: selectedRate }),
      });
      if (!resp.ok) {
        const err = await resp.json().catch(() => null);
        throw new Error(err?.detail || "Purchase failed");
      }
      toast.success("Label purchased — order is now Unfulfilled (ready to print)");
      onBought();
    } catch (e: any) {
      toast.error(e.message || "Purchase failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="font-semibold">Buy Label via EasyPost</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Order #{orderId} · {step === "parcel" ? "Step 1 of 2 — Parcel dimensions" : "Step 2 of 2 — Select rate"}
            </p>
          </div>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>

        {step === "parcel" && (
          <>
            <div className="mb-4 p-3 bg-blue-50 rounded-lg text-xs text-blue-700">
              Enter parcel dimensions to get live shipping rates (USPS &amp; UPS). Label cost will be recorded against the company.
            </div>
            {estimateInfo && (
              <div className={`mb-3 p-2 rounded-lg text-xs ${estimateInfo.complete ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-700"}`}>
                {estimateInfo.complete
                  ? "✓ Auto-filled from catalog dimensions. Adjust if needed."
                  : `Partial auto-fill — ${estimateInfo.missing.length} item(s) missing dimensions.`}
              </div>
            )}
            <div className="grid grid-cols-2 gap-3">
              {([["weight", "Weight (oz)"], ["length", "Length (in)"], ["width", "Width (in)"], ["height", "Height (in)"]] as [string, string][]).map(([k, label]) => (
                <div key={k}>
                  <label className="label">{label} *</label>
                  <input className="input" type="number" step="0.1" min="0.1" value={(parcel as any)[k]} onChange={pf(k)} />
                </div>
              ))}
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button className="btn-secondary" onClick={onClose}>Cancel</button>
              <button className="btn-primary flex items-center gap-1.5" disabled={!parcelValid || busy} onClick={getRates}>
                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Tag className="w-4 h-4" />}
                {busy ? "Getting rates…" : "Get Rates"}
              </button>
            </div>
          </>
        )}

        {step === "rates" && (
          <>
            {debug && (
              <div className="mb-3 border border-gray-200 rounded-lg p-3 bg-gray-50 text-xs">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-semibold text-gray-600 uppercase tracking-wide">EasyPost Request</span>
                  <button className="text-blue-600 hover:underline" onClick={() => setShowRawDebug((v) => !v)}>
                    {showRawDebug ? "Hide raw" : "Show raw JSON"}
                  </button>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div className="bg-white p-2 rounded border border-gray-200">
                    <div className="text-gray-500">Ship from</div>
                    <div className="text-gray-700">{debug.from_address.name}</div>
                    <div className="text-gray-700">{[debug.from_address.street1, debug.from_address.street2].filter(Boolean).join(", ")}</div>
                    <div className="text-gray-700">{[debug.from_address.city, debug.from_address.state, debug.from_address.zip].filter(Boolean).join(", ")}</div>
                  </div>
                  <div className="bg-white p-2 rounded border border-gray-200">
                    <div className="text-gray-500">Ship to</div>
                    <div className="text-gray-700">{debug.to_address.name}</div>
                    <div className="text-gray-700">{[debug.to_address.street1, debug.to_address.street2].filter(Boolean).join(", ")}</div>
                    <div className="text-gray-700">{[debug.to_address.city, debug.to_address.state, debug.to_address.zip].filter(Boolean).join(", ")}</div>
                  </div>
                </div>
                <div className="mt-2 bg-white p-2 rounded border border-gray-200">
                  <span className="text-gray-500">Parcel:</span>{" "}
                  <span className="font-medium">{debug.parcel.weight} oz · {debug.parcel.length}×{debug.parcel.width}×{debug.parcel.height} in</span>
                  <span className="ml-3 text-gray-500">Rates:</span>{" "}
                  <span className="font-medium">{debug.filtered_rates} shown / {debug.total_rates} total</span>
                </div>
                {showRawDebug && (
                  <pre className="mt-2 text-[10px] leading-tight p-2 max-h-40 overflow-auto bg-gray-900 text-gray-100 rounded font-mono">{JSON.stringify(debug, null, 2)}</pre>
                )}
              </div>
            )}
            {rates.length === 0 ? (
              <div className="text-center text-gray-400 py-8">No rates available.</div>
            ) : (
              <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                {rates.map((r) => (
                  <label key={r.id} className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${selectedRate === r.id ? "border-blue-500 bg-blue-50" : "border-gray-200 hover:border-gray-300"}`}>
                    <input type="radio" name="rate" checked={selectedRate === r.id} onChange={() => setSelectedRate(r.id)} className="accent-blue-600" />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${r.carrier === "UPS" ? "bg-amber-100 text-amber-800" : "bg-blue-100 text-blue-800"}`}>{r.carrier}</span>
                        <span className="text-xs text-gray-500">{r.service}</span>
                      </div>
                      {(r.delivery_days || r.est_delivery_days) && (
                        <div className="text-xs text-gray-400">
                          {r.delivery_days ?? r.est_delivery_days} business day(s)
                          {r.delivery_date && ` · by ${new Date(r.delivery_date).toLocaleDateString()}`}
                        </div>
                      )}
                    </div>
                    <span className="font-semibold text-sm">${parseFloat(r.rate).toFixed(2)} {r.currency}</span>
                  </label>
                ))}
              </div>
            )}
            <div className="flex justify-between gap-2 mt-5">
              <button className="btn-secondary" onClick={() => setStep("parcel")}>← Back</button>
              <div className="flex gap-2">
                <button className="btn-secondary" onClick={onClose}>Cancel</button>
                <button className="btn-primary flex items-center gap-1.5" disabled={!selectedRate || busy} onClick={buy}>
                  {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Truck className="w-4 h-4" />}
                  {busy ? "Purchasing…" : "Buy Label"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
