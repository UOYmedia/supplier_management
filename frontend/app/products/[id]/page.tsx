"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { productsApi, suppliersApi, marketplaceApi } from "@/lib/api";
import { useParams, useRouter } from "next/navigation";
import toast from "react-hot-toast";
import { ArrowLeft, Plus, Trash2, Send, X, Pencil } from "lucide-react";
import Link from "next/link";

export default function ProductDetailPage() {
  const { id } = useParams<{ id: string }>();
  const pid = parseInt(id);
  const qc = useQueryClient();
  const router = useRouter();
  const [tab, setTab] = useState<"info" | "suppliers" | "components" | "listings">("info");
  const [showAddSupplier, setShowAddSupplier] = useState(false);
  const [showPush, setShowPush] = useState(false);
  const [showAddComponent, setShowAddComponent] = useState(false);
  const [editingComponent, setEditingComponent] = useState<any>(null);

  const { data: product } = useQuery({ queryKey: ["product", pid], queryFn: () => productsApi.get(pid) });
  const { data: psItems = [] } = useQuery({ queryKey: ["product-suppliers", pid], queryFn: () => productsApi.listSuppliers(pid) });
  const { data: components = [] } = useQuery({ queryKey: ["product-components", pid], queryFn: () => productsApi.listComponents(pid) });
  const { data: listings = [] } = useQuery({ queryKey: ["listings", { product_id: pid }], queryFn: () => marketplaceApi.listListings({ product_id: pid }) });
  const { data: connections = [] } = useQuery({ queryKey: ["connections"], queryFn: marketplaceApi.listConnections });
  const { data: suppliers = [] } = useQuery({ queryKey: ["suppliers"], queryFn: () => suppliersApi.list() });

  const removeSupMut = useMutation({
    mutationFn: (psId: number) => productsApi.removeSupplier(pid, psId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["product-suppliers", pid] }); toast.success("Removed"); },
  });

  const removeCompMut = useMutation({
    mutationFn: (compId: number) => productsApi.removeComponent(pid, compId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["product-components", pid] }); toast.success("Component removed"); },
  });

  if (!product) return <div className="p-6 text-gray-400">Loading…</div>;

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <Link href="/products" className="p-2 hover:bg-gray-100 rounded-lg text-gray-500">
          <ArrowLeft className="w-4 h-4" />
        </Link>
        <h1 className="page-title">{product.name}</h1>
        <span className="text-gray-400 font-mono text-sm">{product.sku}</span>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-5 border-b border-gray-200">
        {(["info", "suppliers", "components", "listings"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium capitalize border-b-2 transition-colors ${tab === t ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
            {t === "components" ? `Components (${components.length})` : t}
          </button>
        ))}
      </div>

      {tab === "info" && (
        <div className="card p-6 max-w-lg">
          <div className="grid grid-cols-2 gap-4 text-sm">
            <Field label="Base Cost" value={`$${parseFloat(product.base_cost).toFixed(2)}`} />
            <Field label="Status" value={product.is_active ? "Active" : "Inactive"} />
            <Field label="Weight" value={product.weight ? `${product.weight} kg` : "—"} />
            <Field label="Dimensions (L×W×H)" value={
              product.length ? `${product.length}×${product.width}×${product.height} cm` : "—"
            } />
            <div className="col-span-2">
              <Field label="Description" value={product.description || "—"} />
            </div>
          </div>
        </div>
      )}

      {tab === "suppliers" && (
        <div>
          <div className="flex justify-end mb-3">
            <button className="btn-primary" onClick={() => setShowAddSupplier(true)}>
              <Plus className="w-4 h-4" /> Add Supplier
            </button>
          </div>
          <div className="card table-wrapper">
            <table>
              <thead><tr>
                <th>Supplier</th><th>Supplier SKU</th><th>Cost</th><th>Stock</th><th>Lead (days)</th><th>Preferred</th><th></th>
              </tr></thead>
              <tbody>
                {psItems.length === 0 ? (
                  <tr><td colSpan={7} className="text-center py-6 text-gray-400">No suppliers assigned.</td></tr>
                ) : psItems.map((ps: any) => (
                  <tr key={ps.id}>
                    <td className="font-medium">{ps.supplier_name || ps.supplier_id}</td>
                    <td className="font-mono text-xs text-gray-500">{ps.supplier_sku || "—"}</td>
                    <td>${parseFloat(ps.cost).toFixed(2)}</td>
                    <td>{ps.stock}</td>
                    <td>{ps.lead_time_days}</td>
                    <td>{ps.is_preferred ? <span className="badge-green">Yes</span> : "—"}</td>
                    <td>
                      <button className="p-1 hover:text-red-500 text-gray-400" onClick={() => removeSupMut.mutate(ps.id)}>
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "components" && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <div className="text-sm text-gray-500">
              Link this product to supplier inventory items. When an order is placed, fulfillment will be auto-assigned per component.
            </div>
            <button className="btn-primary" onClick={() => setShowAddComponent(true)}>
              <Plus className="w-4 h-4" /> Add Component
            </button>
          </div>

          {/* Component type badges */}
          {components.length > 1 && (
            <div className="mb-3 flex gap-2">
              {components.some((c: any) => c.quantity > 1) && (
                <span className="badge-blue">Set / Pack</span>
              )}
              {new Set(components.map((c: any) => c.supplier_id)).size > 1 && (
                <span className="badge-yellow">Combo (multi-supplier)</span>
              )}
            </div>
          )}

          <div className="card table-wrapper">
            <table>
              <thead><tr>
                <th>Supplier</th><th>Supplier Product</th><th>SKU</th><th>Unit Price</th><th>Qty / shop unit</th><th></th>
              </tr></thead>
              <tbody>
                {components.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="text-center py-8 text-gray-400">
                      No components linked.<br />
                      <span className="text-xs">Add supplier products to enable automatic fulfillment assignment.</span>
                    </td>
                  </tr>
                ) : components.map((comp: any) => (
                  <tr key={comp.id}>
                    <td>
                      <Link href={`/suppliers/${comp.supplier_id}`} className="text-blue-600 hover:underline font-medium">
                        {comp.supplier_name || comp.supplier_id}
                      </Link>
                    </td>
                    <td className="font-medium">{comp.supplier_product_name}</td>
                    <td className="font-mono text-xs text-gray-500">{comp.supplier_product_sku}</td>
                    <td>${parseFloat(comp.unit_price || 0).toFixed(2)}</td>
                    <td>
                      <span className="inline-flex items-center gap-1">
                        <span className="font-semibold text-blue-700">×{comp.quantity}</span>
                        <button
                          className="p-0.5 hover:text-blue-600 text-gray-400"
                          onClick={() => setEditingComponent(comp)}
                        >
                          <Pencil className="w-3.5 h-3.5" />
                        </button>
                      </span>
                    </td>
                    <td>
                      <button
                        className="p-1 hover:text-red-500 text-gray-400"
                        onClick={() => { if (confirm("Remove component?")) removeCompMut.mutate(comp.id); }}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "listings" && (
        <div>
          <div className="flex justify-end mb-3">
            <button className="btn-primary" onClick={() => setShowPush(true)}>
              <Send className="w-4 h-4" /> Push to Marketplace
            </button>
          </div>
          <div className="card table-wrapper">
            <table>
              <thead><tr>
                <th>Marketplace</th><th>External ID</th><th>SKU</th><th>Price</th><th>Status</th><th>Synced</th>
              </tr></thead>
              <tbody>
                {listings.length === 0 ? (
                  <tr><td colSpan={6} className="text-center py-6 text-gray-400">No listings yet.</td></tr>
                ) : listings.map((l: any) => (
                  <tr key={l.id}>
                    <td className="capitalize">{connections.find((c: any) => c.id === l.connection_id)?.marketplace || l.connection_id}</td>
                    <td className="font-mono text-xs">{l.external_id || "—"}</td>
                    <td className="font-mono text-xs">{l.marketplace_sku || "—"}</td>
                    <td>{l.price ? `$${l.price}` : "—"}</td>
                    <td><StatusBadge status={l.status} /></td>
                    <td className="text-xs text-gray-500">{l.synced_at ? new Date(l.synced_at).toLocaleDateString() : "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showAddSupplier && (
        <AddSupplierModal productId={pid} suppliers={suppliers} onClose={() => setShowAddSupplier(false)} />
      )}
      {showPush && (
        <PushModal productId={pid} connections={connections} onClose={() => setShowPush(false)} />
      )}
      {showAddComponent && (
        <AddComponentModal productId={pid} onClose={() => setShowAddComponent(false)} />
      )}
      {editingComponent && (
        <EditComponentModal
          productId={pid}
          component={editingComponent}
          onClose={() => setEditingComponent(null)}
        />
      )}
    </div>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-gray-500 mb-0.5">{label}</div>
      <div className="font-medium">{value}</div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    active: "badge-green", draft: "badge-gray", error: "badge-red", syncing: "badge-yellow",
  };
  return <span className={map[status] || "badge-gray"}>{status}</span>;
}

function AddComponentModal({ productId, onClose }: { productId: number; onClose: () => void }) {
  const qc = useQueryClient();
  const [selectedSupplierId, setSelectedSupplierId] = useState("");
  const [selectedSpId, setSelectedSpId] = useState("");
  const [quantity, setQuantity] = useState("1");

  const { data: suppliers = [] } = useQuery({ queryKey: ["suppliers"], queryFn: () => suppliersApi.list() });
  const { data: supplierProducts = [] } = useQuery({
    queryKey: ["supplier-catalog", selectedSupplierId],
    queryFn: () => suppliersApi.listProducts(parseInt(selectedSupplierId)),
    enabled: !!selectedSupplierId,
  });

  const mut = useMutation({
    mutationFn: (data: object) => productsApi.addComponent(productId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["product-components", productId] });
      toast.success("Component added");
      onClose();
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Add Component</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <div className="text-xs text-gray-500 mb-4 p-3 bg-gray-50 rounded-lg">
          Select which supplier product makes up this shop product. Set quantity &gt; 1 for sets/packs, or add multiple components for combos.
        </div>
        <div className="space-y-3">
          <div>
            <label className="label">Supplier *</label>
            <select className="input" value={selectedSupplierId} onChange={(e) => { setSelectedSupplierId(e.target.value); setSelectedSpId(""); }}>
              <option value="">Select supplier…</option>
              {suppliers.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Supplier Product *</label>
            <select className="input" value={selectedSpId} onChange={(e) => setSelectedSpId(e.target.value)} disabled={!selectedSupplierId}>
              <option value="">
                {!selectedSupplierId ? "Select supplier first" : supplierProducts.length === 0 ? "No products in catalog" : "Select product…"}
              </option>
              {supplierProducts.map((sp: any) => (
                <option key={sp.id} value={sp.id}>{sp.name} ({sp.sku}) — ${parseFloat(sp.unit_price).toFixed(2)}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="label">Quantity per shop unit *</label>
            <input
              className="input"
              type="number"
              min="1"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
            />
            <p className="text-xs text-gray-400 mt-1">e.g. 6 for a 6-pack; 1 for single items</p>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button
            className="btn-primary"
            disabled={!selectedSpId || !quantity || mut.isPending}
            onClick={() => mut.mutate({ supplier_product_id: parseInt(selectedSpId), quantity: parseInt(quantity) })}
          >
            Add Component
          </button>
        </div>
      </div>
    </div>
  );
}

function EditComponentModal({ productId, component, onClose }: { productId: number; component: any; onClose: () => void }) {
  const qc = useQueryClient();
  const [quantity, setQuantity] = useState(String(component.quantity));
  const mut = useMutation({
    mutationFn: (data: object) => productsApi.updateComponent(productId, component.id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["product-components", productId] });
      toast.success("Updated");
      onClose();
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-sm p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Edit Quantity</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <p className="text-sm text-gray-600 mb-3">
          <strong>{component.supplier_product_name}</strong> ({component.supplier_product_sku})
        </p>
        <div>
          <label className="label">Quantity per shop unit</label>
          <input className="input" type="number" min="1" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={mut.isPending} onClick={() => mut.mutate({ quantity: parseInt(quantity) })}>Save</button>
        </div>
      </div>
    </div>
  );
}

function AddSupplierModal({ productId, suppliers, onClose }: { productId: number; suppliers: any[]; onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ supplier_id: "", supplier_sku: "", cost: "0", stock: "0", lead_time_days: "0", is_preferred: false });
  const [selectedSpId, setSelectedSpId] = useState<number | null>(null);
  const [units, setUnits] = useState("1");
  const [spQuery, setSpQuery] = useState("");

  const { data: catalog = [] } = useQuery({
    queryKey: ["supplier-catalog", form.supplier_id],
    queryFn: () => suppliersApi.listProducts(parseInt(form.supplier_id)),
    enabled: !!form.supplier_id,
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
    setForm((p) => ({
      ...p,
      supplier_sku: sp.sku,
      cost: (parseFloat(sp.unit_price) * u).toFixed(2),
      stock: String(sp.stock_quantity),
    }));
    setSpQuery("");
  };

  const onUnitsChange = (e: any) => {
    const v = e.target.value;
    setUnits(v);
    if (selectedSp) {
      const u = Math.max(1, parseInt(v) || 1);
      setForm((p) => ({ ...p, cost: (parseFloat(selectedSp.unit_price) * u).toFixed(2) }));
    }
  };

  const clearSp = () => {
    setSelectedSpId(null);
    setUnits("1");
  };

  const onSupplierChange = (e: any) => {
    setForm((p) => ({ ...p, supplier_id: e.target.value }));
    setSelectedSpId(null);
    setSpQuery("");
  };

  const mut = useMutation({
    mutationFn: (data: object) => productsApi.addSupplier(productId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["product-suppliers", productId] });
      qc.invalidateQueries({ queryKey: ["product-components", productId] });
      toast.success(selectedSpId ? "Supplier + component linked" : "Supplier added");
      onClose();
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  const f = (k: string) => (e: any) => setForm((p) => ({ ...p, [k]: e.target.value }));

  const submit = () => {
    const payload: any = {
      supplier_id: parseInt(form.supplier_id),
      supplier_sku: form.supplier_sku,
      cost: parseFloat(form.cost) || 0,
      stock: parseInt(form.stock) || 0,
      lead_time_days: parseInt(form.lead_time_days) || 0,
      is_preferred: form.is_preferred,
    };
    if (selectedSpId) {
      payload.supplier_product_id = selectedSpId;
      payload.units = Math.max(1, parseInt(units) || 1);
    }
    mut.mutate(payload);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Add Supplier</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="label">Supplier *</label>
            <select className="input" value={form.supplier_id} onChange={onSupplierChange}>
              <option value="">Select…</option>
              {suppliers.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>

          {form.supplier_id && (
            <div>
              <label className="label">Catalog Item {catalog.length > 0 && <span className="text-gray-400 font-normal">({catalog.length} available)</span>}</label>
              {selectedSp ? (
                <div className="flex items-center justify-between gap-2 p-2 rounded-lg border border-blue-200 bg-blue-50">
                  <div className="min-w-0">
                    <div className="font-medium text-sm truncate">{selectedSp.name}</div>
                    <div className="text-xs text-gray-500 font-mono">{selectedSp.sku} · ${parseFloat(selectedSp.unit_price).toFixed(2)} · stock {selectedSp.stock_quantity}</div>
                  </div>
                  <button className="text-xs text-gray-500 hover:text-red-500" onClick={clearSp}>Change</button>
                </div>
              ) : catalog.length === 0 ? (
                <p className="text-xs text-gray-400">Supplier has no catalog items. Fields below are entered manually.</p>
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
                  <p className="text-xs text-gray-400 mt-1">Pick to auto-fill SKU/cost/stock and enable supplier-side auto-fulfillment.</p>
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
                Set &gt; 1 for sets/combos. Cost auto-updates to ${parseFloat(selectedSp.unit_price).toFixed(2)} × {units || 1} = <strong>${(parseFloat(selectedSp.unit_price) * (parseInt(units) || 1)).toFixed(2)}</strong>. Each order of 1 shop unit deducts {units || 1} × order qty from supplier stock.
              </p>
            </div>
          )}

          <div><label className="label">Supplier SKU</label><input className="input" value={form.supplier_sku} onChange={f("supplier_sku")} /></div>
          <div><label className="label">Cost ($)</label><input className="input" type="number" step="0.01" value={form.cost} onChange={f("cost")} /></div>
          <div><label className="label">Initial Stock</label><input className="input" type="number" value={form.stock} onChange={f("stock")} /></div>
          <div><label className="label">Lead Time (days)</label><input className="input" type="number" value={form.lead_time_days} onChange={f("lead_time_days")} /></div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.is_preferred} onChange={(e) => setForm((p) => ({ ...p, is_preferred: e.target.checked }))} />
            Preferred supplier
          </label>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={!form.supplier_id || mut.isPending} onClick={submit}>Add</button>
        </div>
      </div>
    </div>
  );
}

function PushModal({ productId, connections, onClose }: { productId: number; connections: any[]; onClose: () => void }) {
  const [connId, setConnId] = useState("");
  const [price, setPrice] = useState("");
  const mut = useMutation({
    mutationFn: () => marketplaceApi.push({ product_ids: [productId], connection_id: parseInt(connId), price: price ? parseFloat(price) : undefined }),
    onSuccess: (data) => { toast.success(`Pushed: ${data.success} success, ${data.failed} failed`); onClose(); },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-sm p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Push to Marketplace</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="label">Connection *</label>
            <select className="input" value={connId} onChange={(e) => setConnId(e.target.value)}>
              <option value="">Select…</option>
              {connections.map((c: any) => <option key={c.id} value={c.id}>{c.name} ({c.marketplace})</option>)}
            </select>
          </div>
          <div><label className="label">Listing Price ($)</label><input className="input" type="number" step="0.01" value={price} onChange={(e) => setPrice(e.target.value)} /></div>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={!connId} onClick={() => mut.mutate()}>Push</button>
        </div>
      </div>
    </div>
  );
}
