"use client";
import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { suppliersApi, snapshotsApi } from "@/lib/api";
import { useParams } from "next/navigation";
import toast from "react-hot-toast";
import { ArrowLeft, Download, Package, Pencil, Plus, Printer, Trash2, Truck, Upload, X, Pencil as PencilIcon } from "lucide-react";
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
  const [catalogSearch, setCatalogSearch] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const fileRef = useRef<HTMLInputElement>(null);

  const { data: supplier } = useQuery({ queryKey: ["supplier", sid], queryFn: () => suppliersApi.get(sid) });
  const { data: liveCatalog = [] } = useQuery({
    queryKey: ["supplier-catalog", sid],
    queryFn: () => suppliersApi.listProducts(sid),
    enabled: !catalogDate,
  });
  const { data: snapshotDates = [] } = useQuery<string[]>({
    queryKey: ["snapshot-dates"],
    queryFn: () => snapshotsApi.dates(),
  });
  // Dates come newest-first; the most recent saved snapshot is "yesterday".
  const latestSnapshot = snapshotDates[0] ?? "";
  const { data: snapshotRows = [] } = useQuery<any[]>({
    queryKey: ["supplier-catalog-snapshot", sid, catalogDate],
    queryFn: () => snapshotsApi.get(catalogDate, sid),
    enabled: !!catalogDate,
  });
  // Normalise a snapshot row into the same shape the catalog table expects.
  const catalog = catalogDate
    ? snapshotRows.map((r: any) => ({
      id: r.sku,
      name: r.product_name || r.sku,
      sku: r.sku,
      unit_price: r.unit_cost,
      stock_quantity: r.available,
      pending_quantity: r.ordered,
      sold_quantity: r.sold,
    }))
    : liveCatalog;
  const { data: orders = [] } = useQuery({ queryKey: ["supplier-orders", sid], queryFn: () => suppliersApi.orders(sid) });
  const { data: invoices = [] } = useQuery({ queryKey: ["supplier-invoices", sid], queryFn: () => suppliersApi.invoices(sid) });

  const q = catalogSearch.trim().toLowerCase();
  const filteredCatalog = q
    ? catalog.filter((i: any) =>
      (i.name || "").toLowerCase().includes(q) || (i.sku || "").toLowerCase().includes(q)
    )
    : catalog;

  const deleteMut = useMutation({
    mutationFn: (spId: number) => suppliersApi.deleteProduct(sid, spId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["supplier-catalog", sid] }); toast.success("Deleted"); },
    onError: () => toast.error("Cannot delete — product is used by components"),
  });

  const bulkDeleteMut = useMutation({
    mutationFn: (ids: number[]) => suppliersApi.bulkDeleteProducts(sid, ids),
    onSuccess: (data: any) => {
      qc.invalidateQueries({ queryKey: ["supplier-catalog", sid] });
      setSelected(new Set());
      const skipped = data.skipped?.length || 0;
      if (skipped > 0) {
        toast.error(`Deleted ${data.deleted}. ${skipped} skipped — in use by orders.`);
      } else {
        toast.success(`Deleted ${data.deleted} product(s)`);
      }
    },
    onError: () => toast.error("Bulk delete failed"),
  });

  const toggleSelected = (spId: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(spId) ? next.delete(spId) : next.add(spId);
      return next;
    });
  };

  const allVisibleSelected = filteredCatalog.length > 0 && filteredCatalog.every((i: any) => selected.has(i.id));
  const toggleSelectAll = () => {
    setSelected((prev) => {
      if (filteredCatalog.every((i: any) => prev.has(i.id))) {
        const next = new Set(prev);
        filteredCatalog.forEach((i: any) => next.delete(i.id));
        return next;
      }
      const next = new Set(prev);
      filteredCatalog.forEach((i: any) => next.add(i.id));
      return next;
    });
  };

  const handleBulkDelete = () => {
    const ids = Array.from(selected);
    if (ids.length === 0) return;
    if (confirm(`Delete ${ids.length} selected product(s)?`)) bulkDeleteMut.mutate(ids);
  };

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

  const [showGenerateInvoice, setShowGenerateInvoice] = useState(false);

  const markPaidMut = useMutation({
    mutationFn: (invId: number) => suppliersApi.updateInvoice(sid, invId, { status: "paid", paid_at: new Date().toISOString() }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["supplier-invoices", sid] }); toast.success("Marked as paid"); },
  });

  if (!supplier) return <div className="p-6 text-gray-400">Loading…</div>;

  return (
    <div>
      <div className="flex items-center gap-3 mb-1">
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

      <div className="flex gap-1 mb-2 border-b border-gray-200">
        {(["catalog", "orders", "invoices"] as const).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium capitalize border-b-2 transition-colors ${tab === t ? "border-blue-600 text-blue-600" : "border-transparent text-gray-500 hover:text-gray-700"}`}>
            {t === "catalog" ? `Catalog (${catalog.length})` : t}
          </button>
        ))}
      </div>

      {tab === "catalog" && (
        <div>
          <div className="flex justify-between items-center mb-3 gap-3">
            <div className="flex items-center gap-3 flex-1 min-w-0">
              <input
                className="input w-64"
                placeholder="Search by name or SKU…"
                value={catalogSearch}
                onChange={(e) => setCatalogSearch(e.target.value)}
              />
              <button
                className="text-xs text-blue-600 hover:underline whitespace-nowrap"
                onClick={() => suppliersApi.downloadCatalogTemplate(sid)}
              >
                Download CSV template
              </button>
            </div>
            <div className="flex gap-2">
              {selected.size > 0 && (
                <button
                  className="btn-secondary text-red-600 hover:bg-red-50 border-red-200"
                  onClick={handleBulkDelete}
                  disabled={bulkDeleteMut.isPending}
                >
                  <Trash2 className="w-4 h-4" /> Delete selected ({selected.size})
                </button>
              )}
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
                onClick={() => setCatalogDate("")}
                className={`px-2.5 py-1.5 text-xs font-medium rounded-md border transition-colors ${catalogDate === ""
                    ? "bg-gray-800 text-white border-transparent"
                    : "bg-white text-gray-500 border-gray-200 hover:border-gray-300"
                  }`}
              >
                Today (live)
              </button>
              <button
                onClick={() => latestSnapshot && setCatalogDate(latestSnapshot)}
                disabled={!latestSnapshot}
                title={latestSnapshot ? `Snapshot ${latestSnapshot}` : "No saved snapshot yet"}
                className={`px-2.5 py-1.5 text-xs font-medium rounded-md border transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${catalogDate && catalogDate === latestSnapshot
                    ? "bg-gray-800 text-white border-transparent"
                    : "bg-white text-gray-500 border-gray-200 hover:border-gray-300"
                  }`}
              >
                Yesterday
              </button>
              <input
                type="date"
                value={catalogDate}
                max={latestSnapshot || undefined}
                onChange={(e) => setCatalogDate(e.target.value)}
                title="Pick a day to view its saved end-of-day snapshot"
                className="border border-gray-200 rounded-md py-1 px-2 text-xs text-gray-600 bg-white"
              />
            </div>
            {!catalogDate && (
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
            )}
          </div>
          {catalogDate && (
            <div className="mb-3">
              <span className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md px-2.5 py-1">
                Viewing saved end-of-day snapshot for {catalogDate} (read-only)
              </span>
            </div>
          )}
          <div className="card table-wrapper table-scroll max-h-[calc(100vh-245px)]">
            <table>
              <thead>
                <tr>
                  <th className="w-8">
                    <input
                      type="checkbox"
                      checked={allVisibleSelected}
                      onChange={toggleSelectAll}
                      disabled={filteredCatalog.length === 0}
                    />
                  </th>
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
                  <tr><td colSpan={9} className="text-center py-6 text-gray-400">No products in catalog. Add one to start tracking inventory.</td></tr>
                ) : filteredCatalog.length === 0 ? (
                  <tr><td colSpan={9} className="text-center py-6 text-gray-400">No products match "{catalogSearch}".</td></tr>
                ) : filteredCatalog.map((item: any) => (
                  <CatalogRow
                    key={item.id}
                    item={item}
                    selected={selected.has(item.id)}
                    onToggle={() => toggleSelected(item.id)}
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
            const unshipped = group.items.filter((i: any) => i.fulfill_status === "unfulfilled" || i.fulfill_status === "pending" || i.fulfill_status === "drop_off");
            const needsLabel = Array.from(new Map(unshipped.filter((i: any) => !i.label_id).map((i: any) => [i.order_line_item_id, i])).values());
            const labeled = group.items.filter((i: any) => i.label_id);
            const uniqueLIs = Array.from(new Map(group.items.map((i: any) => [i.order_line_item_id, i])).values());
            const subtotal = uniqueLIs.reduce((s: number, i: any) => s + i.base_cost * i.li_quantity, 0);
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
                  <div className="flex gap-2">
                    {labeled.length > 0 && (
                      <button
                        type="button"
                        className="btn-primary text-xs py-1 whitespace-nowrap"
                        onClick={() => printAndMarkShipped(group.order_id, labeled, qc, sid)}
                      >
                        <Printer className="w-3 h-3" /> Print Label
                      </button>
                    )}
                    {needsLabel.length > 0 && (
                      <Link
                        href={`/orders/${group.order_id}?buy_label_supplier=${sid}`}
                        className="btn-secondary text-xs py-1 whitespace-nowrap"
                      >
                        <Truck className="w-3 h-3" /> Buy Label ({needsLabel.length})
                      </Link>
                    )}
                  </div>
                </div>
                <div className="table-wrapper table-scroll max-h-[calc(100vh-245px)]">
                  <table>
                    <thead><tr><th className="w-12"></th><th>Catalog Product</th><th>Supplier SKU</th><th>Qty</th><th>Cost</th><th>Status</th><th>Tracking</th></tr></thead>
                    <tbody>
                      {group.items.map((o: any) => (
                        <tr key={o.item_key}>
                          <td>
                            {o.image_url ? (
                              <img src={o.image_url} alt={o.product_name} className="w-9 h-9 rounded object-cover border border-gray-200" />
                            ) : (
                              <div className="w-9 h-9 rounded bg-gray-100 flex items-center justify-center border border-gray-200">
                                <Package className="w-4 h-4 text-gray-300" />
                              </div>
                            )}
                          </td>
                          <td>{o.product_name}</td>
                          <td className="font-mono text-xs">{o.sku || "—"}</td>
                          <td>{o.quantity}</td>
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
        <div>
          <div className="flex justify-end mb-3">
            <button className="btn-primary" onClick={() => setShowGenerateInvoice(true)}>
              <Plus className="w-4 h-4" /> Generate Invoice from Orders
            </button>
          </div>
          <div className="card table-wrapper table-scroll max-h-[calc(100vh-245px)]">
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
                      <div className="flex items-center gap-3">
                        <a
                          className="text-xs text-blue-600 hover:underline inline-flex items-center gap-1"
                          href={suppliersApi.invoicePdfUrl(sid, inv.id)}
                          target="_blank"
                          rel="noopener noreferrer"
                        >
                          <Download className="w-3.5 h-3.5" /> PDF
                        </a>
                        {inv.status !== "paid" && (
                          <button className="text-xs text-blue-600 hover:underline" onClick={() => markPaidMut.mutate(inv.id)}>Mark Paid</button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {showGenerateInvoice && (
        <GenerateInvoiceModal
          supplierId={sid}
          onClose={() => setShowGenerateInvoice(false)}
          onCreated={() => {
            qc.invalidateQueries({ queryKey: ["supplier-invoices", sid] });
            setShowGenerateInvoice(false);
          }}
        />
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

function printAndMarkShipped(orderId: number, labeledItems: any[], qc: any, supplierId: number) {
  // Group items by label_id so we hit each label once
  const byLabel = new Map<number, any[]>();
  for (const li of labeledItems) {
    if (!li.label_id) continue;
    const arr = byLabel.get(li.label_id) || [];
    arr.push(li);
    byLabel.set(li.label_id, arr);
  }
  for (const [labelId, items] of byLabel) {
    const sample = items[0];
    // Always go through the backend download endpoint so the label is served
    // with the product info stamped in (Qty + NAME + size + date for JOE).
    const url = (sample.label_has_pdf || sample.label_url)
      ? `/api/v1/orders/${orderId}/labels/${labelId}/download`
      : null;
    if (url) {
      const win = window.open(url, "_blank");
      if (win) {
        try {
          win.focus();
          setTimeout(() => { try { win.print(); } catch { } }, 800);
        } catch { }
      }
    }
    // Flip items to shipped server-side
    fetch(`/api/v1/orders/${orderId}/labels/${labelId}/mark-printed`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${localStorage.getItem("admin_token")}`,
        "Content-Type": "application/json",
      },
    })
      .then((r) => {
        if (r.ok) {
          toast.success("Marked as shipped");
          qc.invalidateQueries({ queryKey: ["supplier-orders", supplierId] });
          qc.invalidateQueries({ queryKey: ["order", orderId] });
        }
      })
      .catch(() => { });
  }
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

