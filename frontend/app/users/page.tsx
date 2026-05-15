"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { usersApi } from "@/lib/api";
import toast from "react-hot-toast";
import { Plus, Trash2, Pencil, X, ShieldCheck, User } from "lucide-react";

export default function UsersPage() {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<any>(null);

  const { data: users = [], isLoading } = useQuery({
    queryKey: ["users"],
    queryFn: usersApi.list,
  });

  const deleteMut = useMutation({
    mutationFn: (id: number) => usersApi.delete(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["users"] }); toast.success("Deleted"); },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  const currentUser = typeof window !== "undefined"
    ? JSON.parse(localStorage.getItem("admin_user") || "{}")
    : {};

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Users</h1>
        <button className="btn-primary" onClick={() => setShowCreate(true)}>
          <Plus className="w-4 h-4" /> New User
        </button>
      </div>

      <div className="card table-wrapper">
        <table>
          <thead><tr>
            <th>Username</th><th>Email</th><th>Role</th><th>Status</th><th>Created</th><th></th>
          </tr></thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={6} className="text-center py-8 text-gray-400">Loading…</td></tr>
            ) : users.map((u: any) => (
              <tr key={u.id}>
                <td>
                  <div className="flex items-center gap-2">
                    {u.role === "admin"
                      ? <ShieldCheck className="w-4 h-4 text-blue-500" />
                      : <User className="w-4 h-4 text-gray-400" />}
                    <span className="font-medium">{u.username}</span>
                    {u.id === currentUser.id && (
                      <span className="text-xs text-gray-400">(you)</span>
                    )}
                  </div>
                </td>
                <td className="text-gray-500 text-sm">{u.email || "—"}</td>
                <td>
                  <span className={`badge text-xs ${u.role === "admin" ? "badge-blue" : "badge-gray"}`}>
                    {u.role}
                  </span>
                </td>
                <td>
                  <span className={`badge text-xs ${u.is_active ? "badge-green" : "badge-gray"}`}>
                    {u.is_active ? "Active" : "Inactive"}
                  </span>
                </td>
                <td className="text-xs text-gray-400">{new Date(u.created_at).toLocaleDateString()}</td>
                <td>
                  <div className="flex gap-1 justify-end">
                    <button className="p-1 hover:bg-gray-100 rounded text-gray-500" onClick={() => setEditing(u)}>
                      <Pencil className="w-4 h-4" />
                    </button>
                    {u.id !== currentUser.id && (
                      <button className="p-1 hover:text-red-500 text-gray-400"
                        onClick={() => confirm("Delete this user?") && deleteMut.mutate(u.id)}>
                        <Trash2 className="w-4 h-4" />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showCreate && <UserModal onClose={() => setShowCreate(false)} />}
      {editing && <UserModal user={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function UserModal({ user, onClose }: { user?: any; onClose: () => void }) {
  const qc = useQueryClient();
  const [form, setForm] = useState({
    username: user?.username ?? "",
    email: user?.email ?? "",
    password: "",
    role: user?.role ?? "staff",
    is_active: user?.is_active ?? true,
  });

  const mut = useMutation({
    mutationFn: (data: any) => {
      const payload = { ...data };
      if (!payload.password) delete payload.password;
      return user ? usersApi.update(user.id, payload) : usersApi.create(payload);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] });
      toast.success(user ? "Updated" : "Created");
      onClose();
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  const f = (k: string) => (e: any) => setForm((p) => ({ ...p, [k]: e.target.value }));

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">{user ? "Edit User" : "New User"}</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="label">Username *</label>
            <input className="input" value={form.username} onChange={f("username")}
              disabled={!!user} placeholder="username" />
          </div>
          <div>
            <label className="label">Email</label>
            <input className="input" type="email" value={form.email} onChange={f("email")}
              placeholder="user@email.com" />
          </div>
          <div>
            <label className="label">{user ? "New Password" : "Password *"}</label>
            <input className="input" type="password" value={form.password} onChange={f("password")}
              placeholder={user ? "Leave blank to keep" : "Set password"} />
          </div>
          <div>
            <label className="label">Role</label>
            <select className="input" value={form.role} onChange={f("role")}>
              <option value="admin">Admin</option>
              <option value="staff">Staff</option>
            </select>
          </div>
          {user && (
            <div>
              <label className="label">Status</label>
              <select className="input" value={String(form.is_active)}
                onChange={(e) => setForm((p) => ({ ...p, is_active: e.target.value === "true" }))}>
                <option value="true">Active</option>
                <option value="false">Inactive</option>
              </select>
            </div>
          )}
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={!form.username || (!user && !form.password) || mut.isPending}
            onClick={() => mut.mutate(form)}>
            {mut.isPending ? "Saving…" : user ? "Save" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
