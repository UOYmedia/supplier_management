"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ordersApi, suppliersApi } from "@/lib/api";
import toast from "react-hot-toast";
import { Plus, ChevronRight, RefreshCw, X, Trash2, Printer, AlertTriangle } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { OrderStatusBadge } from "./order-status-badge";

const STATUSES = ["", "pending", "processing", "partially_fulfilled", "fulfilled", "cancelled"];
const MARKETS = ["", "amazon", "shopify", "manual"];

interface LineItemDraft {
  product_name: string;
  sku: string;
  quantity: number;
  price: string;
}

const emptyItem = (): LineItemDraft => ({ product_name: "", sku: "", quantity: 1, price: "" });

export default function OrdersPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const page = Number(searchParams.get("page") || "0");
  const limit = 50;

  const [status, setStatus] = useState("");
  const [marketplace, setMarketplace] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [showBulkPrint, setShowBulkPrint] = useState(false);
  const [showDelayed, setShowDelayed] = useState(false);

  const { data: regularOrders = [], isLoading: regularLoading, refetch: refetchRegular } = useQuery({
    queryKey: ["orders", status, marketplace, page],
    queryFn: () => ordersApi.list({ status: status || undefined, marketplace: marketplace || undefined, skip: page * limit, limit }),
  });

  const { data: delayedOrders = [], isLoading: delayedLoading, refetch: refetchDelayed } = useQuery({
    queryKey: ["orders", "delayed"],
    queryFn: () => ordersApi.listDelayed(),
    refetchInterval: 5 * 60 * 1000,
  });

  const orders = showDelayed ? (delayedOrders as any[]) : (regularOrders as any[]);
  const isLoading = showDelayed ? delayedLoading : regularLoading;
  const refetch = showDelayed ? refetchDelayed : refetchRegular;
  const urgentCount = (delayedOrders as any[]).filter((o) => o.status === "urgent").length;

  const hasMore = !showDelayed && (regularOrders as any[]).length === limit;

  // Smart pagination: always show page 1, window of page±1, ellipses for gaps
  const windowStart = Math.max(0, page - 1);
  const windowEnd = hasMore ? page + 1 : page;
  type PageItem = { type: "page"; index: number } | { type: "ellipsis"; key: string };
  const pageItems: PageItem[] = [];
  if (windowStart > 0) {
    pageItems.push({ type: "page", index: 0 });
    if (windowStart > 1) pageItems.push({ type: "ellipsis", key: "pre" });
  }
  for (let i = windowStart; i <= windowEnd; i++) pageItems.push({ type: "page", index: i });
  if (hasMore) pageItems.push({ type: "ellipsis", key: "post" });

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Orders</h1>
        <div className="flex gap-2">
          <button className="btn-secondary" onClick={() => refetch()}><RefreshCw className="w-4 h-4" />Refresh</button>
          <button className="btn-secondary" onClick={() => setShowBulkPrint(true)}><Printer className="w-4 h-4" />Bulk Print</button>
          <button className="btn-primary" onClick={() => setShowCreate(true)}><Plus className="w-4 h-4" />Create Order</button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4">
        <select
          className="input w-40"
          value={status}
          disabled={showDelayed}
          onChange={(e) => { setStatus(e.target.value); router.replace("?page=0"); }}
        >
          {STATUSES.map((s) => <option key={s} value={s}>{s || "All statuses"}</option>)}
        </select>
        <select
          className="input w-40"
          value={marketplace}
          disabled={showDelayed}
          onChange={(e) => { setMarketplace(e.target.value); router.replace("?page=0"); }}
        >
          {MARKETS.map((m) => <option key={m} value={m}>{m || "All channels"}</option>)}
        </select>
        <button
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors ${
            showDelayed
              ? "bg-red-50 border-red-400 text-red-700"
              : "bg-white border-gray-300 text-gray-700 hover:border-gray-400"
          }`}
          onClick={() => { setShowDelayed((v) => !v); router.replace("?page=0"); }}
        >
          <AlertTriangle className="w-4 h-4" />
          Delayed
          {urgentCount > 0 && (
            <span className="ml-0.5 bg-red-500 text-white text-xs font-bold rounded-full px-1.5 py-0.5 min-w-[20px] text-center leading-none">
              {urgentCount}
            </span>
          )}
        </button>
      </div>

      <div className="card table-wrapper">
        {showDelayed ? (
          <table>
            <thead><tr>
              <th>Order</th><th>Supplier</th><th>Label Date</th><th>Days Delayed</th><th>Delay Status</th><th></th>
            </tr></thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={6} className="text-center py-8 text-gray-400">Loading…</td></tr>
              ) : orders.length === 0 ? (
                <tr><td colSpan={6} className="text-center py-8 text-gray-400">No delayed orders.</td></tr>
              ) : orders.map((o: any) => (
                <tr
                  key={`${o.order_id}-${o.purchased_at}`}
                  className={o.status === "urgent" ? "bg-red-50 hover:bg-red-100" : "bg-yellow-50 hover:bg-yellow-100"}
                >
                  <td>
                    <div className="font-medium">#{o.order_id}</div>
                    {o.order_name && o.order_name !== `#${o.order_id}` && (
                      <div className="text-xs text-gray-400 font-mono">{o.order_name}</div>
                    )}
                  </td>
                  <td>{o.supplier_name || "—"}</td>
                  <td className="text-xs text-gray-600">{new Date(o.purchased_at).toLocaleDateString()}</td>
                  <td>
                    <span className={`font-semibold ${o.status === "urgent" ? "text-red-600" : "text-yellow-600"}`}>
                      {o.days_delayed}d
                    </span>
                  </td>
                  <td>
                    {o.status === "urgent" ? (
                      <span className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full bg-red-100 text-red-700">
                        <AlertTriangle className="w-3 h-3" />URGENT
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-xs font-semibold px-2 py-0.5 rounded-full bg-yellow-100 text-yellow-700">
                        <AlertTriangle className="w-3 h-3" />WARNING
                      </span>
                    )}
                  </td>
                  <td>
                    <Link href={`/orders/${o.order_id}`} className="p-1 hover:bg-gray-100 rounded text-gray-500">
                      <ChevronRight className="w-4 h-4" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <table>
            <thead><tr>
              <th>Order ID</th><th>Channel</th><th>Buyer</th><th>Total</th><th>Status</th><th>Items</th><th>Date</th><th></th>
            </tr></thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={8} className="text-center py-8 text-gray-400">Loading…</td></tr>
              ) : orders.length === 0 ? (
                <tr><td colSpan={8} className="text-center py-8 text-gray-400">No orders found.</td></tr>
              ) : orders.map((o: any) => (
                <tr key={o.id}>
                  <td>
                    <div className="font-medium">#{o.id}</div>
                    {o.external_order_id && <div className="text-xs text-gray-400 font-mono">{o.external_order_id}</div>}
                  </td>
                  <td><span className="capitalize badge-gray">{o.marketplace}</span></td>
                  <td>
                    <div>{o.buyer_name || "—"}</div>
                    <div className="text-xs text-gray-400">{o.buyer_email}</div>
                  </td>
                  <td className="font-medium">${parseFloat(o.total).toFixed(2)} <span className="text-xs text-gray-400">{o.currency}</span></td>
                  <td><OrderStatusBadge status={o.status} /></td>
                  <td>{o.line_items?.length ?? 0}</td>
                  <td className="text-xs text-gray-500">{new Date(o.ordered_at).toLocaleDateString()}</td>
                  <td>
                    <Link href={`/orders/${o.id}`} className="p-1 hover:bg-gray-100 rounded text-gray-500">
                      <ChevronRight className="w-4 h-4" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {!showDelayed && (
        <div className="flex items-center justify-between mt-3 px-1">
          <span className="text-sm text-gray-500">
            {(regularOrders as any[]).length > 0
              ? `Showing ${page * limit + 1}–${page * limit + (regularOrders as any[]).length}`
              : !isLoading ? "No orders found" : ""}
          </span>
          <div className="flex items-center gap-1">
            <button className="btn-secondary" disabled={page === 0} onClick={() => router.push(`?page=${page - 1}`)}>
              Previous
            </button>
            {pageItems.map((item) =>
              item.type === "ellipsis" ? (
                <span key={item.key} className="px-2 text-gray-400 select-none">…</span>
              ) : (
                <button
                  key={item.index}
                  className={item.index === page ? "btn-primary" : "btn-secondary"}
                  onClick={() => router.push(`?page=${item.index}`)}
                >
                  {item.index + 1}
                </button>
              )
            )}
            <button className="btn-secondary" disabled={!hasMore} onClick={() => router.push(`?page=${page + 1}`)}>
              Next
            </button>
          </div>
        </div>
      )}

      {showCreate && <CreateOrderModal onClose={() => setShowCreate(false)} />}
      {showBulkPrint && <BulkPrintModal onClose={() => setShowBulkPrint(false)} />}
    </div>
  );
}

