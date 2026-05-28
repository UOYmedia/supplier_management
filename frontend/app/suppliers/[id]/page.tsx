"use client";
import { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { suppliersApi } from "@/lib/api";
import { useParams } from "next/navigation";
import toast from "react-hot-toast";
import { ArrowLeft, Download, Pencil, Plus, Trash2, Truck, Upload, X, Pencil as PencilIcon } from "lucide-react";
import Link from "next/link";
import { SupplierModal } from "../supplier-modal";
import { OrderStatusBadge } from "../../orders/order-status-badge";

export default function SupplierDetailPage() {
  const { id } = useParams<{ id: string }>();
  const sid = parseInt(id);
  const qc = useQueryClient();
  const [tab, setTab] = useState<"catalog" | "orders" | "invoices">("catalog");
  const [showEdit, setShowEdit] = useState(false);
  const [showAddProduct, setShowAddProduct] = useState(false);
  const [editingProduct, setEditingProduct] = useState<any>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const { data: supplier } = useQuery({ queryKey: ["supplier", sid], queryFn: () => suppliersApi.get(sid) });
  const { data: catalog = [] } = useQuery({ queryKey: ["supplier-catalog", sid], queryFn: () => suppliersApi.listProducts(sid) });
  const { data: orders = [] } = useQuery({ queryKey: ["supplier-orders", sid], queryFn: () => suppliersApi.orders(sid) });
  const { data: invoices = [] } = useQuery({ queryKey: ["supplier-invoices", sid], queryFn: () => suppliersApi.invoices(sid) });

  const deleteMut = useMutation({
    mutationFn: (spId: number) => suppliersApi.deleteProduct(sid, spId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["supplier-catalog", sid] }); toast.success("Deleted"); },
    onError: () => toast.error("Cannot delete — product is used by components"),
  });

  const importMut = useMutation({
    mutationFn: (file: File) => suppliersApi.importCatalog(sid, file),
    onSuccess: (data: any) => {
      qc.invalidateQueries({ queryKey: ["supplier-catalog", sid] });
      const msg = `Imported: ${data.created} created, ${data.updated} updated`;
      if (data.errors?.length) {
        toast.error(`${msg}. ${data.errors.length} row(s) skipped — see console.`);
        console.warn("Catalog import errors:", data.errors);
      } else {
        toast.success(msg);
      }
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Import failed"),
  });

  const exportMut = useMutation({
    mutationFn: () => {
      const safe = (supplier?.name || "supplier").replace(/[^a-z0-9]+/gi, "_").slice(0, 40);
      const date = new Date().toISOString().slice(0, 10).replace(/-/g, "");
      return suppliersApi.exportCatalog(sid, `${safe}_catalog_${date}.csv`);
    },
    onError: () => toast.error("Export failed"),
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
          <p className="text-sm text-gray-500">
            {[supplier.street1, supplier.street2, supplier.city, supplier.state, supplier.country, supplier.zipcode].filter(Boolean).join(", ") || "No address"}
          </p>
          {(supplier.email || supplier.phone) && (
            <p className="text-xs text-gray-400 mt-0.5">{[supplier.email, supplier.phone].filter(Boolean).join(" · ")}</p>
          )}
        </div>
        <button className="btn-secondary" onClick={() => setShowEdit(true)}><Pencil className="w-4 h-4" />Edit</button>
      </div>

      <div className="flex gap-1 mb-5 border-b border-gray-200">
        {(["catalog", "orders", "invoices"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium capitalize border-b-2 transition-colors ${tab === t ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
            {t === "catalog" ? `Catalog (${catalog.length})` : t}
          </button>
        ))}
      </div>

      {tab === "catalog" && (
        <div>
          <div className="flex justify-between items-center mb-3">
            <button
              className="text-xs text-blue-600 hover:underline"
              onClick={() => suppliersApi.downloadCatalogTemplate(sid)}
            >
              Download CSV template
            </button>
            <div className="flex gap-2">
              <input
                ref={fileRef}
                type="file"
                accept=".csv"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) importMut.mutate(file);
                  e.target.value = "";
                }}
              />
              <button
                className="btn-secondary"
                onClick={() => fileRef.current?.click()}
                disabled={importMut.isPending}
              >
                <Upload className="w-4 h-4" /> {importMut.isPending ? "Importing…" : "Import CSV"}
              </button>
              <button
                className="btn-secondary"
                onClick={() => exportMut.mutate()}
                disabled={exportMut.isPending || catalog.length === 0}
              >
                <Download className="w-4 h-4" /> Export CSV
              </button>
              <button className="btn-primary" onClick={() => setShowAddProduct(true)}>
                <Plus className="w-4 h-4" /> Add Product
              </button>
            </div>
          </div>
          <div className="card table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>SKU</th>
                  <th>Unit Price</th>
                  <th>Stock</th>
                  <th>Pending</th>
                  <th>Sold</th>
                  <th>Total</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {catalog.length === 0 ? (
                  <tr><td colSpan={8} className="text-center py-6 text-gray-400">No products in catalog. Add one to start tracking inventory.</td></tr>
                ) : catalog.map((item: any) => (
                  <CatalogRow
                    key={item.id}
                    item={item}
                    onEdit={() => setEditingProduct(item)}
                    onDelete={() => {
                      if (confirm(`Delete "${item.name}"?`)) deleteMut.mutate(item.id);
                    }}
                  />
                ))}
              </tbody>
            </table>
          </div>
          {/* Summary row */}
          {catalog.length > 0 && (
            <div className="mt-3 flex gap-6 text-sm text-gray-500 px-1">
              <span>Total products: <strong className="text-gray-800">{catalog.length}</strong></span>
              <span>Total stock: <strong className="text-gray-800">{catalog.reduce((s: number, i: any) => s + i.stock_quantity, 0)}</strong></span>
              <span>Total pending: <strong className="text-yellow-700">{catalog.reduce((s: number, i: any) => s + i.pending_quantity, 0)}</strong></span>
              <span>Total sold: <strong className="text-green-700">{catalog.reduce((s: number, i: any) => s + i.sold_quantity, 0)}</strong></span>
            </div>
          )}
        </div>
      )}

      {tab === "orders" && (
        <div>
          {orders.length === 0 ? (
            <div className="card p-6 text-center text-gray-400">No orders.</div>
          ) : groupOrders(orders).map((group: any) => {
            const unshipped = group.items.filter((i: any) => i.fulfill_status === "unfulfilled" || i.fulfill_status === "pending");
            const subtotal = group.items.reduce((s: number, i: any) => s + i.base_cost * i.quantity, 0);
            return (
              <div key={group.order_id} className="card mb-4">
                <div className="flex items-center justify-between gap-3 px-4 py-3 border-b border-gray-100">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <Link href={`/orders/${group.order_id}`} className="text-blue-600 hover:underline font-semibold text-sm">
                        Order #{group.order_id}
                      </Link>
                      {group.external_order_id && <span className="font-mono text-xs text-gray-400">{group.external_order_id}</span>}
                      {group.marketplace && <span className="text-xs text-gray-400 capitalize">{group.marketplace}</span>}
                      {group.order_status && <OrderStatusBadge status={group.order_status} />}
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5">
                      {group.items.length} item(s) · {group.buyer_name || "—"} · {group.ordered_at ? new Date(group.ordered_at).toLocaleDateString() : "—"} · supplier subtotal ${subtotal.toFixed(2)}
                    </div>
                  </div>
                  {unshipped.length > 0 && (
                    <Link
                      href={`/orders/${group.order_id}?buy_label_supplier=${sid}`}
                      className="btn-secondary text-xs py-1 whitespace-nowrap"
                    >
                      <Truck className="w-3 h-3" /> Buy Label ({unshipped.length})
                    </Link>
                  )}
                </div>
                <div className="table-wrapper">
                  <table>
                    <thead><tr><th>Product</th><th>SKU</th><th>Qty</th><th>Price</th><th>Cost</th><th>Status</th><th>Tracking</th></tr></thead>
                    <tbody>
                      {group.items.map((o: any) => (
                        <tr key={o.id}>
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
              </div>
            );
          })}
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

      {showAddProduct && (
        <ProductFormModal
          supplierId={sid}
          onClose={() => setShowAddProduct(false)}
        />
      )}

      {editingProduct && (
        <ProductFormModal
          supplierId={sid}
          existing={editingProduct}
          onClose={() => setEditingProduct(null)}
        />
      )}
    </div>
  );
}

function groupOrders(items: any[]) {
  const map = new Map<number, any>();
  for (const li of items) {
    let g = map.get(li.order_id);
    if (!g) {
      g = {
        order_id: li.order_id,
        external_order_id: li.external_order_id,
        marketplace: li.marketplace,
        ordered_at: li.ordered_at,
        buyer_name: li.buyer_name,
        order_status: li.order_status,
        items: [],
      };
      map.set(li.order_id, g);
    }
    g.items.push(li);
  }
  return Array.from(map.values()).sort((a, b) => {
    const da = a.ordered_at ? Date.parse(a.ordered_at) : 0;
    const db = b.ordered_at ? Date.parse(b.ordered_at) : 0;
    return db - da;
  });
}

function CatalogRow({ item, onEdit, onDelete }: { item: any; onEdit: () => void; onDelete: () => void }) {
  const total = item.stock_quantity + item.pending_quantity + item.sold_quantity;
  return (
    <tr>
      <td className="font-medium">{item.name}</td>
      <td className="font-mono text-xs text-gray-500">{item.sku}</td>
      <td>${parseFloat(item.unit_price).toFixed(2)}</td>
      <td>
        <span className={item.stock_quantity === 0 ? "text-red-500 font-medium" : "text-gray-800"}>
          {item.stock_quantity}
        </span>
      </td>
      <td>
        <span className={item.pending_quantity > 0 ? "text-yellow-700 font-medium" : "text-gray-500"}>
          {item.pending_quantity}
        </span>
      </td>
      <td>
        <span className={item.sold_quantity > 0 ? "text-green-700 font-medium" : "text-gray-500"}>
          {item.sold_quantity}
        </span>
      </td>
      <td className="text-gray-600">{total}</td>
      <td>
        <div className="flex items-center gap-2">
          <button className="p-1 hover:text-blue-600 text-gray-400" onClick={onEdit}><PencilIcon className="w-4 h-4" /></button>
          <button className="p-1 hover:text-red-500 text-gray-400" onClick={onDelete}><Trash2 className="w-4 h-4" /></button>
        </div>
      </td>
    </tr>
  );
}

function ProductFormModal({
  supplierId,
  existing,
  onClose,
}: {
  supplierId: number;
  existing?: any;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const isEdit = !!existing;
  const [form, setForm] = useState({
    name: existing?.name ?? "",
    sku: existing?.sku ?? "",
    unit_price: existing?.unit_price ? String(existing.unit_price) : "0",
    stock_quantity: existing?.stock_quantity != null ? String(existing.stock_quantity) : "0",
  });

  const mut = useMutation({
    mutationFn: (data: object) =>
      isEdit
        ? suppliersApi.updateProduct(supplierId, existing.id, data)
        : suppliersApi.createProduct(supplierId, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["supplier-catalog", supplierId] });
      toast.success(isEdit ? "Updated" : "Product added");
      onClose();
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  const f = (k: string) => (e: any) => setForm((p) => ({ ...p, [k]: e.target.value }));

  const handleSubmit = () => {
    mut.mutate({
      name: form.name,
      sku: form.sku,
      unit_price: parseFloat(form.unit_price) || 0,
      stock_quantity: parseInt(form.stock_quantity) || 0,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">{isEdit ? "Edit Product" : "Add Product to Catalog"}</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="label">Product Name *</label>
            <input className="input" value={form.name} onChange={f("name")} placeholder="e.g. Red T-Shirt Size M" />
          </div>
          <div>
            <label className="label">SKU *</label>
            <input className="input" value={form.sku} onChange={f("sku")} placeholder="Supplier's internal SKU" />
          </div>
          <div>
            <label className="label">Unit Price ($)</label>
            <input className="input" type="number" step="0.01" min="0" value={form.unit_price} onChange={f("unit_price")} />
          </div>
          <div>
            <label className="label">Stock Quantity</label>
            <input className="input" type="number" min="0" value={form.stock_quantity} onChange={f("stock_quantity")} />
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button
            className="btn-primary"
            disabled={!form.name || !form.sku || mut.isPending}
            onClick={handleSubmit}
          >
            {isEdit ? "Save" : "Add"}
          </button>
        </div>
      </div>
    </div>
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
