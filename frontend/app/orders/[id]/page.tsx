"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ordersApi, suppliersApi, easypostApi } from "@/lib/api";
import { useParams } from "next/navigation";
import toast from "react-hot-toast";
import { ArrowLeft, Truck, Package, X, UserPlus, CheckCircle2, Loader2, Tag } from "lucide-react";
import Link from "next/link";
import { OrderStatusBadge } from "../order-status-badge";

const FULFILL_STATUSES = ["unfulfilled", "pending", "shipped", "delivered", "cancelled"];

export default function OrderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const oid = parseInt(id);
  const qc = useQueryClient();
  const [showLabel, setShowLabel] = useState<{ supplierId: number; lineItemIds: number[] } | null>(null);
  const [assigningItem, setAssigningItem] = useState<number | null>(null); // line_item_id

  const { data: order } = useQuery({ queryKey: ["order", oid], queryFn: () => ordersApi.get(oid) });
  const { data: labels = [] } = useQuery({ queryKey: ["labels", oid], queryFn: () => ordersApi.listLabels(oid) });
  const { data: suppliers = [] } = useQuery({ queryKey: ["suppliers"], queryFn: () => suppliersApi.list() });

  const updateLIMut = useMutation({
    mutationFn: ({ liId, data }: { liId: number; data: object }) => ordersApi.updateLineItem(oid, liId, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["order", oid] }); toast.success("Updated"); },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  const assignSupplierMut = useMutation({
    mutationFn: ({ liId, data }: { liId: number; data: object }) => ordersApi.assignSupplier(oid, liId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["order", oid] });
      setAssigningItem(null);
      toast.success("Supplier assigned");
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  if (!order) return <div className="p-6 text-gray-400">Loading…</div>;

  const addr = order.shipping_address || {};
  const supplierGroups = groupBySupplier(order.line_items);

  const openBuyLabel = (supplierId: number | null, items: any[]) => {
    const sid = supplierId ?? -1;
    const ids = items.map((li: any) => li.id);
    setShowLabel({ supplierId: sid, lineItemIds: ids });
  };

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <Link href="/orders" className="p-2 hover:bg-gray-100 rounded-lg text-gray-500"><ArrowLeft className="w-4 h-4" /></Link>
        <div className="flex-1">
          <h1 className="page-title">Order #{order.id}</h1>
          <p className="text-sm text-gray-500 capitalize">{order.marketplace} · {new Date(order.ordered_at).toLocaleString()}</p>
        </div>
        <OrderStatusBadge status={order.status} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <div className="card p-4">
          <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Buyer</h3>
          <div className="text-sm font-medium">{order.buyer_name || "—"}</div>
          <div className="text-sm text-gray-500">{order.buyer_email || "—"}</div>
        </div>
        <div className="card p-4">
          <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Shipping Address</h3>
          {addr.line1 ? (
            <div className="text-sm text-gray-700 space-y-0.5">
              <div>{addr.name}</div>
              <div>{addr.line1}{addr.line2 && `, ${addr.line2}`}</div>
              <div>{[addr.city, addr.state, addr.zip].filter(Boolean).join(", ")}</div>
              <div>{addr.country}</div>
            </div>
          ) : <div className="text-sm text-gray-400">No address</div>}
        </div>
        <div className="card p-4">
          <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Summary</h3>
          <div className="text-sm space-y-1">
            <div className="flex justify-between"><span className="text-gray-500">Total</span><span className="font-semibold">${parseFloat(order.total).toFixed(2)}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Currency</span><span>{order.currency}</span></div>
            <div className="flex justify-between"><span className="text-gray-500">Items</span><span>{order.line_items.length}</span></div>
          </div>
        </div>
      </div>

      {/* Line items grouped by supplier */}
      {Object.entries(supplierGroups).map(([supplierId, items]) => {
        const sid = supplierId === "null" ? null : parseInt(supplierId);
        const supplier = suppliers.find((s: any) => s.id === sid);
        const supplierName = supplier?.name || (sid === null ? "Unassigned" : `Supplier #${supplierId}`);
        const unshipped = (items as any[]).filter((li: any) =>
          li.fulfill_status === "unfulfilled" || li.fulfill_status === "pending"
        );

        return (
          <div key={supplierId} className="card mb-4">
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
              <div className="flex items-center gap-2">
                <Package className="w-4 h-4 text-gray-400" />
                <span className="font-medium text-sm">{supplierName}</span>
                {sid === null && (
                  <span className="text-xs text-amber-600 bg-amber-50 px-2 py-0.5 rounded-full">Needs supplier</span>
                )}
              </div>
              {sid !== null && unshipped.length > 0 && (
                <button
                  className="btn-secondary text-xs py-1"
                  onClick={() => openBuyLabel(sid, items as any[])}
                >
                  <Truck className="w-3 h-3" /> Buy Label
                </button>
              )}
            </div>
            <div className="table-wrapper">
              <table>
                <thead><tr>
                  <th>Product</th><th>SKU</th><th>Qty</th><th>Price</th><th>Base Cost</th><th>Status</th><th>Tracking</th><th></th>
                </tr></thead>
                <tbody>
                  {(items as any[]).map((li: any) => (
                    <LineItemRow
                      key={li.id}
                      li={li}
                      suppliers={suppliers}
                      onUpdate={(data) => updateLIMut.mutate({ liId: li.id, data })}
                      onAssignSupplier={() => setAssigningItem(li.id)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}

      {/* Shipping Labels */}
      {labels.length > 0 && (
        <div className="card p-4">
          <h3 className="text-sm font-semibold mb-3">Shipping Labels</h3>
          <div className="space-y-2">
            {labels.map((l: any) => (
              <div key={l.id} className="flex items-center gap-4 text-sm py-2 border-b border-gray-100 last:border-0">
                <span className="badge-blue">{l.carrier}</span>
                {l.service && <span className="text-gray-500 text-xs">{l.service}</span>}
                <span className="font-mono text-xs">{l.tracking_number || "—"}</span>
                <span className="text-gray-500">${parseFloat(l.cost).toFixed(2)}</span>
                {l.label_url && <a href={l.label_url} target="_blank" className="text-blue-600 hover:underline text-xs">Download</a>}
              </div>
            ))}
          </div>
        </div>
      )}

      {showLabel !== null && (
        <LabelModal
          orderId={oid}
          supplierId={showLabel.supplierId}
          lineItemIds={showLabel.lineItemIds}
          onClose={() => setShowLabel(null)}
        />
      )}

      {assigningItem !== null && (
        <AssignSupplierModal
          orderId={oid}
          lineItemId={assigningItem}
          lineItem={order.line_items.find((li: any) => li.id === assigningItem)}
          suppliers={suppliers}
          onClose={() => setAssigningItem(null)}
          onAssign={(data) => assignSupplierMut.mutate({ liId: assigningItem, data })}
          loading={assignSupplierMut.isPending}
        />
      )}
    </div>
  );
}

function groupBySupplier(items: any[]) {
  return items.reduce((acc, li) => {
    const key = String(li.supplier_id ?? "null");
    if (!acc[key]) acc[key] = [];
    acc[key].push(li);
    return acc;
  }, {} as Record<string, any[]>);
}

function LineItemRow({ li, onUpdate, onAssignSupplier, suppliers }: {
  li: any;
  onUpdate: (d: object) => void;
  onAssignSupplier: () => void;
  suppliers: any[];
}) {
  const [status, setStatus] = useState(li.fulfill_status);
  const [tracking, setTracking] = useState(li.tracking_number || "");
  const [baseCost, setBaseCost] = useState(String(li.base_cost));

  const isShipped = status === "shipped" || status === "delivered";

  return (
    <tr>
      <td className="font-medium">{li.product_name}</td>
      <td className="font-mono text-xs text-gray-500">{li.sku || "—"}</td>
      <td>{li.quantity}</td>
      <td>${parseFloat(li.price).toFixed(2)}</td>
      <td>
        <input type="number" className="input w-20" value={baseCost} onChange={(e) => setBaseCost(e.target.value)}
          onBlur={() => onUpdate({ base_cost: parseFloat(baseCost) })} step="0.01" />
      </td>
      <td>
        <select className="input w-36 text-xs" value={status} onChange={(e) => {
          setStatus(e.target.value);
          onUpdate({ fulfill_status: e.target.value });
        }}>
          {FULFILL_STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
      </td>
      <td>
        {isShipped ? (
          <span className="font-mono text-xs text-gray-600">{tracking || "—"}</span>
        ) : (
          <input className="input w-32 text-xs" placeholder="tracking…" value={tracking} onChange={(e) => setTracking(e.target.value)}
            onBlur={() => tracking !== li.tracking_number && onUpdate({ tracking_number: tracking })} />
        )}
      </td>
      <td>
        {!li.supplier_id && (
          <button
            onClick={onAssignSupplier}
            className="flex items-center gap-1 text-xs text-amber-600 hover:text-amber-800 font-medium whitespace-nowrap"
          >
            <UserPlus className="w-3 h-3" /> Assign
          </button>
        )}
      </td>
    </tr>
  );
}

function AssignSupplierModal({ orderId, lineItemId, lineItem, suppliers, onClose, onAssign, loading }: {
  orderId: number;
  lineItemId: number;
  lineItem: any;
  suppliers: any[];
  onClose: () => void;
  onAssign: (data: object) => void;
  loading: boolean;
}) {
  const [supplierId, setSupplierId] = useState("");
  const [baseCost, setBaseCost] = useState(lineItem ? String(lineItem.base_cost) : "0");
  const [createPs, setCreatePs] = useState(true);
  const [isPreferred, setIsPreferred] = useState(false);

  const handleSubmit = () => {
    if (!supplierId) { return; }
    onAssign({
      supplier_id: parseInt(supplierId),
      base_cost: parseFloat(baseCost),
      create_product_supplier: createPs,
      is_preferred: isPreferred,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Assign Supplier</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>

        {lineItem && (
          <div className="mb-4 p-3 bg-gray-50 rounded-lg text-sm">
            <div className="font-medium">{lineItem.product_name}</div>
            {lineItem.sku && <div className="text-gray-500 font-mono text-xs">{lineItem.sku}</div>}
          </div>
        )}

        <div className="space-y-3">
          <div>
            <label className="label">Supplier *</label>
            <select className="input" value={supplierId} onChange={(e) => setSupplierId(e.target.value)}>
              <option value="">Select supplier…</option>
              {suppliers.map((s: any) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Base Cost (supplier price)</label>
            <input className="input" type="number" step="0.01" value={baseCost} onChange={(e) => setBaseCost(e.target.value)} />
          </div>
          {lineItem?.product_id && (
            <div className="space-y-2 border-t border-gray-100 pt-3">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={createPs} onChange={(e) => setCreatePs(e.target.checked)} className="rounded" />
                <span>Remember this supplier for future orders</span>
              </label>
              {createPs && (
                <label className="flex items-center gap-2 text-sm cursor-pointer ml-5">
                  <input type="checkbox" checked={isPreferred} onChange={(e) => setIsPreferred(e.target.checked)} className="rounded" />
                  <span>Set as preferred supplier (auto-assign)</span>
                </label>
              )}
            </div>
          )}
        </div>

        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button
            className="btn-primary flex items-center gap-1.5"
            onClick={handleSubmit}
            disabled={!supplierId || loading}
          >
            <CheckCircle2 className="w-4 h-4" />
            {loading ? "Assigning…" : "Assign Supplier"}
          </button>
        </div>
      </div>
    </div>
  );
}

/** Multi-step EasyPost label purchase modal */
function LabelModal({ orderId, supplierId, lineItemIds, onClose }: {
  orderId: number;
  supplierId: number;
  lineItemIds: number[];
  onClose: () => void;
}) {
  const qc = useQueryClient();

  // Step 1: parcel form
  const [parcel, setParcel] = useState({ weight: "", length: "", width: "", height: "" });
  // Step 2: rates
  const [shipmentId, setShipmentId] = useState<string | null>(null);
  const [rates, setRates] = useState<any[]>([]);
  const [selectedRate, setSelectedRate] = useState<string | null>(null);
  const [step, setStep] = useState<"parcel" | "rates" | "done">("parcel");

  const getRatesMut = useMutation({
    mutationFn: () =>
      easypostApi.getRates(orderId, {
        supplier_id: supplierId,
        line_item_ids: lineItemIds,
        parcel: {
          weight: parseFloat(parcel.weight),
          length: parseFloat(parcel.length),
          width: parseFloat(parcel.width),
          height: parseFloat(parcel.height),
        },
      }),
    onSuccess: (data) => {
      setShipmentId(data.shipment_id);
      setRates(data.rates);
      if (data.rates.length > 0) setSelectedRate(data.rates[0].id);
      setStep("rates");
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Failed to get rates"),
  });

  const buyMut = useMutation({
    mutationFn: () =>
      easypostApi.buyLabel(orderId, {
        supplier_id: supplierId,
        shipment_id: shipmentId,
        rate_id: selectedRate,
        line_item_ids: lineItemIds,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["labels", orderId] });
      qc.invalidateQueries({ queryKey: ["order", orderId] });
      toast.success("Label purchased via USPS — items moved to Pending");
      onClose();
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Purchase failed"),
  });

  const pf = (k: string) => (e: any) => setParcel((p) => ({ ...p, [k]: e.target.value }));
  const parcelValid = parcel.weight && parcel.length && parcel.width && parcel.height;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="font-semibold">Buy USPS Label via EasyPost</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {step === "parcel" ? "Step 1 of 2 — Parcel dimensions" : "Step 2 of 2 — Select rate"}
            </p>
          </div>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>

        {/* Step 1 — Parcel */}
        {step === "parcel" && (
          <>
            <div className="mb-4 p-3 bg-blue-50 rounded-lg text-xs text-blue-700">
              Covers <strong>{lineItemIds.length}</strong> item(s). Enter parcel dimensions to get live USPS rates.
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Weight (oz) *</label>
                <input className="input" type="number" step="0.1" min="0.1" placeholder="e.g. 16" value={parcel.weight} onChange={pf("weight")} />
              </div>
              <div>
                <label className="label">Length (in) *</label>
                <input className="input" type="number" step="0.1" min="0.1" placeholder="e.g. 12" value={parcel.length} onChange={pf("length")} />
              </div>
              <div>
                <label className="label">Width (in) *</label>
                <input className="input" type="number" step="0.1" min="0.1" placeholder="e.g. 9" value={parcel.width} onChange={pf("width")} />
              </div>
              <div>
                <label className="label">Height (in) *</label>
                <input className="input" type="number" step="0.1" min="0.1" placeholder="e.g. 4" value={parcel.height} onChange={pf("height")} />
              </div>
            </div>
            <div className="flex justify-end gap-2 mt-5">
              <button className="btn-secondary" onClick={onClose}>Cancel</button>
              <button
                className="btn-primary flex items-center gap-1.5"
                disabled={!parcelValid || getRatesMut.isPending}
                onClick={() => getRatesMut.mutate()}
              >
                {getRatesMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Tag className="w-4 h-4" />}
                {getRatesMut.isPending ? "Getting rates…" : "Get Rates"}
              </button>
            </div>
          </>
        )}

        {/* Step 2 — Rates */}
        {step === "rates" && (
          <>
            {rates.length === 0 ? (
              <div className="text-center text-gray-400 py-8">No rates available for this shipment.</div>
            ) : (
              <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                {rates.map((r) => (
                  <label
                    key={r.id}
                    className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                      selectedRate === r.id ? "border-blue-500 bg-blue-50" : "border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    <input
                      type="radio"
                      name="rate"
                      value={r.id}
                      checked={selectedRate === r.id}
                      onChange={() => setSelectedRate(r.id)}
                      className="accent-blue-600"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm">{r.carrier}</span>
                        <span className="text-xs text-gray-500">{r.service}</span>
                      </div>
                      {(r.delivery_days || r.est_delivery_days) && (
                        <div className="text-xs text-gray-400">
                          {r.delivery_days ?? r.est_delivery_days} business day(s)
                          {r.delivery_date && ` · by ${new Date(r.delivery_date).toLocaleDateString()}`}
                        </div>
                      )}
                    </div>
                    <span className="font-semibold text-sm text-gray-800">${parseFloat(r.rate).toFixed(2)} {r.currency}</span>
                  </label>
                ))}
              </div>
            )}
            <div className="flex justify-between gap-2 mt-5">
              <button className="btn-secondary" onClick={() => setStep("parcel")}>← Back</button>
              <div className="flex gap-2">
                <button className="btn-secondary" onClick={onClose}>Cancel</button>
                <button
                  className="btn-primary flex items-center gap-1.5"
                  disabled={!selectedRate || buyMut.isPending}
                  onClick={() => buyMut.mutate()}
                >
                  {buyMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Truck className="w-4 h-4" />}
                  {buyMut.isPending ? "Purchasing…" : "Buy Label"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
