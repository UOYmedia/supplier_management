"use client";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { suppliersApi } from "@/lib/api";
import toast from "react-hot-toast";
import { X } from "lucide-react";

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
