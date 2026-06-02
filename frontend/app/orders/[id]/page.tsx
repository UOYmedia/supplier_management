"use client";
import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ordersApi, suppliersApi, easypostApi, amazonShippingApi } from "@/lib/api";
import { useParams, useSearchParams } from "next/navigation";
import toast from "react-hot-toast";
import { ArrowLeft, Truck, Package, X, UserPlus, CheckCircle2, Loader2, Tag, ExternalLink, Download, Printer, Pencil, Upload, RefreshCw } from "lucide-react";
import Link from "next/link";
import { OrderStatusBadge } from "../order-status-badge";

const FULFILL_STATUSES = ["unfulfilled", "pending", "shipped", "delivered", "cancelled"];

export default function OrderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const oid = parseInt(id);
  const qc = useQueryClient();
  const searchParams = useSearchParams();
  const [showLabel, setShowLabel] = useState<{ supplierId: number; lineItemIds: number[] } | null>(null);
  const [manualLabel, setManualLabel] = useState<{ supplierId: number; lineItemIds: number[] } | null>(null);
  const [editingLabel, setEditingLabel] = useState<any>(null);
  const [assigningItem, setAssigningItem] = useState<number | null>(null);
  const [autoOpenedForSupplier, setAutoOpenedForSupplier] = useState<number | null>(null);

  const { data: order } = useQuery({ queryKey: ["order", oid], queryFn: () => ordersApi.get(oid), throwOnError: false });
  const { data: labels = [] } = useQuery({ queryKey: ["labels", oid], queryFn: () => ordersApi.listLabels(oid), throwOnError: false });
  const { data: suppliers = [] } = useQuery({ queryKey: ["suppliers"], queryFn: () => suppliersApi.list(), throwOnError: false });

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

  const markPrintedMut = useMutation({
    mutationFn: (labelId: number) =>
      ordersApi.markLabelPrinted(oid, labelId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["order", oid] });
      qc.invalidateQueries({ queryKey: ["labels", oid] });
    },
  });

  const syncTrackingMut = useMutation({
    mutationFn: () => ordersApi.syncTracking(oid),
    onSuccess: (res: any) => {
      const n = res.synced?.length ?? 0;
      toast.success(n > 0 ? `Synced ${n} fulfillment(s) to Shopify` : "No new fulfillments to sync");
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Shopify sync failed"),
  });

  // Auto-open Buy Label modal when navigated from supplier orders tab
  useEffect(() => {
    if (!order || autoOpenedForSupplier !== null) return;
    const raw = searchParams.get("buy_label_supplier");
    if (!raw) return;
    const sid = parseInt(raw);
    if (Number.isNaN(sid)) return;
    const items = order.line_items.filter(
      (li: any) =>
        li.supplier_id === sid &&
        !li.tracking_number &&
        (li.fulfill_status === "unfulfilled" || li.fulfill_status === "pending")
    );
    if (items.length > 0) {
      setShowLabel({ supplierId: sid, lineItemIds: items.map((li: any) => li.id) });
      setAutoOpenedForSupplier(sid);
    }
  }, [order, searchParams, autoOpenedForSupplier]);

  if (!order) return <div className="p-6 text-gray-400">Loading…</div>;

  const addr = order.shipping_address || {};
  const supplierGroups = groupBySupplier(order.line_items);
  const isAmazonOrder = order.marketplace === "amazon" && !!order.external_order_id;
  const isShopifyOrder = order.marketplace === "shopify" && !!order.external_order_id;

  const unmappedCount = order.line_items.filter((li: any) => !li.supplier_id).length;
  const supplierIds = order.line_items
    .map((li: any) => li.supplier_id)
    .filter((s: any) => s != null);
  const uniqueSupplierCount = new Set(supplierIds).size;
  const allMapped = unmappedCount === 0 && order.line_items.length > 0;
  const isShipped = ["fulfilled", "partially_fulfilled"].includes(order.status);

  const openBuyLabel = (supplierId: number | null, items: any[]) => {
    const sid = supplierId ?? -1;
    const ids = items.map((li: any) => li.id);
    setShowLabel({ supplierId: sid, lineItemIds: ids });
  };

  const printLabel = (url: string) => {
    if (!url) return;
    const win = window.open(url, "_blank");
    if (!win) {
      toast.error("Popup blocked — allow popups to print labels");
      return;
    }
    try {
      win.focus();
      setTimeout(() => {
        try { win.print(); } catch {}
      }, 800);
    } catch {}
  };

  const printLabelsForGroup = (items: any[]) => {
    const labelIds = Array.from(new Set(items.map((li) => li.label_id).filter(Boolean)));
    if (labelIds.length === 0) {
      toast.error("No label found for this group");
      return;
    }
    for (const labelId of labelIds) {
      const lbl = labels.find((l: any) => l.id === labelId);
      if (!lbl) continue;
      const url = lbl.has_label_data
        ? ordersApi.labelDownloadUrl(oid, lbl.id)
        : lbl.label_url;
      if (url) printLabel(url);
      markPrintedMut.mutate(labelId);
    }
  };

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <Link href="/orders" className="p-2 hover:bg-gray-100 rounded-lg text-gray-500"><ArrowLeft className="w-4 h-4" /></Link>
        <div className="flex-1">
          <h1 className="page-title">{order.order_name || `Order #${order.id}`}</h1>
          <div className="flex items-center gap-2 mt-0.5">
            <p className="text-sm text-gray-500 capitalize">{order.marketplace} · {new Date(order.ordered_at).toLocaleString()}</p>
            {order.external_order_id && !order.order_name && (
              <span className="text-xs font-mono text-gray-400">{order.external_order_id}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {isShopifyOrder && (
            <button
              className="btn-secondary text-xs"
              onClick={() => syncTrackingMut.mutate()}
              disabled={syncTrackingMut.isPending}
              title="Push tracking number to Shopify"
            >
              {syncTrackingMut.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              Sync to Shopify
            </button>
          )}
          <OrderStatusBadge status={order.status} />
        </div>
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
            {isAmazonOrder && (
              <div className="flex justify-between"><span className="text-gray-500">Source</span><span className="badge-orange text-xs">Amazon</span></div>
            )}
          </div>
        </div>
      </div>

      {/* Dispatch readiness */}
      {!isShipped && (
        <div className={`card p-3 mb-4 text-sm flex items-center gap-2 ${
          allMapped
            ? uniqueSupplierCount === 1 ? "bg-green-50 border-green-200" : "bg-blue-50 border-blue-200"
            : "bg-amber-50 border-amber-200"
        }`}>
          {allMapped ? (
            uniqueSupplierCount === 1 ? (
              <>
                <CheckCircle2 className="w-4 h-4 text-green-700" />
                <span className="text-green-800">
                  Ready to dispatch — all {order.line_items.length} item(s) mapped to a single supplier. Buy one label to ship the whole order with one tracking number.
                </span>
              </>
            ) : (
              <>
                <CheckCircle2 className="w-4 h-4 text-blue-700" />
                <span className="text-blue-800">
                  Ready to dispatch — items split across <strong>{uniqueSupplierCount}</strong> suppliers. Buy one label per supplier; each group gets its own tracking number.
                </span>
              </>
            )
          ) : (
            <>
              <UserPlus className="w-4 h-4 text-amber-700" />
              <span className="text-amber-800">
                {unmappedCount} of {order.line_items.length} item(s) still need a supplier mapping. The order will wait until every line item is assigned.
              </span>
            </>
          )}
        </div>
      )}

      {/* Line items grouped by supplier */}
      {Object.entries(supplierGroups).map(([supplierId, items]) => {
        const sid = supplierId === "null" ? null : parseInt(supplierId);
        const supplier = suppliers.find((s: any) => s.id === sid);
        const supplierName = supplier?.name || (sid === null ? "Unassigned" : `Supplier #${supplierId}`);
        const unshipped = (items as any[]).filter((li: any) =>
          li.fulfill_status === "unfulfilled" || li.fulfill_status === "pending"
        );
        const needsLabel = unshipped.filter((li: any) => !li.tracking_number);
        const itemsWithLabel = (items as any[]).filter((li: any) => li.label_id);

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
              <div className="flex gap-2">
                {itemsWithLabel.length > 0 && (
                  <button
                    className="btn-primary text-xs py-1"
                    onClick={() => printLabelsForGroup(itemsWithLabel)}
                  >
                    <Printer className="w-3 h-3" /> Print Label
                  </button>
                )}
                {sid !== null && needsLabel.length > 0 && (
                  <button
                    className="btn-secondary text-xs py-1"
                    onClick={() => openBuyLabel(sid, needsLabel)}
                  >
                    <Truck className="w-3 h-3" /> Buy Label ({needsLabel.length})
                  </button>
                )}
                {sid !== null && needsLabel.length > 0 && (
                  <button
                    className="btn-secondary text-xs py-1"
                    onClick={() => setManualLabel({ supplierId: sid, lineItemIds: needsLabel.map((li: any) => li.id) })}
                    title="Provide a label manually (tracking + optional PDF) without buying through a carrier"
                  >
                    <Tag className="w-3 h-3" /> Manual Label
                  </button>
                )}
              </div>
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
                {l.has_label_data && (
                  <a
                    href={ordersApi.labelDownloadUrl(oid, l.id)}
                    target="_blank"
                    className="flex items-center gap-1 text-blue-600 hover:underline text-xs"
                  >
                    <Download className="w-3 h-3" /> Download PDF
                  </a>
                )}
                {!l.has_label_data && l.label_url && (
                  <a href={l.label_url} target="_blank" className="flex items-center gap-1 text-blue-600 hover:underline text-xs">
                    <ExternalLink className="w-3 h-3" /> Download
                  </a>
                )}
                {!l.has_label_data && !l.label_url && (
                  <span className="text-xs text-amber-600">No PDF — upload one</span>
                )}
                <button
                  className="flex items-center gap-1 text-gray-500 hover:text-gray-800 text-xs ml-auto"
                  onClick={() => setEditingLabel(l)}
                >
                  <Pencil className="w-3 h-3" /> Edit
                </button>
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
          isAmazonOrder={isAmazonOrder}
          amazonOrderId={order.external_order_id}
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

      {manualLabel !== null && (
        <ManualLabelModal
          orderId={oid}
          supplierId={manualLabel.supplierId}
          lineItemIds={manualLabel.lineItemIds}
          onClose={() => setManualLabel(null)}
          onDone={() => {
            qc.invalidateQueries({ queryKey: ["order", oid] });
            qc.invalidateQueries({ queryKey: ["labels", oid] });
            setManualLabel(null);
          }}
        />
      )}

      {editingLabel !== null && (
        <EditLabelModal
          orderId={oid}
          label={editingLabel}
          onClose={() => setEditingLabel(null)}
          onDone={() => {
            qc.invalidateQueries({ queryKey: ["order", oid] });
            qc.invalidateQueries({ queryKey: ["labels", oid] });
            setEditingLabel(null);
          }}
        />
      )}
    </div>
  );
}

function ManualLabelModal({ orderId, supplierId, lineItemIds, onClose, onDone }: {
  orderId: number;
  supplierId: number;
  lineItemIds: number[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [carrier, setCarrier] = useState("");
  const [service, setService] = useState("");
  const [tracking, setTracking] = useState("");
  const [cost, setCost] = useState("0");
  const [labelUrl, setLabelUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [saving, setSaving] = useState(false);

  const handleSubmit = async () => {
    if (!carrier.trim()) { toast.error("Carrier is required"); return; }
    setSaving(true);
    try {
      const label = await ordersApi.createLabel(orderId, {
        supplier_id: supplierId,
        carrier: carrier.trim(),
        service: service.trim() || undefined,
        tracking_number: tracking.trim() || undefined,
        label_url: labelUrl.trim() || undefined,
        cost: parseFloat(cost) || 0,
        line_item_ids: lineItemIds,
      });
      if (file) {
        await ordersApi.uploadLabel(orderId, label.id, file);
      }
      toast.success("Manual label saved");
      onDone();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || "Error saving label");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Manual Label</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <p className="text-xs text-gray-500 mb-4">
          Provide a label bought outside the system for {lineItemIds.length} item(s). Items move to <strong>pending</strong>.
        </p>
        <div className="space-y-3">
          <div>
            <label className="label">Carrier *</label>
            <input className="input" value={carrier} onChange={(e) => setCarrier(e.target.value)} placeholder="e.g. USPS, UPS, DHL" />
          </div>
          <div>
            <label className="label">Service</label>
            <input className="input" value={service} onChange={(e) => setService(e.target.value)} placeholder="e.g. Ground, Priority" />
          </div>
          <div>
            <label className="label">Tracking Number</label>
            <input className="input" value={tracking} onChange={(e) => setTracking(e.target.value)} placeholder="Tracking #" />
          </div>
          <div>
            <label className="label">Cost ($)</label>
            <input className="input" type="number" step="0.01" min="0" value={cost} onChange={(e) => setCost(e.target.value)} />
          </div>
          <div>
            <label className="label">Label URL (optional)</label>
            <input className="input" value={labelUrl} onChange={(e) => setLabelUrl(e.target.value)} placeholder="https://…" />
          </div>
          <div>
            <label className="label">Or upload label PDF (optional)</label>
            <label className="btn-secondary cursor-pointer inline-flex">
              <Upload className="w-4 h-4" /> {file ? file.name : "Choose PDF"}
              <input type="file" accept="application/pdf,.pdf" className="hidden" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            </label>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={!carrier.trim() || saving} onClick={handleSubmit}>
            {saving ? "Saving…" : "Save Label"}
          </button>
        </div>
      </div>
    </div>
  );
}

function EditLabelModal({ orderId, label, onClose, onDone }: {
  orderId: number;
  label: any;
  onClose: () => void;
  onDone: () => void;
}) {
  const [carrier, setCarrier] = useState(label.carrier || "");
  const [service, setService] = useState(label.service || "");
  const [tracking, setTracking] = useState(label.tracking_number || "");
  const [cost, setCost] = useState(String(label.cost ?? "0"));
  const [labelUrl, setLabelUrl] = useState(label.label_url || "");
  const [file, setFile] = useState<File | null>(null);
  const [size, setSize] = useState("4x6");
  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);

  const handleSubmit = async () => {
    setSaving(true);
    try {
      await ordersApi.updateLabel(orderId, label.id, {
        carrier: carrier.trim() || undefined,
        service: service.trim() || null,
        tracking_number: tracking.trim() || null,
        cost: parseFloat(cost) || 0,
        label_url: labelUrl.trim() || null,
      });
      if (file) {
        await ordersApi.uploadLabel(orderId, label.id, file);
      }
      toast.success("Label updated");
      onDone();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || "Error updating label");
    } finally {
      setSaving(false);
    }
  };

  const handleRegenerate = async () => {
    setRegenerating(true);
    try {
      await ordersApi.regenerateLabel(orderId, label.id, size);
      toast.success(`Label PDF regenerated (${size})`);
      onDone();
    } catch (e: any) {
      toast.error(e.response?.data?.detail || "Error regenerating label");
    } finally {
      setRegenerating(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Edit Label</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="label">Carrier</label>
            <input className="input" value={carrier} onChange={(e) => setCarrier(e.target.value)} />
          </div>
          <div>
            <label className="label">Service</label>
            <input className="input" value={service} onChange={(e) => setService(e.target.value)} />
          </div>
          <div>
            <label className="label">Tracking Number</label>
            <input className="input" value={tracking} onChange={(e) => setTracking(e.target.value)} />
            <p className="text-xs text-gray-400 mt-1">Updating this also updates the tracking number on all linked items.</p>
          </div>
          <div>
            <label className="label">Cost ($)</label>
            <input className="input" type="number" step="0.01" min="0" value={cost} onChange={(e) => setCost(e.target.value)} />
          </div>
          <div>
            <label className="label">Label URL</label>
            <input className="input" value={labelUrl} onChange={(e) => setLabelUrl(e.target.value)} placeholder="https://…" />
          </div>
          <div>
            <label className="label">{label.has_label_data ? "Replace label PDF" : "Upload label PDF"}</label>
            <label className="btn-secondary cursor-pointer inline-flex">
              <Upload className="w-4 h-4" /> {file ? file.name : "Choose PDF"}
              <input type="file" accept="application/pdf,.pdf" className="hidden" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            </label>
          </div>
          <div className="border-t border-gray-100 pt-3">
            <label className="label">Re-generate PDF from carrier</label>
            <p className="text-xs text-gray-400 mb-2">Re-fetch the label from EasyPost at the chosen size (fixes a missing PDF or changes the print size). Only works for labels bought through EasyPost.</p>
            <div className="flex items-center gap-2">
              <select className="input w-28" value={size} onChange={(e) => setSize(e.target.value)}>
                <option value="4x6">4x6</option>
                <option value="7x3">7x3</option>
              </select>
              <button className="btn-secondary inline-flex" disabled={regenerating} onClick={handleRegenerate}>
                {regenerating ? <Loader2 className="w-4 h-4 animate-spin" /> : <Tag className="w-4 h-4" />}
                {regenerating ? "Regenerating…" : "Re-generate"}
              </button>
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={saving} onClick={handleSubmit}>
            {saving ? "Saving…" : "Save Changes"}
          </button>
        </div>
      </div>
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
  const [selectedSpId, setSelectedSpId] = useState<number | null>(null);
  const [units, setUnits] = useState("1");
  const [baseCost, setBaseCost] = useState(lineItem ? String(lineItem.base_cost) : "0");
  const [createPs, setCreatePs] = useState(true);
  const [isPreferred, setIsPreferred] = useState(false);
  const [spQuery, setSpQuery] = useState("");

  const { data: catalog = [] } = useQuery({
    queryKey: ["supplier-catalog", supplierId],
    queryFn: () => suppliersApi.listProducts(parseInt(supplierId)),
    enabled: !!supplierId,
  });

  const selectedSp = catalog.find((c: any) => c.id === selectedSpId);
  const filtered = spQuery
    ? catalog.filter((sp: any) =>
        sp.name.toLowerCase().includes(spQuery.toLowerCase()) ||
        sp.sku.toLowerCase().includes(spQuery.toLowerCase())
      )
    : catalog;

  const chooseSp = (sp: any) => {
    setSelectedSpId(sp.id);
    const u = Math.max(1, parseInt(units) || 1);
    setBaseCost((parseFloat(sp.unit_price) * u).toFixed(2));
    setSpQuery("");
  };

  const onUnitsChange = (e: any) => {
    const v = e.target.value;
    setUnits(v);
    if (selectedSp) {
      const u = Math.max(1, parseInt(v) || 1);
      setBaseCost((parseFloat(selectedSp.unit_price) * u).toFixed(2));
    }
  };

  const onSupplierChange = (e: any) => {
    setSupplierId(e.target.value);
    setSelectedSpId(null);
    setSpQuery("");
  };

  const handleSubmit = () => {
    if (!supplierId) return;
    const payload: any = {
      supplier_id: parseInt(supplierId),
      base_cost: parseFloat(baseCost),
      create_product_supplier: createPs,
      is_preferred: isPreferred,
    };
    if (selectedSpId) {
      payload.supplier_product_id = selectedSpId;
      payload.units = Math.max(1, parseInt(units) || 1);
    }
    onAssign(payload);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Assign Supplier</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>

        {lineItem && (
          <div className="mb-4 p-3 bg-gray-50 rounded-lg text-sm">
            <div className="font-medium">{lineItem.product_name}</div>
            {lineItem.sku && <div className="text-gray-500 font-mono text-xs">{lineItem.sku}</div>}
            <div className="text-xs text-gray-500 mt-1">Qty {lineItem.quantity} · ${parseFloat(lineItem.price).toFixed(2)} each</div>
          </div>
        )}

        <div className="space-y-3">
          <div>
            <label className="label">Supplier *</label>
            <select className="input" value={supplierId} onChange={onSupplierChange}>
              <option value="">Select supplier…</option>
              {suppliers.map((s: any) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>

          {supplierId && (
            <div>
              <label className="label">Catalog Item {catalog.length > 0 && <span className="text-gray-400 font-normal">({catalog.length} available)</span>}</label>
              {selectedSp ? (
                <div className="flex items-center justify-between gap-2 p-2 rounded-lg border border-blue-200 bg-blue-50">
                  <div className="min-w-0">
                    <div className="font-medium text-sm truncate">{selectedSp.name}</div>
                    <div className="text-xs text-gray-500 font-mono">{selectedSp.sku} · ${parseFloat(selectedSp.unit_price).toFixed(2)} · stock {selectedSp.stock_quantity}</div>
                  </div>
                  <button className="text-xs text-gray-500 hover:text-red-500" onClick={() => setSelectedSpId(null)}>Change</button>
                </div>
              ) : catalog.length === 0 ? (
                <p className="text-xs text-gray-400">Supplier has no catalog items. Enter base cost manually below.</p>
              ) : (
                <>
                  <input
                    className="input"
                    placeholder="Search by name or SKU…"
                    value={spQuery}
                    onChange={(e) => setSpQuery(e.target.value)}
                  />
                  <div className="mt-1 border border-gray-200 rounded-lg max-h-40 overflow-y-auto bg-white">
                    {filtered.length === 0 ? (
                      <div className="p-2 text-xs text-gray-400">No matches</div>
                    ) : filtered.slice(0, 50).map((sp: any) => (
                      <button
                        key={sp.id}
                        type="button"
                        className="w-full text-left px-2 py-1.5 text-sm hover:bg-blue-50 border-b border-gray-100 last:border-0"
                        onClick={() => chooseSp(sp)}
                      >
                        <div className="font-medium truncate">{sp.name}</div>
                        <div className="text-xs text-gray-500 font-mono">{sp.sku} · ${parseFloat(sp.unit_price).toFixed(2)} · stock {sp.stock_quantity}</div>
                      </button>
                    ))}
                  </div>
                  <p className="text-xs text-gray-400 mt-1">Picking a catalog item maps this variant for future orders and creates fulfillment items.</p>
                </>
              )}
            </div>
          )}

          {selectedSp && (
            <div>
              <label className="label">Units per shop unit *</label>
              <input
                className="input"
                type="number"
                min="1"
                value={units}
                onChange={onUnitsChange}
              />
              <p className="text-xs text-gray-400 mt-1">
                Cost auto-updates to ${parseFloat(selectedSp.unit_price).toFixed(2)} × {units || 1} = <strong>${(parseFloat(selectedSp.unit_price) * (parseInt(units) || 1)).toFixed(2)}</strong> per shop unit. Order line qty {lineItem?.quantity || 1} → supplier ships {(parseInt(units) || 1) * (lineItem?.quantity || 1)} unit(s).
              </p>
            </div>
          )}

          <div>
            <label className="label">Base Cost (per shop unit)</label>
            <input className="input" type="number" step="0.01" value={baseCost} onChange={(e) => setBaseCost(e.target.value)} />
          </div>

          {lineItem?.product_id && (
            <div className="space-y-2 border-t border-gray-100 pt-3">
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={createPs} onChange={(e) => setCreatePs(e.target.checked)} className="rounded" />
                <span>Remember this supplier for future orders of this variant</span>
              </label>
              {createPs && (
                <label className="flex items-center gap-2 text-sm cursor-pointer ml-5">
                  <input type="checkbox" checked={isPreferred} onChange={(e) => setIsPreferred(e.target.checked)} className="rounded" />
                  <span>Set as preferred supplier (auto-assign next time)</span>
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

/** Label modal — choose Amazon MFN or EasyPost */
function LabelModal({ orderId, supplierId, lineItemIds, isAmazonOrder, amazonOrderId, onClose }: {
  orderId: number;
  supplierId: number;
  lineItemIds: number[];
  isAmazonOrder: boolean;
  amazonOrderId?: string | null;
  onClose: () => void;
}) {
  const [provider, setProvider] = useState<"amazon" | "easypost">(isAmazonOrder ? "amazon" : "easypost");

  if (provider === "amazon" && isAmazonOrder) {
    return (
      <AmazonLabelModal
        orderId={orderId}
        supplierId={supplierId}
        lineItemIds={lineItemIds}
        amazonOrderId={amazonOrderId!}
        onClose={onClose}
        onSwitchToEasyPost={() => setProvider("easypost")}
      />
    );
  }

  return (
    <EasyPostLabelModal
      orderId={orderId}
      supplierId={supplierId}
      lineItemIds={lineItemIds}
      showAmazonOption={isAmazonOrder}
      onClose={onClose}
      onSwitchToAmazon={isAmazonOrder ? () => setProvider("amazon") : undefined}
    />
  );
}

/** Amazon MFN shipping modal */
function AmazonLabelModal({ orderId, supplierId, lineItemIds, amazonOrderId, onClose, onSwitchToEasyPost }: {
  orderId: number;
  supplierId: number;
  lineItemIds: number[];
  amazonOrderId: string;
  onClose: () => void;
  onSwitchToEasyPost: () => void;
}) {
  const qc = useQueryClient();
  const [parcel, setParcel] = useState({ weight: "", length: "", width: "", height: "" });
  const [services, setServices] = useState<any[]>([]);
  const [selectedService, setSelectedService] = useState<any>(null);
  const [step, setStep] = useState<"parcel" | "services">("parcel");
  const [estimateInfo, setEstimateInfo] = useState<{ complete: boolean; missing: any[] } | null>(null);

  useEffect(() => {
    ordersApi
      .parcelEstimate(orderId, { supplier_id: supplierId, line_item_ids: lineItemIds })
      .then((est: any) => {
        setParcel({
          weight: est.weight > 0 ? String(est.weight) : "",
          length: est.length > 0 ? String(est.length) : "",
          width: est.width > 0 ? String(est.width) : "",
          height: est.height > 0 ? String(est.height) : "",
        });
        setEstimateInfo({ complete: !!est.complete, missing: est.missing || [] });
      })
      .catch(() => {});
  }, [orderId, supplierId]);

  const getRatesMut = useMutation({
    mutationFn: () =>
      amazonShippingApi.getRates(orderId, {
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
      setServices(data.services);
      if (data.services.length > 0) setSelectedService(data.services[0]);
      setStep("services");
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Failed to get Amazon rates"),
  });

  const buyMut = useMutation({
    mutationFn: () =>
      amazonShippingApi.buyLabel(orderId, {
        supplier_id: supplierId,
        amazon_order_id: amazonOrderId,
        shipping_service_id: selectedService.shipping_service_id,
        shipping_service_offer_id: selectedService.shipping_service_offer_id,
        line_item_ids: lineItemIds,
        parcel: {
          weight: parseFloat(parcel.weight),
          length: parseFloat(parcel.length),
          width: parseFloat(parcel.width),
          height: parseFloat(parcel.height),
        },
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["labels", orderId] });
      qc.invalidateQueries({ queryKey: ["order", orderId] });
      toast.success("Amazon label purchased — items moved to Pending");
      onClose();
    },
    onError: (e: any) => {
      const detail = e.response?.data?.detail;
      const msg = Array.isArray(detail)
        ? detail.map((d: any) => d.msg || d.type || JSON.stringify(d)).join("; ")
        : detail || "Purchase failed";
      toast.error(msg);
    },
  });

  const pf = (k: string) => (e: any) => setParcel((p) => ({ ...p, [k]: e.target.value }));
  const parcelValid = parcel.weight && parcel.length && parcel.width && parcel.height;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="flex items-center gap-2">
              <h2 className="font-semibold">Buy Label via Amazon</h2>
              <span className="badge-orange text-xs">Amazon MFN</span>
            </div>
            <p className="text-xs text-gray-500 mt-0.5">
              {step === "parcel" ? "Step 1 of 2 — Parcel dimensions" : "Step 2 of 2 — Select service"}
            </p>
          </div>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>

        {step === "parcel" && (
          <>
            <div className="mb-4 p-3 bg-orange-50 rounded-lg text-xs text-orange-700">
              Amazon Order: <strong className="font-mono">{amazonOrderId}</strong> · {lineItemIds.length} item(s)
            </div>
            {estimateInfo && (
              <div className={`mb-3 p-2 rounded-lg text-xs ${
                estimateInfo.complete ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-700"
              }`}>
                {estimateInfo.complete
                  ? "✓ Auto-filled from catalog dimensions. Adjust if needed."
                  : `Partial auto-fill — ${estimateInfo.missing.length} item(s) missing dimensions.`}
              </div>
            )}
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
            <div className="flex items-center justify-between mt-5">
              <button className="text-xs text-blue-600 hover:underline" onClick={onSwitchToEasyPost}>
                Use EasyPost instead →
              </button>
              <div className="flex gap-2">
                <button className="btn-secondary" onClick={onClose}>Cancel</button>
                <button
                  className="btn-primary flex items-center gap-1.5"
                  disabled={!parcelValid || getRatesMut.isPending}
                  onClick={() => getRatesMut.mutate()}
                >
                  {getRatesMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Tag className="w-4 h-4" />}
                  {getRatesMut.isPending ? "Getting rates…" : "Get Amazon Rates"}
                </button>
              </div>
            </div>
          </>
        )}

        {step === "services" && (
          <>
            {services.length === 0 ? (
              <div className="text-center text-gray-400 py-8">
                No Amazon shipping services available.<br />
                <button className="text-sm text-blue-600 hover:underline mt-2" onClick={onSwitchToEasyPost}>Try EasyPost instead</button>
              </div>
            ) : (
              <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                {services.map((s) => (
                  <label
                    key={s.shipping_service_id}
                    className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                      selectedService?.shipping_service_id === s.shipping_service_id
                        ? "border-orange-500 bg-orange-50"
                        : "border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    <input
                      type="radio"
                      name="amz-service"
                      checked={selectedService?.shipping_service_id === s.shipping_service_id}
                      onChange={() => setSelectedService(s)}
                      className="accent-orange-500"
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm">{s.carrier}</span>
                        <span className="text-xs text-gray-500">{s.name}</span>
                      </div>
                      {(s.earliest_delivery || s.latest_delivery) && (
                        <div className="text-xs text-gray-400">
                          Est. {s.earliest_delivery ? new Date(s.earliest_delivery).toLocaleDateString() : "—"}
                          {s.latest_delivery ? ` – ${new Date(s.latest_delivery).toLocaleDateString()}` : ""}
                        </div>
                      )}
                    </div>
                    <span className="font-semibold text-sm">${s.rate.toFixed(2)} {s.currency}</span>
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
                  disabled={!selectedService || buyMut.isPending}
                  onClick={() => buyMut.mutate()}
                >
                  {buyMut.isPending ? <Loader2 className="w-4 h-4 animate-spin" /> : <Truck className="w-4 h-4" />}
                  {buyMut.isPending ? "Purchasing…" : "Buy Amazon Label"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** EasyPost shipping modal */
function EasyPostLabelModal({ orderId, supplierId, lineItemIds, showAmazonOption, onClose, onSwitchToAmazon }: {
  orderId: number;
  supplierId: number;
  lineItemIds: number[];
  showAmazonOption?: boolean;
  onClose: () => void;
  onSwitchToAmazon?: () => void;
}) {
  const qc = useQueryClient();
  const [parcel, setParcel] = useState({ weight: "", length: "", width: "", height: "" });
  const [shipmentId, setShipmentId] = useState<string | null>(null);
  const [rates, setRates] = useState<any[]>([]);
  const [selectedRate, setSelectedRate] = useState<string | null>(null);
  const [step, setStep] = useState<"parcel" | "rates">("parcel");
  const [estimateInfo, setEstimateInfo] = useState<{ complete: boolean; missing: any[] } | null>(null);
  const [debug, setDebug] = useState<any | null>(null);
  const [showRawDebug, setShowRawDebug] = useState(false);

  const { data: orderForPreview } = useQuery({ queryKey: ["order", orderId], queryFn: () => ordersApi.get(orderId) });
  const { data: supplierForPreview } = useQuery({ queryKey: ["supplier", supplierId], queryFn: () => suppliersApi.get(supplierId) });

  useEffect(() => {
    ordersApi
      .parcelEstimate(orderId, { supplier_id: supplierId, line_item_ids: lineItemIds })
      .then((est: any) => {
        setParcel({
          weight: est.weight > 0 ? String(est.weight) : "",
          length: est.length > 0 ? String(est.length) : "",
          width: est.width > 0 ? String(est.width) : "",
          height: est.height > 0 ? String(est.height) : "",
        });
        setEstimateInfo({ complete: !!est.complete, missing: est.missing || [] });
      })
      .catch(() => {});
  }, [orderId, supplierId]);

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
      setDebug(data.debug);
      if (data.rates.length > 0) setSelectedRate(data.rates[0].id);
      setStep("rates");
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Failed to get rates"),
  });

  const buyMut = useMutation({
    mutationFn: () => {
      if (!shipmentId || !selectedRate) {
        toast.error("No rate selected — please get rates first");
        return Promise.reject(new Error("missing rate"));
      }
      return easypostApi.buyLabel(orderId, {
        supplier_id: supplierId,
        shipment_id: shipmentId,
        rate_id: selectedRate,
        line_item_ids: lineItemIds,
      });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["labels", orderId] });
      qc.invalidateQueries({ queryKey: ["order", orderId] });
      toast.success("Label purchased — items moved to Pending");
      onClose();
    },
    onError: (e: any) => {
      const detail = e.response?.data?.detail;
      const msg = Array.isArray(detail)
        ? detail.map((d: any) => d.msg || d.type || JSON.stringify(d)).join("; ")
        : detail || "Purchase failed";
      toast.error(msg);
    },
  });

  const pf = (k: string) => (e: any) => setParcel((p) => ({ ...p, [k]: e.target.value }));
  const parcelValid = parcel.weight && parcel.length && parcel.width && parcel.height;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="font-semibold">Buy Label via EasyPost</h2>
            <p className="text-xs text-gray-500 mt-0.5">
              {step === "parcel" ? "Step 1 of 2 — Parcel dimensions" : "Step 2 of 2 — Select rate"}
            </p>
          </div>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>

        {step === "parcel" && (
          <>
            <div className="mb-4 p-3 bg-blue-50 rounded-lg text-xs text-blue-700">
              Covers <strong>{lineItemIds.length}</strong> item(s). Enter parcel dimensions for live carrier rates.
            </div>

            <AddressPreview
              from={supplierForPreview}
              to={orderForPreview?.shipping_address}
              missingFromAddr={supplierForPreview && !supplierForPreview.street1}
              missingToAddr={!orderForPreview?.shipping_address?.line1}
            />

            {estimateInfo && (
              <div className={`mb-3 p-2 rounded-lg text-xs ${
                estimateInfo.complete ? "bg-green-50 text-green-700" : "bg-amber-50 text-amber-700"
              }`}>
                {estimateInfo.complete
                  ? "✓ Auto-filled from catalog dimensions. Adjust if needed."
                  : `Partial auto-fill — ${estimateInfo.missing.length} item(s) missing dimensions. Edit any field below or set per-unit dimensions on the supplier catalog.`}
              </div>
            )}
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
            <div className="flex items-center justify-between mt-5">
              {showAmazonOption && onSwitchToAmazon ? (
                <button className="text-xs text-orange-600 hover:underline" onClick={onSwitchToAmazon}>
                  Use Amazon Buy Shipping instead →
                </button>
              ) : <span />}
              <div className="flex gap-2">
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
            </div>
          </>
        )}

        {step === "rates" && (
          <>
            <EasyPostDebugPanel
              debug={debug}
              showRaw={showRawDebug}
              onToggleRaw={() => setShowRawDebug((v) => !v)}
            />

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
                      name="ep-rate"
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

function AddressPreview({
  from,
  to,
  missingFromAddr,
  missingToAddr,
}: {
  from?: any;
  to?: any;
  missingFromAddr?: boolean;
  missingToAddr?: boolean;
}) {
  if (!from && !to) return null;
  const fromLines = from
    ? [
        from.name,
        [from.street1, from.street2].filter(Boolean).join(", "),
        [from.city, from.state, from.zipcode].filter(Boolean).join(", "),
        from.country,
        from.phone,
      ].filter(Boolean)
    : [];
  const toLines = to
    ? [
        to.name,
        [to.line1, to.line2].filter(Boolean).join(", "),
        [to.city, to.state, to.zip].filter(Boolean).join(", "),
        to.country,
        to.phone,
      ].filter(Boolean)
    : [];
  return (
    <div className="grid grid-cols-2 gap-2 mb-3">
      <div className={`p-2 rounded-lg text-xs border ${missingFromAddr ? "border-red-200 bg-red-50" : "border-gray-200 bg-gray-50"}`}>
        <div className="font-semibold text-gray-500 uppercase tracking-wide mb-1">Ship from (supplier)</div>
        {missingFromAddr ? (
          <div className="text-red-700">Supplier address incomplete — update the supplier profile before requesting rates.</div>
        ) : fromLines.length === 0 ? (
          <div className="text-gray-400">No supplier loaded</div>
        ) : fromLines.map((l, i) => <div key={i} className="text-gray-700">{l}</div>)}
      </div>
      <div className={`p-2 rounded-lg text-xs border ${missingToAddr ? "border-red-200 bg-red-50" : "border-gray-200 bg-gray-50"}`}>
        <div className="font-semibold text-gray-500 uppercase tracking-wide mb-1">Ship to (buyer)</div>
        {missingToAddr ? (
          <div className="text-red-700">Order has no shipping address.</div>
        ) : toLines.length === 0 ? (
          <div className="text-gray-400">No address</div>
        ) : toLines.map((l, i) => <div key={i} className="text-gray-700">{l}</div>)}
      </div>
    </div>
  );
}

function EasyPostDebugPanel({
  debug,
  showRaw,
  onToggleRaw,
}: {
  debug: any | null;
  showRaw: boolean;
  onToggleRaw: () => void;
}) {
  if (!debug) return null;
  const renderAddr = (a: any) => [
    a.name,
    [a.street1, a.street2].filter(Boolean).join(", "),
    [a.city, a.state, a.zip].filter(Boolean).join(", "),
    a.country,
    a.phone,
  ].filter(Boolean);
  return (
    <div className="mb-4 border border-gray-200 rounded-lg">
      <div className="p-3 border-b border-gray-100 bg-gray-50 rounded-t-lg">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-semibold text-gray-600 uppercase tracking-wide">EasyPost Request — Verify before paying</span>
          <button className="text-xs text-blue-600 hover:underline" onClick={onToggleRaw}>
            {showRaw ? "Hide raw JSON" : "Show raw JSON"}
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="bg-white p-2 rounded border border-gray-200">
            <div className="text-gray-500 mb-0.5">Ship from (supplier)</div>
            {renderAddr(debug.from_address).map((l, i) => <div key={i} className="text-gray-700">{l}</div>)}
          </div>
          <div className="bg-white p-2 rounded border border-gray-200">
            <div className="text-gray-500 mb-0.5">Ship to (buyer)</div>
            {renderAddr(debug.to_address).map((l, i) => <div key={i} className="text-gray-700">{l}</div>)}
          </div>
        </div>
        <div className="mt-2 bg-white p-2 rounded border border-gray-200 text-xs">
          <span className="text-gray-500">Parcel:</span>{" "}
          <span className="font-medium">{debug.parcel.weight} oz</span>{" · "}
          <span className="font-medium">{debug.parcel.length}×{debug.parcel.width}×{debug.parcel.height} in</span>
          <span className="ml-3 text-gray-500">Rates returned:</span>{" "}
          <span className="font-medium">{debug.total_rates} total</span>
          <span className="ml-3 text-gray-500">Line items:</span>{" "}
          <span className="font-mono">{(debug.line_item_ids || []).join(", ")}</span>
        </div>
      </div>
      {showRaw && (
        <pre className="text-[10px] leading-tight p-2 max-h-40 overflow-auto bg-gray-900 text-gray-100 rounded-b-lg font-mono">
{JSON.stringify(debug, null, 2)}
        </pre>
      )}
    </div>
  );
}
