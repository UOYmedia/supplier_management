"use client";
import { useState, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { productsApi, suppliersApi } from "@/lib/api";
import toast from "react-hot-toast";
import { Plus, Upload, Search, Pencil, Trash2, ChevronRight, X } from "lucide-react";
import Link from "next/link";

export default function ProductsPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const { data: products = [], isLoading } = useQuery({
    queryKey: ["products", search],
    queryFn: () => productsApi.list({ search: search || undefined }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => productsApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["products"] }); toast.success("Product deleted"); },
  });

  const importMut = useMutation({
    mutationFn: (file: File) => productsApi.importCsv(file),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["products"] });
      toast.success(`Imported ${data.created} products. Skipped: ${data.skipped}`);
    },
  });

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Products</h1>
        <div className="flex gap-2">
          <input ref={fileRef} type="file" accept=".csv" className="hidden" onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) importMut.mutate(file);
            e.target.value = "";
          }} />
          <button className="btn-secondary" onClick={() => fileRef.current?.click()}>
            <Upload className="w-4 h-4" /> Import CSV
          </button>
          <button className="btn-primary" onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4" /> New Product
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="card mb-4 px-3 py-2 flex items-center gap-2">
        <Search className="w-4 h-4 text-gray-400" />
        <input
          className="flex-1 text-sm outline-none bg-transparent"
          placeholder="Search by name or SKU…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && <button onClick={() => setSearch("")}><X className="w-4 h-4 text-gray-400" /></button>}
      </div>

      <div className="card table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>SKU</th>
              <th>Base Cost</th>
              <th>Suppliers</th>
              <th>Stock</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={7} className="text-center py-8 text-gray-400">Loading…</td></tr>
            ) : products.length === 0 ? (
              <tr><td colSpan={7} className="text-center py-8 text-gray-400">No products found.</td></tr>
            ) : products.map((p: any) => (
              <tr key={p.id}>
                <td className="font-medium">{p.name}</td>
                <td className="text-gray-500 font-mono text-xs">{p.sku}</td>
                <td>${parseFloat(p.base_cost).toFixed(2)}</td>
                <td>{p.supplier_count}</td>
                <td>{p.total_stock}</td>
                <td>
                  <span className={p.is_active ? "badge-green" : "badge-gray"}>
                    {p.is_active ? "Active" : "Inactive"}
                  </span>
                </td>
                <td>
                  <div className="flex items-center gap-1 justify-end">
                    <Link href={`/products/${p.id}`} className="p-1 hover:bg-gray-100 rounded text-gray-500">
                      <ChevronRight className="w-4 h-4" />
                    </Link>
                    <button className="p-1 hover:bg-red-50 rounded text-gray-400 hover:text-red-500"
                      onClick={() => confirm("Delete product?") && deleteMut.mutate(p.id)}>
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showCreate && <ProductModal onClose={() => setShowCreate(false)} />}
    </div>
  );
}

function ProductModal({ onClose, product }: { onClose: () => void; product?: any }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    name: product?.name ?? "",
    sku: product?.sku ?? "",
    base_cost: product?.base_cost ?? "0",
    weight: product?.weight ?? "",
    length: product?.length ?? "",
    width: product?.width ?? "",
    height: product?.height ?? "",
    description: product?.description ?? "",
  });

  const mut = useMutation({
    mutationFn: (data: object) => product ? productsApi.update(product.id, data) : productsApi.create(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["products"] });
      toast.success(product ? "Product updated" : "Product created");
      onClose();
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  const f = (k: string) => (e: any) => setForm((p) => ({ ...p, [k]: e.target.value }));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-lg p-6 relative">
        <button className="absolute top-4 right-4 text-gray-400" onClick={onClose}><X className="w-5 h-5" /></button>
        <h2 className="text-lg font-semibold mb-4">{product ? "Edit Product" : "New Product"}</h2>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2">
            <label className="label">Name *</label>
            <input className="input" value={form.name} onChange={f("name")} />
          </div>
          <div>
            <label className="label">SKU *</label>
            <input className="input" value={form.sku} onChange={f("sku")} disabled={!!product} />
          </div>
          <div>
            <label className="label">Base Cost ($)</label>
            <input className="input" type="number" step="0.01" value={form.base_cost} onChange={f("base_cost")} />
          </div>
          <div>
            <label className="label">Weight (kg)</label>
            <input className="input" type="number" step="0.001" value={form.weight} onChange={f("weight")} />
          </div>
          <div>
            <label className="label">Length (cm)</label>
            <input className="input" type="number" step="0.1" value={form.length} onChange={f("length")} />
          </div>
          <div>
            <label className="label">Width (cm)</label>
            <input className="input" type="number" step="0.1" value={form.width} onChange={f("width")} />
          </div>
          <div>
            <label className="label">Height (cm)</label>
            <input className="input" type="number" step="0.1" value={form.height} onChange={f("height")} />
          </div>
          <div className="col-span-2">
            <label className="label">Description</label>
            <textarea className="input" rows={2} value={form.description} onChange={f("description")} />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={!form.name || !form.sku} onClick={() => mut.mutate(form)}>
            {product ? "Save" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