function CatalogRow({ item, selected, onToggle, onEdit, onDelete }: { item: any; selected: boolean; onToggle: () => void; onEdit: () => void; onDelete: () => void }) {
  const total = item.stock_quantity + item.pending_quantity + item.sold_quantity;
  return (
    <tr className={selected ? "bg-blue-50" : undefined}>
      <td>
        <input type="checkbox" checked={selected} onChange={onToggle} />
      </td>
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
        {!readOnly && (
          <div className="flex items-center gap-2">
            <button className="p-1 hover:text-blue-600 text-gray-400" onClick={onEdit}><PencilIcon className="w-4 h-4" /></button>
            <button className="p-1 hover:text-red-500 text-gray-400" onClick={onDelete}><Trash2 className="w-4 h-4" /></button>
          </div>
        )}
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
    weight: existing?.weight != null ? String(existing.weight) : "",
    length: existing?.length != null ? String(existing.length) : "",
    width: existing?.width != null ? String(existing.width) : "",
    height: existing?.height != null ? String(existing.height) : "",
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
    const parseOpt = (s: string) => (s === "" ? null : parseFloat(s) || 0);
    mut.mutate({
      name: form.name,
      sku: form.sku,
      unit_price: parseFloat(form.unit_price) || 0,
      stock_quantity: parseInt(form.stock_quantity) || 0,
      weight: parseOpt(form.weight),
      length: parseOpt(form.length),
      width: parseOpt(form.width),
      height: parseOpt(form.height),
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
          <div className="border-t border-gray-100 pt-3 mt-1">
            <div className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">Per-unit shipping dimensions</div>
            <p className="text-xs text-gray-400 mb-2">Used to auto-estimate parcel size when buying labels. Leave blank if unknown.</p>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="label">Weight (oz)</label>
                <input className="input" type="number" step="0.01" min="0" value={form.weight} onChange={f("weight")} />
              </div>
              <div>
                <label className="label">Length (in)</label>
                <input className="input" type="number" step="0.1" min="0" value={form.length} onChange={f("length")} />
              </div>
              <div>
                <label className="label">Width (in)</label>
                <input className="input" type="number" step="0.1" min="0" value={form.width} onChange={f("width")} />
              </div>
              <div>
                <label className="label">Height (in)</label>
                <input className="input" type="number" step="0.1" min="0" value={form.height} onChange={f("height")} />
              </div>
            </div>
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

function GenerateInvoiceModal({ supplierId, onClose, onCreated }: { supplierId: number; onClose: () => void; onCreated: () => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const createMut = useMutation({
    mutationFn: (data: object) => suppliersApi.createInvoiceFromOrders(supplierId, data),
    onSuccess: () => { toast.success("Invoice created"); onCreated(); },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error creating invoice"),
  });

  useEffect(() => {
    suppliersApi.previewInvoiceFromOrders(supplierId)
      .then((data: any) => {
        const rows = (data.items || []).map((it: any) => ({
          ...it,
          unit_cost_input: parseFloat(it.unit_cost).toFixed(2),
        }));
        setItems(rows);
        setSelected(new Set(rows.map((r: any) => r.order_line_item_id)));
        setLoading(false);
      })
      .catch(() => { setError("Failed to load fulfilled orders."); setLoading(false); });
  }, [supplierId]);

  const updateCost = (id: number, val: string) => {
    setItems((prev) => prev.map((it) => it.order_line_item_id === id ? { ...it, unit_cost_input: val } : it));
  };

  const toggleItem = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const selectedItems = items.filter((it) => selected.has(it.order_line_item_id));
  const total = selectedItems.reduce((s, it) => {
    const unit = parseFloat(it.unit_cost_input) || 0;
    return s + unit * it.quantity;
  }, 0);

  const handleSubmit = () => {
    if (selectedItems.length === 0) { toast.error("Select at least one item"); return; }
    createMut.mutate({
      notes: notes || undefined,
      items: selectedItems.map((it) => {
        const unit = parseFloat(it.unit_cost_input) || 0;
        return {
          order_line_item_id: it.order_line_item_id,
          description: `${it.product_name}${it.sku ? ` (${it.sku})` : ""} — Order #${it.order_id}`,
          quantity: it.quantity,
          unit_amount: unit,
          total_amount: +(unit * it.quantity).toFixed(2),
        };
      }),
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-3xl p-6 max-h-[90vh] flex flex-col">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Generate Invoice from Fulfilled Orders</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>

        {loading && <p className="text-gray-400 text-sm py-8 text-center">Loading…</p>}
        {error && <p className="text-red-500 text-sm py-4">{error}</p>}

        {!loading && !error && (
          <>
            {items.length === 0 ? (
              <p className="text-gray-400 text-sm py-8 text-center">No uninvoiced fulfilled orders for this supplier.</p>
            ) : (
              <div className="overflow-auto flex-1 mb-4">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 text-left text-xs text-gray-500">
                      <th className="pb-2 pr-2 w-8">
                        <input
                          type="checkbox"
                          checked={selected.size === items.length}
                          onChange={() => setSelected(selected.size === items.length ? new Set() : new Set(items.map((i) => i.order_line_item_id)))}
                        />
                      </th>
                      <th className="pb-2 pr-2">Order</th>
                      <th className="pb-2 pr-2">Product</th>
                      <th className="pb-2 pr-2">SKU</th>
                      <th className="pb-2 pr-2 text-center">Qty</th>
                      <th className="pb-2 pr-2 text-right">Unit Cost ($)</th>
                      <th className="pb-2 text-right">Total</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((it) => {
                      const unit = parseFloat(it.unit_cost_input) || 0;
                      const rowTotal = unit * it.quantity;
                      return (
                        <tr key={it.order_line_item_id} className="border-b border-gray-100 last:border-0">
                          <td className="py-2 pr-2">
                            <input type="checkbox" checked={selected.has(it.order_line_item_id)} onChange={() => toggleItem(it.order_line_item_id)} />
                          </td>
                          <td className="py-2 pr-2 text-xs text-gray-500">
                            #{it.order_id}{it.order_external_id ? <><br /><span className="font-mono">{it.order_external_id}</span></> : ""}
                          </td>
                          <td className="py-2 pr-2">{it.product_name}</td>
                          <td className="py-2 pr-2 font-mono text-xs text-gray-500">{it.sku || "—"}</td>
                          <td className="py-2 pr-2 text-center">{it.quantity}</td>
                          <td className="py-2 pr-2">
                            <input
                              type="number"
                              step="0.01"
                              min="0"
                              className="input text-right w-24"
                              value={it.unit_cost_input}
                              onChange={(e) => updateCost(it.order_line_item_id, e.target.value)}
                            />
                          </td>
                          <td className="py-2 text-right font-medium">${rowTotal.toFixed(2)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

            <div className="border-t border-gray-200 pt-4 space-y-3">
              <div>
                <label className="label">Notes (optional)</label>
                <input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. June 2026 fulfillment" />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-500">{selectedItems.length} item(s) selected</span>
                <span className="font-semibold">Total: ${total.toFixed(2)}</span>
              </div>
              <div className="flex justify-end gap-2">
                <button className="btn-secondary" onClick={onClose}>Cancel</button>
                <button
                  className="btn-primary"
                  disabled={selectedItems.length === 0 || createMut.isPending}
                  onClick={handleSubmit}
                >
                  {createMut.isPending ? "Creating…" : "Create Invoice"}
                </button>
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function FulfillBadge({ status }: { status: string }) {
  const map: Record<string, string> = { unfulfilled: "badge-gray", pending: "badge-yellow", drop_off: "badge-blue", shipped: "badge-green", delivered: "badge-green", cancelled: "badge-red" };
  return <span className={map[status] || "badge-gray"}>{status}</span>;
}

function InvoiceBadge({ status }: { status: string }) {
  const map: Record<string, string> = { pending: "badge-yellow", sent: "badge-blue", paid: "badge-green", overdue: "badge-red" };
  return <span className={map[status] || "badge-gray"}>{status}</span>;
}