function BulkPrintModal({ onClose }: { onClose: () => void }) {
  const today = new Date().toISOString().split("T")[0];
  const [date, setDate] = useState(today);
  const [supplierId, setSupplierId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  const { data: suppliers = [] } = useQuery({
    queryKey: ["suppliers"],
    queryFn: () => suppliersApi.list(),
  });

  const handleDownload = async () => {
    setLoading(true);
    try {
      const params: { date: string; supplier_id?: number } = { date };
      if (supplierId !== null) params.supplier_id = supplierId;

      const blob = await ordersApi.bulkLabels(params);

      const d = new Date(date + "T12:00:00");
      const mon = d.toLocaleString("en-US", { month: "short" }).toUpperCase();
      const dateLabel = `${mon} ${d.getDate()}`;

      let filename: string;
      if (supplierId !== null) {
        const sup = (suppliers as any[]).find((s) => s.id === supplierId);
        filename = `${dateLabel} – ${sup?.name?.toUpperCase() ?? "SUPPLIER"}.pdf`;
      } else {
        filename = `${dateLabel} – labels.zip`;
      }

      const mimeType = supplierId !== null ? "application/pdf" : "application/zip";
      const url = URL.createObjectURL(new Blob([blob], { type: mimeType }));
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      onClose();
    } catch (e: any) {
      const status = e.response?.status;
      toast.error(status === 404 ? "No labels found for this date/supplier" : "Download failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="card w-full max-w-sm p-6">
        <div className="flex items-center justify-between mb-5">
          <h2 className="font-semibold text-lg">Bulk Print Labels</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="label">Date</label>
            <input
              type="date"
              className="input"
              value={date}
              onChange={(e) => setDate(e.target.value)}
            />
          </div>
          <div>
            <label className="label">Supplier</label>
            <select
              className="input"
              value={supplierId ?? ""}
              onChange={(e) => setSupplierId(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">All suppliers (zip)</option>
              {(suppliers as any[]).map((s) => (
                <option key={s.id} value={s.id}>{s.name}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-6">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={handleDownload} disabled={loading || !date}>
            {loading ? "Preparing…" : "Download"}
          </button>
        </div>
      </div>
    </div>
  );
}


function CreateOrderModal({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const qc = useQueryClient();

  // Buyer
  const [buyerName, setBuyerName] = useState("");
  const [buyerEmail, setBuyerEmail] = useState("");
  const [notes, setNotes] = useState("");
  const [currency, setCurrency] = useState("USD");

  // Shipping address
  const [addrName, setAddrName] = useState("");
  const [line1, setLine1] = useState("");
  const [line2, setLine2] = useState("");
  const [city, setCity] = useState("");
  const [addrState, setAddrState] = useState("");
  const [zip, setZip] = useState("");
  const [country, setCountry] = useState("US");
  const [phone, setPhone] = useState("");

  // Line items
  const [items, setItems] = useState<LineItemDraft[]>([emptyItem()]);

  const updateItem = (i: number, field: keyof LineItemDraft, value: string | number) => {
    setItems((prev) => prev.map((it, idx) => idx === i ? { ...it, [field]: value } : it));
  };
  const addItem = () => setItems((prev) => [...prev, emptyItem()]);
  const removeItem = (i: number) => setItems((prev) => prev.filter((_, idx) => idx !== i));

  const total = items.reduce((s, it) => s + (parseFloat(it.price) || 0) * it.quantity, 0);

  const mut = useMutation({
    mutationFn: (data: object) => ordersApi.create(data),
    onSuccess: (order: any) => {
      qc.invalidateQueries({ queryKey: ["orders"] });
      toast.success("Order created");
      onClose();
      router.push(`/orders/${order.id}`);
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Failed to create order"),
  });

  const handleSubmit = () => {
    const validItems = items.filter((it) => it.product_name.trim() && it.price);
    if (validItems.length === 0) {
      toast.error("Add at least one line item with a name and price");
      return;
    }
    const hasAddr = line1.trim() || city.trim();
    mut.mutate({
      marketplace: "manual",
      buyer_name: buyerName || undefined,
      buyer_email: buyerEmail || undefined,
      currency,
      notes: notes || undefined,
      shipping_address: hasAddr ? {
        name: addrName || buyerName || undefined,
        line1: line1 || undefined,
        line2: line2 || undefined,
        city: city || undefined,
        state: addrState || undefined,
        zip: zip || undefined,
        country: country || undefined,
        phone: phone || undefined,
      } : undefined,
      line_items: validItems.map((it) => ({
        product_name: it.product_name.trim(),
        sku: it.sku.trim() || undefined,
        quantity: it.quantity,
        price: parseFloat(it.price),
        base_cost: 0,
      })),
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="card w-full max-w-2xl max-h-[92vh] overflow-y-auto p-6">
        {/* Header */}
        <div className="flex items-center justify-between mb-5">
          <h2 className="font-semibold text-lg">Create Custom Order</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>

        <div className="space-y-5">
          {/* Buyer */}
          <section>
            <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Buyer</div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Name</label>
                <input className="input" value={buyerName} onChange={(e) => setBuyerName(e.target.value)} placeholder="John Smith" />
              </div>
              <div>
                <label className="label">Email</label>
                <input className="input" type="email" value={buyerEmail} onChange={(e) => setBuyerEmail(e.target.value)} placeholder="john@example.com" />
              </div>
            </div>
          </section>

          {/* Shipping address */}
          <section>
            <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Shipping Address <span className="font-normal text-gray-400">(optional)</span></div>
            <div className="grid grid-cols-2 gap-3">
              <div className="col-span-2">
                <label className="label">Recipient Name</label>
                <input className="input" value={addrName} onChange={(e) => setAddrName(e.target.value)} placeholder="Same as buyer" />
              </div>
              <div className="col-span-2">
                <label className="label">Address Line 1</label>
                <input className="input" value={line1} onChange={(e) => setLine1(e.target.value)} placeholder="123 Main St" />
              </div>
              <div className="col-span-2">
                <label className="label">Address Line 2</label>
                <input className="input" value={line2} onChange={(e) => setLine2(e.target.value)} placeholder="Apt, Suite, etc." />
              </div>
              <div>
                <label className="label">City</label>
                <input className="input" value={city} onChange={(e) => setCity(e.target.value)} />
              </div>
              <div>
                <label className="label">State / Province</label>
                <input className="input" value={addrState} onChange={(e) => setAddrState(e.target.value)} placeholder="CA" />
              </div>
              <div>
                <label className="label">ZIP / Postal Code</label>
                <input className="input" value={zip} onChange={(e) => setZip(e.target.value)} />
              </div>
              <div>
                <label className="label">Country</label>
                <input className="input" value={country} onChange={(e) => setCountry(e.target.value)} placeholder="US" />
              </div>
              <div>
                <label className="label">Phone</label>
                <input className="input" value={phone} onChange={(e) => setPhone(e.target.value)} />
              </div>
            </div>
          </section>

          {/* Line items */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Line Items</div>
              <button className="btn-secondary text-xs py-1" onClick={addItem}><Plus className="w-3 h-3" />Add Item</button>
            </div>
            <div className="space-y-2">
              {/* Header row */}
              <div className="grid grid-cols-[1fr_120px_70px_90px_32px] gap-2 text-xs text-gray-400 font-medium px-1">
                <span>Product Name *</span><span>SKU</span><span>Qty</span><span>Price *</span><span></span>
              </div>
              {items.map((it, i) => (
                <div key={i} className="grid grid-cols-[1fr_120px_70px_90px_32px] gap-2 items-center">
                  <input
                    className="input text-sm"
                    value={it.product_name}
                    onChange={(e) => updateItem(i, "product_name", e.target.value)}
                    placeholder="Product name"
                  />
                  <input
                    className="input text-sm font-mono"
                    value={it.sku}
                    onChange={(e) => updateItem(i, "sku", e.target.value)}
                    placeholder="SKU"
                  />
                  <input
                    className="input text-sm"
                    type="number"
                    min={1}
                    value={it.quantity}
                    onChange={(e) => updateItem(i, "quantity", Math.max(1, parseInt(e.target.value) || 1))}
                  />
                  <input
                    className="input text-sm"
                    type="number"
                    min={0}
                    step="0.01"
                    value={it.price}
                    onChange={(e) => updateItem(i, "price", e.target.value)}
                    placeholder="0.00"
                  />
                  <button
                    className="p-1 text-gray-400 hover:text-red-500 disabled:opacity-30"
                    disabled={items.length === 1}
                    onClick={() => removeItem(i)}
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          </section>

          {/* Notes + currency */}
          <section className="grid grid-cols-2 gap-3">
            <div>
              <label className="label">Currency</label>
              <select className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
                {["USD", "EUR", "GBP", "CAD", "AUD"].map((c) => <option key={c}>{c}</option>)}
              </select>
            </div>
            <div>
              <label className="label">Notes <span className="text-gray-400 font-normal">(internal)</span></label>
              <input className="input" value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional notes" />
            </div>
          </section>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between mt-6 pt-4 border-t border-gray-100">
          <div className="text-sm font-semibold text-gray-700">
            Total: <span className="text-gray-900">${total.toFixed(2)} {currency}</span>
          </div>
          <div className="flex gap-2">
            <button className="btn-secondary" onClick={onClose}>Cancel</button>
            <button className="btn-primary" onClick={handleSubmit} disabled={mut.isPending}>
              {mut.isPending ? "Creating…" : "Create Order"}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
