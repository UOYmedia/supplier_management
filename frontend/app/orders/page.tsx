"use client";
import { useState, useRef, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ordersApi, productsApi } from "@/lib/api";
import toast from "react-hot-toast";
import { Plus, ChevronRight, RefreshCw, X, Trash2, Search, Tag, ChevronDown, ChevronUp } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { OrderStatusBadge } from "./order-status-badge";

const STATUSES = ["", "pending", "processing", "partially_fulfilled", "fulfilled", "cancelled"];
const MARKETS = ["", "amazon", "shopify", "manual"];

interface LineItemDraft {
  product_id?: number;
  product_name: string;
  sku: string;
  quantity: number;
  price: string;
  base_cost: string;
}

interface LabelDraft {
  enabled: boolean;
  carrier: string;
  service: string;
  tracking: string;
  cost: string;
}

const emptyLineItem = (): LineItemDraft => ({
  product_name: "",
  sku: "",
  quantity: 1,
  price: "0",
  base_cost: "0",
});

const emptyLabel = (): LabelDraft => ({
  enabled: false,
  carrier: "",
  service: "",
  tracking: "",
  cost: "0",
});

export default function OrdersPage() {
  const [status, setStatus] = useState("");
  const [marketplace, setMarketplace] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  const { data: orders = [], isLoading, refetch } = useQuery({
    queryKey: ["orders", status, marketplace],
    queryFn: () => ordersApi.list({ status: status || undefined, marketplace: marketplace || undefined }),
  });

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Orders</h1>
        <div className="flex gap-2">
          <button className="btn-secondary" onClick={() => refetch()}><RefreshCw className="w-4 h-4" />Refresh</button>
          <button className="btn-primary" onClick={() => setShowCreate(true)}><Plus className="w-4 h-4" />Create Order</button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-3 mb-4">
        <select className="input w-40" value={status} onChange={(e) => setStatus(e.target.value)}>
          {STATUSES.map((s) => <option key={s} value={s}>{s || "All statuses"}</option>)}
        </select>
        <select className="input w-40" value={marketplace} onChange={(e) => setMarketplace(e.target.value)}>
          {MARKETS.map((m) => <option key={m} value={m}>{m || "All channels"}</option>)}
        </select>
      </div>

      <div className="card table-wrapper">
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
      </div>

      {showCreate && (
        <CreateOrderModal onClose={() => setShowCreate(false)} onCreated={() => { setShowCreate(false); refetch(); }} />
      )}
    </div>
  );
}

/**
 * Single input that doubles as catalog search + free-text entry.
 * - onSelect: user picked from suggestions (catalog product)
 * - onChange: user is typing freely (manual name)
 * - selectedProductId: when set, shows a small "catalog" badge
 */
