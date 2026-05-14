"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { productsApi, suppliersApi, marketplaceApi } from "@/lib/api";
import { useParams, useRouter } from "next/navigation";
import toast from "react-hot-toast";
import { ArrowLeft, Plus, Trash2, Send, X } from "lucide-react";
import Link from "next/link";

export default function ProductDetailPage() {
  const { id } = useParams<{ id: string }>();
  const pid = parseInt(id);
  const qc = useQueryClient();
  const router = useRouter();
  const [tab, setTab] = useState<"info" | "suppliers" | "listings">("info");
  const [showAddSupplier, setShowAddSupplier] = useState(false);
  const [showPush, setShowPush] = useState(false);

  const { data: product } = useQuery({ queryKey: ["product", pid], queryFn: () => productsApi.get(pid) });
  const { data: psItems = [] } = useQuery({ queryKey: ["product-suppliers", pid], queryFn: () => productsApi.listSuppliers(pid) });
  const { data: listings = [] } = useQuery({ queryKey: ["listings", { product_id: pid }], queryFn: () => marketplaceApi.listListings({ product_id: pid }) });
  const { data: connections = [] } = useQuery({ queryKey: ["connections"], queryFn: marketplaceApi.listConnections });
  const { data: suppliers = [] } = useQuery({ queryKey: ["suppliers"], queryFn: () => suppliersApi.list() });

  const removeSupMut = useMutation({
    mutationFn: (psId: number) => productsApi.removeSupplier(pid, psId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["product-suppliers", pid] }); toast.success("Removed"); },
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
        {(["info", "suppliers", "listings"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium capitalize border-b-2 transition-colors ${tab === t ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
            {t}
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
        <AddSupplierModal
          productId={pid}
          suppliers={suppliers}
          onClose={() => setShowAddSupplier(false)}
        />
      )}
      {showPush && (
        <PushModal productId={pid} connections={connections} onClose={() => setShowPush(false)} />
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

function AddSupplierModal({ productId, suppliers, onClose }: { productId: number; suppliers: any[]; onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({ supplier_id: "", supplier_sku: "", cost: "0", stock: "0", lead_time_days: "0", is_preferred: false });
  const mut = useMutation({
    mutationFn: (data: object) => productsApi.addSupplier(productId, data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["product-suppliers", productId] }); toast.success("Supplier added"); onClose(); },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });
  const f = (k: string) => (e: any) => setForm((p) => ({ ...p, [k]: e.target.value }));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Add Supplier</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="label">Supplier *</label>
            <select className="input" value={form.supplier_id} onChange={f("supplier_id")}>
              <option value="">Select…</option>
              {suppliers.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
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
          <button className="btn-primary" disabled={!form.supplier_id} onClick={() => mut.mutate({ ...form, supplier_id: parseInt(form.supplier_id) })}>Add</button>
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
