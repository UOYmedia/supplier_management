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
  const [editingOrderInfo, setEditingOrderInfo] = useState(false);
  const [assigningItem, setAssigningItem] = useState<number | null>(null);
  const [autoOpenedForSupplier, setAutoOpenedForSupplier] = useState<number | null>(null);

  const { data: order } = useQuery({ queryKey: ["order", oid], queryFn: () => ordersApi.get(oid), throwOnError: false });
  const { data: labels = [] } = useQuery({ queryKey: ["labels", oid], queryFn: () => ordersApi.listLabels(oid), throwOnError: false });
  const { data: suppliers = [] } = useQuery({ queryKey: ["suppliers"], queryFn: () => suppliersApi.list(), throwOnError: false });

  const updateLIMut = useMutation({
    mutationFn: ({ liId, data }: { liId: number; data: object }) => ordersApi.updateLineItem(oid, liId, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["order", oid] }),
  });
  const assignSupplierMut = useMutation({
    mutationFn: ({ liId, data }: { liId: number; data: object }) => ordersApi.assignSupplier(oid, liId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["order", oid] });
      qc.invalidateQueries({ queryKey: ["suppliers"] });
    },
  });
  const quickAssignMut = useMutation({
    mutationFn: ({ liId, data }: { liId: number; data: object }) => ordersApi.assignSupplier(oid, liId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["order", oid] });
      qc.invalidateQueries({ queryKey: ["suppliers"] });
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "Failed to assign"),
  });
  const markShippedMut = useMutation({
    mutationFn: (data: object) => ordersApi.markShipped(oid, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["order", oid] });
      qc.invalidateQueries({ queryKey: ["labels", oid] });
      toast.success("Marked as shipped");
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "Failed to mark shipped"),
  });
  const syncTrackingMut = useMutation({
    mutationFn: () => ordersApi.syncTracking(oid),
    onSuccess: (data: any) => {
      qc.invalidateQueries({ queryKey: ["order", oid] });
      if (data?.skipped) {
        toast(data.skipped, { icon: "ℹ️" });
      } else if (data?.synced) {
        toast.success(`Tracking synced: ${data.tracking_number}`);
      } else if (data?.error) {
        const msg: string = data.error;
        if (msg.includes("re-authenticate") || msg.includes("401") || msg.includes("403")) {
          toast.error(
            (t) => (
              <span>
                {msg}{" "}
                <a
                  href="/settings"
                  onClick={() => toast.dismiss(t.id)}
                  className="underline font-medium"
                >
                  Go to Settings
                </a>
              </span>
            ),
            { duration: 8000 }
          );
        } else {
          toast.error(msg);
        }
      }
    },
    onError: (e: any) => toast.error(e?.response?.data?.detail || "Failed to sync tracking"),
  });

  // Auto-open label modal when ?label=supplierId is in URL
  useEffect(() => {
    if (!order) return;
    const labelSupplierId = searchParams.get("label");
    if (!labelSupplierId) return;
    const sid = parseInt(labelSupplierId);
    if (autoOpenedForSupplier === sid) return;
    const supplierLineItems = (order.line_items || []).filter((li: any) => li.supplier_id === sid);
    if (supplierLineItems.length === 0) return;
    setAutoOpenedForSupplier(sid);
    setShowLabel({ supplierId: sid, lineItemIds: supplierLineItems.map((li: any) => li.id) });
  }, [order, searchParams, autoOpenedForSupplier]);

  if (!order) return <div className="p-8 text-center text-gray-500">Loading...</div>;

  const isAmazonOrder = order.marketplace === "amazon";
  const supplierGroups: Record<number, { name: string; items: any[] }> = {};
  const unassignedItems: any[] = [];
  for (const li of order.line_items || []) {
    if (!li.supplier_id) { unassignedItems.push(li); continue; }
    if (!supplierGroups[li.supplier_id]) supplierGroups[li.supplier_id] = { name: li.supplier_name || `Supplier ${li.supplier_id}`, items: [] };
    supplierGroups[li.supplier_id].items.push(li);
  }

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <div className="flex items-center gap-3">
        <Link href="/orders" className="text-gray-400 hover:text-gray-600"><ArrowLeft className="w-5 h-5" /></Link>
        <h1 className="text-xl font-bold">Order #{order.external_order_id || order.id}</h1>
        <OrderStatusBadge status={order.status} />
        {isAmazonOrder && <span className="badge-orange">Amazon</span>}
      </div>

      {/* Order Info */}
      <div className="card p-4 space-y-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-gray-700">Order Info</h2>
          <button onClick={() => setEditingOrderInfo(true)} className="flex items-center gap-1 text-xs text-gray-500 hover:text-gray-800">
            <Pencil className="w-3 h-3" /> Edit
          </button>
        </div>
        <div className="grid grid-cols-2 gap-x-8 gap-y-1 text-sm">
          <div><span className="text-gray-500">Buyer:</span> {order.buyer_name || "—"}</div>
          <div><span className="text-gray-500">Email:</span> {order.buyer_email || "—"}</div>
          <div><span className="text-gray-500">Marketplace:</span> {order.marketplace}</div>
          <div><span className="text-gray-500">Total:</span> ${parseFloat(order.total).toFixed(2)} {order.currency}</div>
          <div><span className="text-gray-500">Ordered:</span> {new Date(order.ordered_at).toLocaleString()}</div>
          <div><span className="text-gray-500">Notes:</span> {order.notes || "—"}</div>
        </div>
        {order.shipping_address && (
          <div className="text-sm mt-1">
            <span className="text-gray-500">Ship to:</span>{" "}
            {[order.shipping_address.name, order.shipping_address.line1, order.shipping_address.city, order.shipping_address.state, order.shipping_address.country].filter(Boolean).join(", ")}
          </div>
        )}
      </div>

      {/* Unassigned Items */}
      {unassignedItems.length > 0 && (
        <div className="card p-4 space-y-3 border-amber-200">
          <div className="flex items-center gap-2">
            <UserPlus className="w-4 h-4 text-amber-500" />
            <h3 className="font-medium text-amber-700">Unassigned Items</h3>
            <span className="text-xs text-amber-500">({unassignedItems.length} item{unassignedItems.length > 1 ? "s" : ""} need a supplier)</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-500 border-b">
                  <th className="pb-2">Product</th>
                  <th className="pb-2">SKU</th>
                  <th className="pb-2">Qty</th>
                  <th className="pb-2">Cost</th>
                  <th className="pb-2">Status</th>
                  <th className="pb-2"></th>
                </tr>
              </thead>
              <tbody>
                {unassignedItems.map((li: any) => (
                  <LineItemRow
                    key={li.id}
                    li={li}
                    suppliers={suppliers}
                    onUpdate={(data) => updateLIMut.mutate({ liId: li.id, data })}
                    onAssignSupplier={() => setAssigningItem(li.id)}
                    onQuickAssign={(s) => quickAssignMut.mutate({
                      liId: li.id,
                      data: {
                        supplier_id: s.supplier_id,
                        supplier_product_id: s.supplier_product_id,
                        units: s.units,
                        create_product_supplier: true,
                      },
                    })}
                  />
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Supplier Groups */}
      {Object.entries(supplierGroups).map(([sid, group]) => {
        const supplierId = parseInt(sid);
        const supplierLineItemIds = group.items.map((li) => li.id);
        return (
          <div key={sid} className="card p-4 space-y-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Package className="w-4 h-4 text-gray-400" />
                <h3 className="font-medium">{group.name}</h3>
              </div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setShowLabel({ supplierId, lineItemIds: supplierLineItemIds })}
                  className="btn-secondary flex items-center gap-1 text-xs"
                >
                  <Tag className="w-3 h-3" /> Print Label
                </button>
                <button
                  onClick={() => setManualLabel({ supplierId, lineItemIds: supplierLineItemIds })}
                  className="btn-secondary flex items-center gap-1 text-xs"
                >
                  <Upload className="w-3 h-3" /> Manual Label
                </button>
                <button
                  onClick={() => markShippedMut.mutate({ supplier_id: supplierId, line_item_ids: supplierLineItemIds })}
                  className="btn-secondary flex items-center gap-1 text-xs"
                  disabled={markShippedMut.isPending}
                >
                  <Truck className="w-3 h-3" /> Mark Shipped
                </button>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-gray-500 border-b">
                    <th className="pb-2">Product</th>
                    <th className="pb-2">SKU</th>
                    <th className="pb-2">Qty</th>
                    <th className="pb-2">Cost</th>
                    <th className="pb-2">Status</th>
                    <th className="pb-2">Tracking</th>
                    <th className="pb-2"></th>
                  </tr>
                </thead>
                <tbody>
                  {(group.items as any[]).map((li: any) => (
                    <LineItemRow
                      key={li.id}
                      li={li}
                      suppliers={suppliers}
                      onUpdate={(data) => updateLIMut.mutate({ liId: li.id, data })}
                      onAssignSupplier={() => setAssigningItem(li.id)}
                      onQuickAssign={(s) => quickAssignMut.mutate({
                        liId: li.id,
                        data: {
                          supplier_id: s.supplier_id,
                          supplier_product_id: s.supplier_product_id,
                          units: s.units,
                          create_product_supplier: true,
                        },
                      })}
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
            qc.invalidateQueries({ queryKey: ["labels", oid] });
            setEditingLabel(null);
          }}
        />
      )}

      {editingOrderInfo && (
        <EditOrderInfoModal
          order={order}
          onClose={() => setEditingOrderInfo(false)}
          onDone={() => {
            qc.invalidateQueries({ queryKey: ["order", oid] });
            setEditingOrderInfo(false);
          }}
        />
      )}

      {/* Sync tracking */}
      <div className="flex justify-end">
        <button
          onClick={() => syncTrackingMut.mutate()}
          disabled={syncTrackingMut.isPending}
          className="btn-secondary flex items-center gap-1 text-xs"
        >
          {syncTrackingMut.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
          Sync tracking to {isAmazonOrder ? "Amazon" : "marketplace"}
        </button>
      </div>
    </div>
  );
}

function LineItemRow({ li, suppliers, onUpdate, onAssignSupplier, onQuickAssign }: {
  li: any;
  suppliers: any[];
  onUpdate: (data: object) => void;
  onAssignSupplier: () => void;
  onQuickAssign: (s: { supplier_id: number; supplier_product_id?: number; units?: number }) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [status, setStatus] = useState(li.fulfill_status);
  const [tracking, setTracking] = useState(li.tracking_number || "");
  const [cost, setCost] = useState(li.base_cost || "");
  const [showQuickAssign, setShowQuickAssign] = useState(false);

  const productSuppliers: any[] = li.product_suppliers || [];

  function save() {
    onUpdate({ fulfill_status: status, tracking_number: tracking || null, base_cost: cost || 0 });
    setEditing(false);
  }

  return (
    <tr className="border-b border-gray-50 last:border-0">
      <td className="py-2 pr-4">
        <div className="font-medium">{li.product_name}</div>
        {li.supplier_name && <div className="text-xs text-gray-400">{li.supplier_name}</div>}
      </td>
      <td className="py-2 pr-4 font-mono text-xs text-gray-500">{li.sku || "—"}</td>
      <td className="py-2 pr-4">{li.quantity}</td>
      <td className="py-2 pr-4">
        {editing ? (
          <input type="number" value={cost} onChange={(e) => setCost(e.target.value)} className="input-sm w-20" step="0.01" />
        ) : (
          <span>${parseFloat(li.base_cost || 0).toFixed(2)}</span>
        )}
      </td>
      <td className="py-2 pr-4">
        {editing ? (
          <select value={status} onChange={(e) => setStatus(e.target.value)} className="input-sm">
            {FULFILL_STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
        ) : (
          <span className={`badge-${
            li.fulfill_status === "shipped" ? "green" :
            li.fulfill_status === "unfulfilled" ? "gray" : "blue"
          }`}>{li.fulfill_status}</span>
        )}
      </td>
      <td className="py-2 pr-4">
        {editing ? (
          <input value={tracking} onChange={(e) => setTracking(e.target.value)} className="input-sm w-32" placeholder="Tracking #" />
        ) : (
          <span className="font-mono text-xs">{li.tracking_number || "—"}</span>
        )}
      </td>
      <td className="py-2">
        <div className="flex items-center gap-1 flex-wrap">
          {editing ? (
            <>
              <button onClick={save} className="btn-primary-xs"><CheckCircle2 className="w-3 h-3" /></button>
              <button onClick={() => setEditing(false)} className="btn-secondary-xs"><X className="w-3 h-3" /></button>
            </>
          ) : (
            <>
              <button onClick={() => setEditing(true)} className="btn-secondary-xs"><Pencil className="w-3 h-3" /></button>
              {!li.supplier_id ? (
                <div className="relative">
                  <button onClick={() => setShowQuickAssign(!showQuickAssign)} className="btn-secondary-xs flex items-center gap-1">
                    <UserPlus className="w-3 h-3" /> Assign
                  </button>
                  {showQuickAssign && (
                    <QuickAssignDropdown
                      lineItem={li}
                      productSuppliers={productSuppliers}
                      suppliers={suppliers}
                      onSelect={(s) => { onQuickAssign(s); setShowQuickAssign(false); }}
                      onManual={() => { onAssignSupplier(); setShowQuickAssign(false); }}
                      onClose={() => setShowQuickAssign(false)}
                    />
                  )}
                </div>
              ) : (
                <button onClick={onAssignSupplier} className="btn-secondary-xs flex items-center gap-1">
                  <UserPlus className="w-3 h-3" /> Reassign
                </button>
              )}
            </>
          )}
        </div>
      </td>
    </tr>
  );
}

function QuickAssignDropdown({ lineItem, productSuppliers, suppliers, onSelect, onManual, onClose }: {
  lineItem: any;
  productSuppliers: any[];
  suppliers: any[];
  onSelect: (s: { supplier_id: number; supplier_product_id?: number; units?: number }) => void;
  onManual: () => void;
  onClose: () => void;
}) {
  useEffect(() => {
    const handle = (e: MouseEvent) => {
      if (!(e.target as Element).closest(".quick-assign-dropdown")) onClose();
    };
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [onClose]);

  return (
    <div className="quick-assign-dropdown absolute right-0 top-6 z-20 bg-white border border-gray-200 rounded-lg shadow-lg min-w-48 py-1">
      {productSuppliers.length > 0 && (
        <>
          <div className="px-3 py-1 text-xs text-gray-400 font-medium">Known suppliers</div>
          {productSuppliers.map((ps: any) => (
            <button
              key={ps.supplier_id}
              className="w-full text-left px-3 py-2 text-sm hover:bg-gray-50"
              onClick={() => onSelect({ supplier_id: ps.supplier_id, supplier_product_id: ps.id, units: ps.units })}
            >
              {ps.supplier_name || `Supplier ${ps.supplier_id}`}
              {ps.cost ? ` — $${parseFloat(ps.cost).toFixed(2)}` : ""}
            </button>
          ))}
          <div className="border-t border-gray-100 my-1" />
        </>
      )}
      <button className="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 text-blue-600" onClick={onManual}>
        + Assign manually
      </button>
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
  const [carrier, setCarrier] = useState("USPS");
  const [service, setService] = useState("");
  const [tracking, setTracking] = useState("");
  const [cost, setCost] = useState("");
  const [labelFile, setLabelFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit() {
    setLoading(true);
    try {
      const formData = new FormData();
      formData.append("carrier", carrier);
      formData.append("service", service);
      formData.append("tracking_number", tracking);
      formData.append("cost", cost || "0");
      formData.append("supplier_id", String(supplierId));
      lineItemIds.forEach((id) => formData.append("line_item_ids", String(id)));
      if (labelFile) formData.append("label_file", labelFile);
      await ordersApi.createManualLabel(orderId, formData);
      onDone();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Failed to save label");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Manual Shipping Label</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Carrier</label>
            <select value={carrier} onChange={(e) => setCarrier(e.target.value)} className="input w-full">
              {["USPS", "UPS", "FedEx", "DHL", "Other"].map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Service (optional)</label>
            <input value={service} onChange={(e) => setService(e.target.value)} className="input w-full" placeholder="e.g. Priority Mail" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Tracking Number</label>
            <input value={tracking} onChange={(e) => setTracking(e.target.value)} className="input w-full" placeholder="Tracking #" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Cost ($)</label>
            <input type="number" value={cost} onChange={(e) => setCost(e.target.value)} className="input w-full" step="0.01" placeholder="0.00" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Label PDF (optional)</label>
            <input type="file" accept=".pdf,.png,.jpg" onChange={(e) => setLabelFile(e.target.files?.[0] || null)} className="text-sm" />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="btn-secondary">Cancel</button>
          <button onClick={submit} disabled={loading} className="btn-primary">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Save Label"}
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
  const [cost, setCost] = useState(label.cost || "");
  const [labelFile, setLabelFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit() {
    setLoading(true);
    try {
      if (labelFile) {
        const formData = new FormData();
        formData.append("carrier", carrier);
        formData.append("service", service);
        formData.append("tracking_number", tracking);
        formData.append("cost", cost || "0");
        formData.append("label_file", labelFile);
        await ordersApi.updateLabelWithFile(orderId, label.id, formData);
      } else {
        await ordersApi.updateLabel(orderId, label.id, { carrier, service, tracking_number: tracking, cost: parseFloat(cost) || 0 });
      }
      onDone();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Failed to update label");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Edit Label</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Carrier</label>
            <select value={carrier} onChange={(e) => setCarrier(e.target.value)} className="input w-full">
              {["USPS", "UPS", "FedEx", "DHL", "Other"].map((c) => <option key={c}>{c}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Service (optional)</label>
            <input value={service} onChange={(e) => setService(e.target.value)} className="input w-full" placeholder="e.g. Priority Mail" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Tracking Number</label>
            <input value={tracking} onChange={(e) => setTracking(e.target.value)} className="input w-full" placeholder="Tracking #" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Cost ($)</label>
            <input type="number" value={cost} onChange={(e) => setCost(e.target.value)} className="input w-full" step="0.01" placeholder="0.00" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Replace Label PDF (optional)</label>
            <input type="file" accept=".pdf,.png,.jpg" onChange={(e) => setLabelFile(e.target.files?.[0] || null)} className="text-sm" />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="btn-secondary">Cancel</button>
          <button onClick={submit} disabled={loading} className="btn-primary">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

function EditOrderInfoModal({ order, onClose, onDone }: {
  order: any;
  onClose: () => void;
  onDone: () => void;
}) {
  const [buyerName, setBuyerName] = useState(order.buyer_name || "");
  const [buyerEmail, setBuyerEmail] = useState(order.buyer_email || "");
  const [notes, setNotes] = useState(order.notes || "");
  const [addr, setAddr] = useState(order.shipping_address || {});
  const [loading, setLoading] = useState(false);

  async function submit() {
    setLoading(true);
    try {
      await ordersApi.update(order.id, {
        buyer_name: buyerName || null,
        buyer_email: buyerEmail || null,
        notes: notes || null,
        shipping_address: addr,
      });
      onDone();
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Failed to update order");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Edit Order Info</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Buyer Name</label>
            <input value={buyerName} onChange={(e) => setBuyerName(e.target.value)} className="input w-full" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Buyer Email</label>
            <input value={buyerEmail} onChange={(e) => setBuyerEmail(e.target.value)} className="input w-full" />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Notes</label>
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} className="input w-full" rows={3} />
          </div>
          <div className="border-t pt-3">
            <div className="text-xs font-medium text-gray-600 mb-2">Shipping Address</div>
            <div className="grid grid-cols-2 gap-2">
              {(["name", "line1", "line2", "city", "state", "zip", "country", "phone"] as const).map((field) => (
                <div key={field}>
                  <label className="block text-xs text-gray-400 mb-0.5 capitalize">{field}</label>
                  <input
                    value={addr[field] || ""}
                    onChange={(e) => setAddr({ ...addr, [field]: e.target.value })}
                    className="input w-full text-sm"
                  />
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="btn-secondary">Cancel</button>
          <button onClick={submit} disabled={loading} className="btn-primary">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Save"}
          </button>
        </div>
      </div>
    </div>
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
  const [baseCost, setBaseCost] = useState("");
  const [createMapping, setCreateMapping] = useState(true);
  const [isPreferred, setIsPreferred] = useState(false);

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl p-6 w-full max-w-md shadow-xl">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Assign Supplier</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <p className="text-sm text-gray-600 mb-4">{lineItem?.product_name} (qty: {lineItem?.quantity})</p>
        <div className="space-y-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Supplier</label>
            <select value={supplierId} onChange={(e) => setSupplierId(e.target.value)} className="input w-full">
              <option value="">Select supplier...</option>
              {suppliers.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">Base Cost ($)</label>
            <input type="number" value={baseCost} onChange={(e) => setBaseCost(e.target.value)} className="input w-full" step="0.01" />
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={createMapping} onChange={(e) => setCreateMapping(e.target.checked)} />
            Save as product-supplier mapping
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={isPreferred} onChange={(e) => setIsPreferred(e.target.checked)} />
            Mark as preferred supplier
          </label>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button onClick={onClose} className="btn-secondary">Cancel</button>
          <button
            onClick={() => supplierId && onAssign({ supplier_id: parseInt(supplierId), base_cost: baseCost || null, create_product_supplier: createMapping, is_preferred: isPreferred })}
            disabled={!supplierId || loading}
            className="btn-primary"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Assign"}
          </button>
        </div>
      </div>
    </div>
  );
}

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
  const [loading, setLoading] = useState(false);
  const [rates, setRates] = useState<any[]>([]);
  const [selectedService, setSelectedService] = useState<any>(null);
  const [services, setServices] = useState<any[]>([]);
  const [step, setStep] = useState<"rates" | "confirm" | "done">("rates");
  const [debug, setDebug] = useState<any>(null);
  const [showRaw, setShowRaw] = useState(false);
  const [buyLabel, setBuyLabel] = useState(false);
  const [result, setResult] = useState<any>(null);

  useEffect(() => {
    fetchRates();
  }, []);

  async function fetchRates() {
    setLoading(true);
    try {
      const data = await amazonShippingApi.getRates({
        order_id: orderId,
        supplier_id: supplierId,
        line_item_ids: lineItemIds,
      });
      setServices(data.eligible_shipping_services || []);
      setRates(data.eligible_shipping_services || []);
      setDebug(data.debug || null);
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Failed to get rates");
    } finally {
      setLoading(false);
    }
  }

  async function confirmLabel() {
    if (!selectedService) return;
    setLoading(true);
    try {
      const data = await amazonShippingApi.createLabel({
        order_id: orderId,
        supplier_id: supplierId,
        line_item_ids: lineItemIds,
        shipping_service_id: selectedService.shipping_service_id,
        shipping_service_name: selectedService.shipping_service_name,
        carrier_name: selectedService.carrier_name,
        buy_label: buyLabel,
      });
      setResult(data);
      setStep("done");
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Failed to create label");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl p-6 w-full max-w-2xl shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Amazon Shipping Label</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>

        {step === "rates" && (
          <>
            {debug && (
              <ShipmentDebugPanel debug={debug} showRaw={showRaw} onToggleRaw={() => setShowRaw(!showRaw)} />
            )}
            {loading && <div className="text-center py-8"><Loader2 className="w-8 h-8 animate-spin mx-auto text-gray-400" /></div>}
            {!loading && services.length === 0 && (
              <div className="text-center py-8 text-gray-500">
                <p>No shipping services available.</p>
                <button className="text-xs text-blue-600 hover:underline mt-2" onClick={onSwitchToEasyPost}>Try EasyPost instead</button>
              </div>
            )}
            {!loading && services.length > 0 && (
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
                    <div className="flex-1">
                      <div className="text-sm font-medium">{s.shipping_service_name}</div>
                      <div className="text-xs text-gray-500">{s.carrier_name} · {s.earliest_estimated_delivery_date ? new Date(s.earliest_estimated_delivery_date).toLocaleDateString() : ""}</div>
                    </div>
                    <div className="text-sm font-semibold">${parseFloat(s.rate?.amount || 0).toFixed(2)}</div>
                  </label>
                ))}
              </div>
            )}
            {!loading && (
              <div className="mt-4 flex items-center justify-between">
                <button className="text-xs text-blue-600 hover:underline" onClick={onSwitchToEasyPost}>
                  Use EasyPost instead
                </button>
                <button
                  disabled={!selectedService}
                  onClick={() => setStep("confirm")}
                  className="btn-primary"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}

        {step === "confirm" && selectedService && (
          <>
            <div className="bg-orange-50 border border-orange-200 rounded-lg p-4 mb-4">
              <div className="text-sm font-medium mb-1">{selectedService.shipping_service_name}</div>
              <div className="text-xs text-gray-500">{selectedService.carrier_name}</div>
              <div className="text-lg font-bold mt-2">${parseFloat(selectedService.rate?.amount || 0).toFixed(2)}</div>
            </div>
            <label className="flex items-center gap-2 text-sm mb-4">
              <input type="checkbox" checked={buyLabel} onChange={(e) => setBuyLabel(e.target.checked)} />
              Purchase label now (charges your Amazon account)
            </label>
            <div className="flex justify-between">
              <button onClick={() => setStep("rates")} className="btn-secondary">Back</button>
              <button onClick={confirmLabel} disabled={loading} className="btn-primary">
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : buyLabel ? "Buy & Create Label" : "Confirm Shipment"}
              </button>
            </div>
          </>
        )}

        {step === "done" && result && (
          <div className="text-center py-6">
            <CheckCircle2 className="w-12 h-12 text-green-500 mx-auto mb-3" />
            <p className="font-medium mb-1">Shipment confirmed!</p>
            {result.tracking_number && (
              <p className="text-sm text-gray-600">Tracking: <span className="font-mono">{result.tracking_number}</span></p>
            )}
            {result.label_url && (
              <a href={result.label_url} target="_blank" className="btn-primary mt-4 inline-flex items-center gap-1">
                <Printer className="w-4 h-4" /> Print Label
              </a>
            )}
            <button onClick={onClose} className="btn-secondary mt-2 ml-2">Close</button>
          </div>
        )}
      </div>
    </div>
  );
}

function EasyPostLabelModal({ orderId, supplierId, lineItemIds, showAmazonOption, onClose, onSwitchToAmazon }: {
  orderId: number;
  supplierId: number;
  lineItemIds: number[];
  showAmazonOption?: boolean;
  onClose: () => void;
  onSwitchToAmazon?: () => void;
}) {
  const [step, setStep] = useState<"rates" | "confirm" | "done">("rates");
  const [rates, setRates] = useState<any[]>([]);
  const [selectedRate, setSelectedRate] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [debug, setDebug] = useState<any>(null);
  const [showRaw, setShowRaw] = useState(false);

  useEffect(() => {
    fetchRates();
  }, []);

  async function fetchRates() {
    setLoading(true);
    try {
      const data = await easypostApi.getRates({ order_id: orderId, supplier_id: supplierId, line_item_ids: lineItemIds });
      setRates(data.rates || []);
      setDebug(data.debug || null);
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Failed to get rates");
    } finally {
      setLoading(false);
    }
  }

  async function buyLabel() {
    if (!selectedRate) return;
    setLoading(true);
    try {
      const data = await easypostApi.buyLabel({ order_id: orderId, supplier_id: supplierId, line_item_ids: lineItemIds, rate_id: selectedRate.id });
      setResult(data);
      setStep("done");
    } catch (e: any) {
      toast.error(e?.response?.data?.detail || "Failed to buy label");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl p-6 w-full max-w-2xl shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">EasyPost Shipping Label</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        {step === "rates" && (
          <>
            {debug && (
              <ShipmentDebugPanel debug={debug} showRaw={showRaw} onToggleRaw={() => setShowRaw(!showRaw)} />
            )}
            {loading && <div className="text-center py-8"><Loader2 className="w-8 h-8 animate-spin mx-auto text-gray-400" /></div>}
            {!loading && rates.length === 0 && (
              <div className="text-center py-8 text-gray-500">
                <p>No rates found. Check supplier address and parcel dimensions.</p>
                {showAmazonOption && onSwitchToAmazon && (
                  <button className="text-xs text-blue-600 hover:underline mt-2" onClick={onSwitchToAmazon}>Try Amazon shipping instead</button>
                )}
              </div>
            )}
            {!loading && rates.length > 0 && (
              <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
                {rates.map((r) => (
                  <label
                    key={r.id}
                    className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                      selectedRate?.id === r.id ? "border-blue-500 bg-blue-50" : "border-gray-200 hover:border-gray-300"
                    }`}
                  >
                    <input type="radio" name="rate" checked={selectedRate?.id === r.id} onChange={() => setSelectedRate(r)} className="accent-blue-500" />
                    <div className="flex-1">
                      <div className="text-sm font-medium">{r.carrier} {r.service}</div>
                      <div className="text-xs text-gray-500">{r.delivery_days ? `${r.delivery_days}d` : ""}</div>
                    </div>
                    <div className="text-sm font-semibold">${parseFloat(r.rate).toFixed(2)}</div>
                  </label>
                ))}
              </div>
            )}
            {!loading && (
              <div className="mt-4 flex items-center justify-between">
                <div>
                  {showAmazonOption && onSwitchToAmazon && (
                    <button className="text-xs text-blue-600 hover:underline" onClick={onSwitchToAmazon}>Use Amazon shipping instead</button>
                  )}
                </div>
                <button disabled={!selectedRate} onClick={() => setStep("confirm")} className="btn-primary">Next</button>
              </div>
            )}
          </>
        )}
        {step === "confirm" && selectedRate && (
          <>
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-4">
              <div className="text-sm font-medium">{selectedRate.carrier} {selectedRate.service}</div>
              <div className="text-lg font-bold mt-1">${parseFloat(selectedRate.rate).toFixed(2)}</div>
              {selectedRate.delivery_days && <div className="text-xs text-gray-500">{selectedRate.delivery_days} business days</div>}
            </div>
            <div className="flex justify-between">
              <button onClick={() => setStep("rates")} className="btn-secondary">Back</button>
              <button onClick={buyLabel} disabled={loading} className="btn-primary">
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : "Buy Label"}
              </button>
            </div>
          </>
        )}
        {step === "done" && result && (
          <div className="text-center py-6">
            <CheckCircle2 className="w-12 h-12 text-green-500 mx-auto mb-3" />
            <p className="font-medium mb-2">Label purchased!</p>
            {result.tracking_number && <p className="text-sm text-gray-600 mb-3">Tracking: <span className="font-mono">{result.tracking_number}</span></p>}
            <div className="flex justify-center gap-2">
              {result.label_url && (
                <a href={result.label_url} target="_blank" className="btn-primary flex items-center gap-1">
                  <Printer className="w-4 h-4" /> Print Label
                </a>
              )}
              <button onClick={onClose} className="btn-secondary">Close</button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ShipmentDebugPanel({ debug, showRaw, onToggleRaw }: { debug: any; showRaw: boolean; onToggleRaw: () => void }) {
  function renderAddr(a: any) {
    if (!a) return [];
    return [
      a.name,
      [a.street1, a.street2].filter(Boolean).join(", "),
      [a.city, a.state, a.zip].filter(Boolean).join(", "),
      a.country,
      a.phone,
    ].filter(Boolean);
  }
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