function ProductSearchField({
  value,
  selectedProductId,
  products,
  onSelect,
  onChange,
}: {
  value: string;
  selectedProductId?: number;
  products: any[];
  onSelect: (p: any) => void;
  onChange: (name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const filtered = value.trim()
    ? products.filter((p) =>
        p.name.toLowerCase().includes(value.toLowerCase()) ||
        p.sku.toLowerCase().includes(value.toLowerCase())
      ).slice(0, 20)
    : products.slice(0, 20);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <div className="relative" ref={ref}>
      <div className="relative">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
        <input
          className="input pl-8"
          placeholder="Search catalog or type name…"
          value={value}
          onChange={(e) => { onChange(e.target.value); setOpen(true); }}
          onFocus={() => setOpen(true)}
        />
        {selectedProductId && (
          <span className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] bg-blue-100 text-blue-700 px-1.5 py-0.5 rounded font-medium pointer-events-none">catalog</span>
        )}
      </div>
      {open && filtered.length > 0 && (
        <div className="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-lg shadow-lg max-h-48 overflow-y-auto">
          {filtered.map((p) => (
            <button
              key={p.id}
              type="button"
              className="w-full text-left px-3 py-2 hover:bg-blue-50 border-b border-gray-100 last:border-0"
              onMouseDown={(e) => e.preventDefault()}
              onClick={() => { onSelect(p); setOpen(false); }}
            >
              <div className="text-sm font-medium truncate">{p.name}</div>
              <div className="text-xs text-gray-500 font-mono">{p.sku} · cost ${parseFloat(p.base_cost).toFixed(2)}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function CreateOrderModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: number) => void }) {
  const router = useRouter();
  const [buyerName, setBuyerName] = useState("");
  const [buyerEmail, setBuyerEmail] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [notes, setNotes] = useState("");
  const [addr, setAddr] = useState({ name: "", line1: "", line2: "", city: "", state: "", zip: "", country: "US", phone: "" });
  const [lineItems, setLineItems] = useState<LineItemDraft[]>([emptyLineItem()]);
  const [label, setLabel] = useState<LabelDraft>(emptyLabel());
  const [addrOpen, setAddrOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const { data: products = [] } = useQuery({
    queryKey: ["products-list"],
    queryFn: () => productsApi.list({ limit: 500 }),
    staleTime: 60_000,
  });

  const updateItem = (i: number, patch: Partial<LineItemDraft>) => {
    setLineItems((prev) => prev.map((it, idx) => idx === i ? { ...it, ...patch } : it));
  };

  const selectProduct = (i: number, p: any) => {
    updateItem(i, {
      product_id: p.id,
      product_name: p.name,
      sku: p.sku,
      base_cost: String(parseFloat(p.base_cost) || 0),
    });
  };

  const submit = async () => {
    const validItems = lineItems.filter((it) => it.product_name.trim());
    if (validItems.length === 0) {
      toast.error("Add at least one line item with a product name");
      return;
    }
    if (label.enabled && !label.carrier.trim()) {
      toast.error("Carrier is required for the pre-purchased label");
      return;
    }
    setSubmitting(true);
    try {
      const order = await ordersApi.create({
        marketplace: "manual",
        buyer_name: buyerName || undefined,
        buyer_email: buyerEmail || undefined,
        currency,
        notes: notes || undefined,
        shipping_address: addr.line1 ? addr : undefined,
        line_items: validItems.map((it) => ({
          product_id: it.product_id,
          product_name: it.product_name,
          sku: it.sku || undefined,
          quantity: it.quantity,
          price: parseFloat(it.price) || 0,
          base_cost: parseFloat(it.base_cost) || 0,
        })),
      });

      if (label.enabled && label.carrier.trim()) {
        const allLiIds = (order.line_items ?? []).map((li: any) => li.id);
        await ordersApi.createLabel(order.id, {
          carrier: label.carrier.trim(),
          service: label.service.trim() || undefined,
          tracking_number: label.tracking.trim() || undefined,
          cost: parseFloat(label.cost) || 0,
          line_item_ids: allLiIds,
        });
      }

      toast.success(`Order #${order.id} created`);
      onCreated(order.id);
      router.push(`/orders/${order.id}`);
    } catch (e: any) {
      toast.error(e.response?.data?.detail || "Failed to create order");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 overflow-y-auto py-8 px-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <h2 className="text-lg font-semibold">Create Manual Order</h2>
          <button onClick={onClose} className="p-1.5 hover:bg-gray-100 rounded-lg text-gray-500"><X className="w-4 h-4" /></button>
        </div>

        <div className="px-6 py-5 space-y-5">
          {/* Buyer */}
          <section>
            <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Buyer</h3>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Name</label>
                <input className="input" placeholder="John Doe" value={buyerName} onChange={(e) => setBuyerName(e.target.value)} />
              </div>
              <div>
                <label className="label">Email</label>
                <input className="input" type="email" placeholder="john@example.com" value={buyerEmail} onChange={(e) => setBuyerEmail(e.target.value)} />
              </div>
              <div>
                <label className="label">Currency</label>
                <select className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
                  {["USD", "EUR", "GBP", "CAD", "AUD"].map((c) => <option key={c}>{c}</option>)}
                </select>
              </div>
            </div>
          </section>

          {/* Shipping Address — collapsible */}
          <section>
            <button
              type="button"
              className="flex items-center gap-2 text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1 hover:text-gray-700 w-full"
              onClick={() => setAddrOpen((v) => !v)}
            >
              {addrOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              Shipping Address {addr.line1 && <span className="normal-case font-normal text-gray-400 ml-1">({addr.line1})</span>}
            </button>
            {addrOpen && (
              <div className="grid grid-cols-2 gap-3 mt-2">
                <div className="col-span-2">
                  <label className="label">Full Name</label>
                  <input className="input" placeholder="Recipient name" value={addr.name} onChange={(e) => setAddr({ ...addr, name: e.target.value })} />
                </div>
                <div className="col-span-2">
                  <label className="label">Address Line 1</label>
                  <input className="input" placeholder="123 Main St" value={addr.line1} onChange={(e) => setAddr({ ...addr, line1: e.target.value })} />
                </div>
                <div className="col-span-2">
                  <label className="label">Address Line 2</label>
                  <input className="input" placeholder="Apt, Suite, etc." value={addr.line2} onChange={(e) => setAddr({ ...addr, line2: e.target.value })} />
                </div>
                <div>
                  <label className="label">City</label>
                  <input className="input" value={addr.city} onChange={(e) => setAddr({ ...addr, city: e.target.value })} />
                </div>
                <div>
                  <label className="label">State</label>
                  <input className="input" placeholder="CA" value={addr.state} onChange={(e) => setAddr({ ...addr, state: e.target.value })} />
                </div>
                <div>
                  <label className="label">ZIP</label>
                  <input className="input" value={addr.zip} onChange={(e) => setAddr({ ...addr, zip: e.target.value })} />
                </div>
                <div>
                  <label className="label">Country</label>
                  <input className="input" placeholder="US" value={addr.country} onChange={(e) => setAddr({ ...addr, country: e.target.value })} />
                </div>
                <div>
                  <label className="label">Phone</label>
                  <input className="input" value={addr.phone} onChange={(e) => setAddr({ ...addr, phone: e.target.value })} />
                </div>
              </div>
            )}
          </section>

          {/* Line Items */}
          <section>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Line Items</h3>
              <button className="btn-secondary text-xs py-1" onClick={() => setLineItems((p) => [...p, emptyLineItem()])}>
                <Plus className="w-3 h-3" /> Add Item
              </button>
            </div>
            <div className="space-y-3">
              {lineItems.map((it, i) => (
                <div key={i} className="p-3 bg-gray-50 rounded-lg border border-gray-200">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs font-medium text-gray-500">Item {i + 1}</span>
                    {lineItems.length > 1 && (
                      <button className="p-1 hover:bg-red-50 rounded text-red-400" onClick={() => setLineItems((p) => p.filter((_, idx) => idx !== i))}>
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                  <div className="grid grid-cols-12 gap-2">
                    <div className="col-span-6">
                      <label className="label">Product *</label>
                      <ProductSearchField
                        value={it.product_name}
                        selectedProductId={it.product_id}
                        products={products}
                        onSelect={(p) => selectProduct(i, p)}
                        onChange={(name) => updateItem(i, { product_name: name, product_id: undefined })}
                      />
                    </div>
                    <div className="col-span-4">
                      <label className="label">SKU</label>
                      <input className="input" placeholder="SKU" value={it.sku} onChange={(e) => updateItem(i, { sku: e.target.value })} />
                    </div>
                    <div className="col-span-2">
                      <label className="label">Qty</label>
                      <input className="input" type="number" min={1} value={it.quantity} onChange={(e) => updateItem(i, { quantity: parseInt(e.target.value) || 1 })} />
                    </div>
                    <div className="col-span-5">
                      <label className="label">Sell Price ($)</label>
                      <input className="input" type="number" step="0.01" min={0} value={it.price} onChange={(e) => updateItem(i, { price: e.target.value })} />
                    </div>
                    <div className="col-span-5">
                      <label className="label">Base Cost ($)</label>
                      <input className="input" type="number" step="0.01" min={0} value={it.base_cost} onChange={(e) => updateItem(i, { base_cost: e.target.value })} />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </section>

          {/* Pre-purchased label */}
          <section className="border border-gray-200 rounded-lg overflow-hidden">
            <button
              type="button"
              className={`flex items-center gap-2 w-full px-4 py-3 text-sm font-medium text-left transition-colors ${label.enabled ? "bg-blue-50 text-blue-700" : "bg-gray-50 text-gray-600 hover:bg-gray-100"}`}
              onClick={() => setLabel((l) => ({ ...l, enabled: !l.enabled }))}
            >
              <Tag className="w-4 h-4" />
              Pre-purchased shipping label
              <span className="ml-auto text-xs font-normal text-gray-400">{label.enabled ? "included" : "optional"}</span>
            </button>
            {label.enabled && (
              <div className="px-4 pb-4 pt-3 grid grid-cols-2 gap-3 bg-white">
                <p className="col-span-2 text-xs text-gray-500">
                  Attach a label that was already bought outside the system. All line items will be linked to this label and moved to <strong>pending</strong>.
                </p>
                <div>
                  <label className="label">Carrier *</label>
                  <input className="input" placeholder="USPS, UPS, DHL…" value={label.carrier} onChange={(e) => setLabel((l) => ({ ...l, carrier: e.target.value }))} />
                </div>
                <div>
                  <label className="label">Service</label>
                  <input className="input" placeholder="Priority Mail, Ground…" value={label.service} onChange={(e) => setLabel((l) => ({ ...l, service: e.target.value }))} />
                </div>
                <div>
                  <label className="label">Tracking Number</label>
                  <input className="input" placeholder="1Z…" value={label.tracking} onChange={(e) => setLabel((l) => ({ ...l, tracking: e.target.value }))} />
                </div>
                <div>
                  <label className="label">Label Cost ($)</label>
                  <input className="input" type="number" step="0.01" min={0} value={label.cost} onChange={(e) => setLabel((l) => ({ ...l, cost: e.target.value }))} />
                </div>
              </div>
            )}
          </section>

          {/* Notes */}
          <section>
            <label className="label">Notes</label>
            <textarea className="input h-16 resize-none" placeholder="Internal notes…" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </section>
        </div>

        {/* Footer */}
        <div className="flex justify-end gap-2 px-6 py-4 border-t border-gray-100">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={submit} disabled={submitting}>
            {submitting ? "Creating…" : "Create Order"}
          </button>
        </div>
      </div>
    </div>
  );
}
