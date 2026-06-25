"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { suppliersApi } from "@/lib/api";
import toast from "react-hot-toast";
import { Plus, Pencil, Trash2, Search, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { SupplierModal } from "./supplier-modal";

export default function SuppliersPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<any | null>(null);

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
            <th>Name</th>
            <th>Contact</th>
            <th>Address</th>
            <th>Products</th>
            <th>Stock</th>
            <th>Status</th>
            <th className="flex justify-end">Actions</th>
          </tr></thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={7} className="text-center py-8 text-gray-400">Loading…</td></tr>
            ) : suppliers.length === 0 ? (
              <tr><td colSpan={7} className="text-center py-8 text-gray-400">No suppliers found.</td></tr>
            ) : suppliers.map((s: any) => (
              <tr
                key={s.id}
                onClick={() => router.push(`/suppliers/${s.id}`)}
                className="cursor-pointer hover:bg-gray-50"
              >
                <td className="font-medium">{s.name}</td>
                <td>
                  <div className="text-xs text-gray-600">{s.email || "—"}</div>
                  {s.phone && <div className="text-xs text-gray-400">{s.phone}</div>}
                </td>
                <td className="text-xs text-gray-500">
                  <div>{[s.city, s.state, s.country].filter(Boolean).join(", ") || "—"}</div>
                  {s.zipcode && <div className="text-gray-400">{s.zipcode}</div>}
                </td>
                <td>{s.product_count}</td>
                <td>{s.total_stock}</td>
                <td><span className={s.is_active ? "badge-green" : "badge-gray"}>{s.is_active ? "Active" : "Inactive"}</span></td>
                <td onClick={(e) => e.stopPropagation()}>
                  <div className="flex gap-1 justify-end">
                    <button className="p-1 hover:text-blue-500 text-gray-400 mr-3"
                      onClick={() => setEditing(s)} title="Edit">
                      <Pencil className="w-4 h-4" />
                    </button>
                    <button className="p-1 hover:text-red-500 text-gray-400"
                      onClick={() => confirm("Delete?") && deleteMut.mutate(s.id)} title="Delete">
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
      {editing && <SupplierModal supplier={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}
