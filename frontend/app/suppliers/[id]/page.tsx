"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { suppliersApi } from "@/lib/api";
import { useParams } from "next/navigation";
import toast from "react-hot-toast";
import { ArrowLeft, Pencil, FileText } from "lucide-react";
import Link from "next/link";
import { SupplierModal } from "../page";

export default function SupplierDetailPage() {
  const { id } = useParams<{ id: string }>();
  const sid = parseInt(id);
  const qc = useQueryClient();
  const [tab, setTab] = useState<"inventory" | "orders" | "invoices">("inventory");
  const [showEdit, setShowEdit] = useState(false);

  const { data: supplier } = useQuery({ queryKey: ["supplier", sid], queryFn: () => suppliersApi.get(sid) });
  const { data: inventory = [] } = useQuery({ queryKey: ["supplier-inventory", sid], queryFn: () => suppliersApi.inventory(sid) });
  const { data: orders = [] } = useQuery({ queryKey: ["supplier-orders", sid], queryFn: () => suppliersApi.orders(sid) });
  const { data: invoices = [] } = useQuery({ queryKey: ["supplier-invoices", sid], queryFn: () => suppliersApi.invoices(sid) });

  const updateStockMut = useMutation({
    mutationFn: ({ psId, stock }: { psId: number; stock: number }) => suppliersApi.updateStock(sid, psId, stock),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["supplier-inventory", sid] }); toast.success("Stock updated"); },
  });

  const markPaidMut = useMutation({
    mutationFn: (invId: number) => suppliersApi.updateInvoice(sid, invId, { status: "paid", paid_at: new Date().toISOString() }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["supplier-invoices", sid] }); toast.success("Marked as paid"); },
  });

  if (!supplier) return <div className="p-6 text-gray-400">Loading…</div>;

  return (
    <div>
      <div className="flex items-center gap-3 mb-6">
        <Link href="/suppliers" className="p-2 hover:bg-gray-100 rounded-lg text-gray-500"><ArrowLeft className="w-4 h-4" /></Link>
        <div className="flex-1">
          <h1 className="page-title">{supplier.name}</h1>
          <p className="text-sm text-gray-500">{[supplier.city, supplier.country].filter(Boolean).join(", ")}</p>
        </div>
        <button className="btn-secondary" onClick={() => setShowEdit(true)}><Pencil className="w-4 h-4" />Edit</button>
      </div>

      <div className="flex gap-1 mb-5 border-b border-gray-200">
        {(["inventory", "orders", "invoices"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium capitalize border-b-2 transition-colors ${tab === t ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
            {t}
          </button>
        ))}
      </div>

      {tab === "inventory" && (
        <div className="card table-wrapper">
          <table>
            <thead><tr><th>Product ID</th><th>Supplier SKU</th><th>Cost</th><th>Stock</th><th>Lead (days)</th><th>Update Stock</th></tr></thead>
            <tbody>
              {inventory.length === 0 ? (
                <tr><td colSpan={6} className="text-center py-6 text-gray-400">No inventory.</td></tr>
              ) : inventory.map((item: any) => (
                <StockRow key={item.product_supplier_id} item={item} onUpdate={(psId, stock) => updateStockMut.mutate({ psId, stock })} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "orders" && (
        <div className="card table-wrapper">
          <table>
            <thead><tr><th>Order ID</th><th>Product</th><th>SKU</th><th>Qty</th><th>Price</th><th>Cost</th><th>Status</th><th>Tracking</th></tr></thead>
            <tbody>
              {orders.length === 0 ? (
                <tr><td colSpan={8} className="text-center py-6 text-gray-400">No orders.</td></tr>
              ) : orders.map((o: any) => (
                <tr key={o.id}>
                  <td><Link href={`/orders/${o.order_id}`} className="text-blue-600 hover:underline">#{o.order_id}</Link></td>
                  <td>{o.product_name}</td>
                  <td className="font-mono text-xs">{o.sku || "—"}</td>
                  <td>{o.quantity}</td>
                  <td>${o.price.toFixed(2)}</td>
                  <td>${o.base_cost.toFixed(2)}</td>
                  <td><FulfillBadge status={o.fulfill_status} /></td>
                  <td className="text-xs text-gray-500">{o.tracking_number || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {tab === "invoices" && (
        <div className="card table-wrapper">
          <table>
            <thead><tr><th>Invoice #</th><th>Period</th><th>Total</th><th>Status</th><th>Paid At</th><th></th></tr></thead>
            <tbody>
              {invoices.length === 0 ? (
                <tr><td colSpan={6} className="text-center py-6 text-gray-400">No invoices.</td></tr>
              ) : invoices.map((inv: any) => (
                <tr key={inv.id}>
                  <td className="font-mono text-xs">{inv.invoice_number}</td>
                  <td className="text-xs text-gray-500">
                    {new Date(inv.period_start).toLocaleDateString()} — {new Date(inv.period_end).toLocaleDateString()}
                  </td>
                  <td>${parseFloat(inv.total_amount).toFixed(2)}</td>
                  <td><InvoiceBadge status={inv.status} /></td>
                  <td className="text-xs text-gray-500">{inv.paid_at ? new Date(inv.paid_at).toLocaleDateString() : "—"}</td>
                  <td>
                    {inv.status !== "paid" && (
                      <button className="text-xs text-blue-600 hover:underline" onClick={() => markPaidMut.mutate(inv.id)}>Mark Paid</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showEdit && <SupplierModal supplier={supplier} onClose={() => setShowEdit(false)} />}
    </div>
  );
}

function StockRow({ item, onUpdate }: { item: any; onUpdate: (psId: number, stock: number) => void }) {
  const [val, setVal] = useState(String(item.stock));
  return (
    <tr>
      <td>{item.product_id}</td>
      <td className="font-mono text-xs">{item.supplier_sku || "—"}</td>
      <td>${item.cost.toFixed(2)}</td>
      <td>
        <input type="number" className="input w-20 text-center" value={val} onChange={(e) => setVal(e.target.value)} />
      </td>
      <td>{item.lead_time_days}</td>
      <td>
        <button className="text-xs text-blue-600 hover:underline" onClick={() => onUpdate(item.product_supplier_id, parseInt(val))}>Save</button>
      </td>
    </tr>
  );
}

function FulfillBadge({ status }: { status: string }) {
  const map: Record<string, string> = { unfulfilled: "badge-gray", pending: "badge-yellow", shipped: "badge-blue", delivered: "badge-green", cancelled: "badge-red" };
  return <span className={map[status] || "badge-gray"}>{status}</span>;
}

function InvoiceBadge({ status }: { status: string }) {
  const map: Record<string, string> = { pending: "badge-yellow", sent: "badge-blue", paid: "badge-green", overdue: "badge-red" };
  return <span className={map[status] || "badge-gray"}>{status}</span>;
}
