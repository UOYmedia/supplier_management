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
    street1: supplier?.street1 ?? "",
    street2: supplier?.street2 ?? "",
    city: supplier?.city ?? "",
    state: supplier?.state ?? "",
    country: supplier?.country ?? "",
    zipcode: supplier?.zipcode ?? "",
    notes: supplier?.notes ?? "",
    username: supplier?.username ?? "",
    password: "",
  });

  const mut = useMutation({
    mutationFn: (data: any) => {
      const payload: any = { ...data };
      if (!payload.password) delete payload.password;
      return supplier ? suppliersApi.update(supplier.id, payload) : suppliersApi.create(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["suppliers"] });
      toast.success(supplier ? "Updated" : "Created");
      onClose();
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  const f = (k: string) => (e: any) => setForm((p) => ({ ...p, [k]: e.target.value }));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">{supplier ? "Edit Supplier" : "New Supplier"}</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>

        <div className="grid grid-cols-2 gap-3">
          {/* Name */}
          <div className="col-span-2">
            <label className="label">Name *</label>
            <input className="input" value={form.name} onChange={f("name")} placeholder="Supplier name" />
          </div>

          {/* Contact */}
          <div>
            <label className="label">Email</label>
            <input className="input" type="email" value={form.email} onChange={f("email")} placeholder="supplier@email.com" />
          </div>
          <div>
            <label className="label">Phone</label>
            <input className="input" value={form.phone} onChange={f("phone")} placeholder="+1 234 567 890" />
          </div>

          {/* Address */}
          <div className="col-span-2">
            <label className="label">Street 1</label>
            <input className="input" value={form.street1} onChange={f("street1")} placeholder="123 Main St" />
          </div>
          <div className="col-span-2">
            <label className="label">Street 2 <span className="text-gray-400 font-normal">(optional)</span></label>
            <input className="input" value={form.street2} onChange={f("street2")} placeholder="Suite 100" />
          </div>

          <div>
            <label className="label">City</label>
            <input className="input" value={form.city} onChange={f("city")} placeholder="New York" />
          </div>
          <div>
            <label className="label">State</label>
            <input className="input" value={form.state} onChange={f("state")} placeholder="NY" />
          </div>
          <div>
            <label className="label">Country</label>
            <input className="input" value={form.country} onChange={f("country")} placeholder="US" />
          </div>
          <div>
            <label className="label">Zip Code</label>
            <input className="input" value={form.zipcode} onChange={f("zipcode")} placeholder="10001" />
          </div>

          {/* Notes */}
          <div className="col-span-2">
            <label className="label">Notes</label>
            <textarea className="input" rows={2} value={form.notes} onChange={f("notes")} />
          </div>

          {/* Portal credentials */}
          <div className="col-span-2 border-t border-gray-100 pt-3 mt-1">
            <div className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-3">Portal Login</div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Username</label>
                <input className="input" value={form.username} onChange={f("username")} placeholder="supplier_username" />
              </div>
              <div>
                <label className="label">{supplier ? "New Password" : "Password"}</label>
                <input className="input" type="password" value={form.password} onChange={f("password")}
                  placeholder={supplier ? "Leave blank to keep" : "Set password"} />
              </div>
            </div>
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-4">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button
            className="btn-primary"
            disabled={!form.name || mut.isPending}
            onClick={() => mut.mutate(form)}
          >
            {mut.isPending ? "Saving…" : supplier ? "Save" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
