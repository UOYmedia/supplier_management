"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { suppliersApi } from "@/lib/api";
import toast from "react-hot-toast";
import { Plus, ChevronRight, Trash2, Search, X } from "lucide-react";
import Link from "next/link";

export default function SuppliersPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  const { data: suppliers = [], isLoading } = useQuery({
    queryKey: ["suppliers", search],
    queryFn: () => suppliersApi.list({ search: search || undefined }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => suppliersApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["suppliers"] }); toast.success("Deleted"); },
  });

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Suppliers</h1>
        <button className="btn-primary" onClick={() => setShowCreate(true)}>
          <Plus className="w-4 h-4" /> New Supplier
        </button>
      </div>

      <div className="card mb-4 px-3 py-2 flex items-center gap-2">
        <Search className="w-4 h-4 text-gray-400" />
        <input className="flex-1 text-sm outline-none bg-transparent" placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)} />
        {search && <button onClick={() => setSearch("")}><X className="w-4 h-4 text-gray-400" /></button>}
      </div>

      <div className="card table-wrapper">
        <table>
          <thead><tr>
            <th>Name</th><th>Email</th><th>City</th><th>Country</th><th>Products</th><th>Stock</th><th>Status</th><th></th>
          </tr></thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={8} className="text-center py-8 text-gray-400">Loading…</td></tr>
            ) : suppliers.length === 0 ? (
              <tr><td colSpan={8} className="text-center py-8 text-gray-400">No suppliers found.</td></tr>
            ) : suppliers.map((s: any) => (
              <tr key={s.id}>
                <td className="font-medium">{s.name}</td>
                <td className="text-gray-500 text-xs">{s.email || "—"}</td>
                <td>{s.city || "—"}</td>
                <td>{s.country || "—"}</td>
                <td>{s.product_count}</td>
                <td>{s.total_stock}</td>
                <td><span className={s.is_active ? "badge-green" : "badge-gray"}>{s.is_active ? "Active" : "Inactive"}</span></td>
                <td>
                  <div className="flex gap-1 justify-end">
                    <Link href={`/suppliers/${s.id}`} className="p-1 hover:bg-gray-100 rounded text-gray-500">
                      <ChevronRight className="w-4 h-4" />
                    </Link>
                    <button className="p-1 hover:text-red-500 text-gray-400"
                      onClick={() => confirm("Delete?") && deleteMut.mutate(s.id)}>
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showCreate && <SupplierModal onClose={() => setShowCreate(false)} />}
    </div>
  );
}

export function SupplierModal({ onClose, supplier }: { onClose: () => void; supplier?: any }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    name: supplier?.name ?? "",
    email: supplier?.email ?? "",
    phone: supplier?.phone ?? "",
    address: supplier?.address ?? "",
    city: supplier?.city ?? "",
    country: supplier?.country ?? "",
    notes: supplier?.notes ?? "",
  });
  const mut = useMutation({
    mutationFn: (data: object) => supplier ? suppliersApi.update(supplier.id, data) : suppliersApi.create(data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["suppliers"] }); toast.success(supplier ? "Updated" : "Created"); onClose(); },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });
  const f = (k: string) => (e: any) => setForm((p) => ({ ...p, [k]: e.target.value }));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-lg p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">{supplier ? "Edit Supplier" : "New Supplier"}</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div className="col-span-2"><label className="label">Name *</label><input className="input" value={form.name} onChange={f("name")} /></div>
          <div><label className="label">Email</label><input className="input" type="email" value={form.email} onChange={f("email")} /></div>
          <div><label className="label">Phone</label><input className="input" value={form.phone} onChange={f("phone")} /></div>
          <div className="col-span-2"><label className="label">Address</label><input className="input" value={form.address} onChange={f("address")} /></div>
          <div><label className="label">City</label><input className="input" value={form.city} onChange={f("city")} /></div>
          <div><label className="label">Country</label><input className="input" value={form.country} onChange={f("country")} /></div>
          <div className="col-span-2"><label className="label">Notes</label><textarea className="input" rows={2} value={form.notes} onChange={f("notes")} /></div>
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={!form.name} onClick={() => mut.mutate(form)}>
            {supplier ? "Save" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
