"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ordersApi } from "@/lib/api";
import toast from "react-hot-toast";
import { Plus, ChevronRight, RefreshCw, X, Trash2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { OrderStatusBadge } from "./order-status-badge";

const STATUSES = ["", "pending", "processing", "partially_fulfilled", "fulfilled", "cancelled"];
const MARKETS = ["", "amazon", "shopify", "manual"];

interface LineItemDraft {
  product_name: string;
  sku: string;
  quantity: number;
  price: string;
  base_cost: string;
}

const emptyLineItem = (): LineItemDraft => ({
  product_name: "",
  sku: "",
  quantity: 1,
  price: "0",
  base_cost: "0",
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

function CreateOrderModal({ onClose, onCreated }: { onClose: () => void; onCreated: (id: number) => void }) {
  const router = useRouter();
  const [buyerName, setBuyerName] = useState("");
  const [buyerEmail, setBuyerEmail] = useState("");
  const [currency, setCurrency] = useState("USD");
  const [notes, setNotes] = useState("");
  const [addr, setAddr] = useState({ name: "", line1: "", line2: "", city: "", state: "", zip: "", country: "US", phone: "" });
  const [lineItems, setLineItems] = useState<LineItemDraft[]>([emptyLineItem()]);

  const createMut = useMutation({
    mutationFn: (data: object) => ordersApi.create(data),
    onSuccess: (order: any) => {
      toast.success(`Order #${order.id} created`);
      onCreated(order.id);
      router.push(`/orders/${order.id}`);
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Failed to create order"),
  });

  const updateItem = (i: number, field: keyof LineItemDraft, value: string | number) => {
    setLineItems((prev) => prev.map((it, idx) => idx === i ? { ...it, [field]: value } : it));
  };

  const submit = () => {
    const validItems = lineItems.filter((it) => it.product_name.trim());
    if (validItems.length === 0) {
      toast.error("Add at least one line item with a product name");
      return;
    }
    createMut.mutate({
      marketplace: "manual",
      buyer_name: buyerName || undefined,
      buyer_email: buyerEmail || undefined,
      currency,
      notes: notes || undefined,
      shipping_address: addr.line1 ? addr : undefined,
      line_items: validItems.map((it) => ({
        product_name: it.product_name,
        sku: it.sku || undefined,
        quantity: it.quantity,
        price: parseFloat(it.price) || 0,
        base_cost: parseFloat(it.base_cost) || 0,
      })),
    });
  };

  return (
    <div className="modal-backdrop">
      <div className="modal max-w-2xl w-full max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Create Manual Order</h2>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded"><X className="w-4 h-4" /></button>
        </div>

        <div className="space-y-4">
          {/* Buyer */}
          <div>
            <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Buyer</h3>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="label">Name</label>
                <input className="input" placeholder="John Doe" value={buyerName} onChange={(e) => setBuyerName(e.target.value)} />
              </div>
              <div>
                <label className="label">Email</label>
                <input className="input" type="email" placeholder="john@example.com" value={buyerEmail} onChange={(e) => setBuyerEmail(e.target.value)} />
              </div>
            </div>
          </div>

          {/* Shipping Address */}
          <div>
            <h3 className="text-xs font-semibold text-gray-500 uppercase mb-2">Shipping Address</h3>
            <div className="grid grid-cols-2 gap-3">
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
              <div>
                <label className="label">Currency</label>
                <select className="input" value={currency} onChange={(e) => setCurrency(e.target.value)}>
                  {["USD", "EUR", "GBP", "CAD", "AUD"].map((c) => <option key={c}>{c}</option>)}
                </select>
              </div>
            </div>
          </div>

          {/* Line Items */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-xs font-semibold text-gray-500 uppercase">Line Items</h3>
              <button className="btn-secondary text-xs py-1" onClick={() => setLineItems((p) => [...p, emptyLineItem()])}>
                <Plus className="w-3 h-3" /> Add Item
              </button>
            </div>
            <div className="space-y-2">
              {lineItems.map((it, i) => (
                <div key={i} className="grid grid-cols-12 gap-2 items-end">
                  <div className="col-span-4">
                    {i === 0 && <label className="label">Product Name *</label>}
                    <input className="input" placeholder="Product name" value={it.product_name} onChange={(e) => updateItem(i, "product_name", e.target.value)} />
                  </div>
                  <div className="col-span-2">
                    {i === 0 && <label className="label">SKU</label>}
                    <input className="input" placeholder="SKU" value={it.sku} onChange={(e) => updateItem(i, "sku", e.target.value)} />
                  </div>
                  <div className="col-span-1">
                    {i === 0 && <label className="label">Qty</label>}
                    <input className="input" type="number" min={1} value={it.quantity} onChange={(e) => updateItem(i, "quantity", parseInt(e.target.value) || 1)} />
                  </div>
                  <div className="col-span-2">
                    {i === 0 && <label className="label">Price</label>}
                    <input className="input" type="number" step="0.01" min={0} value={it.price} onChange={(e) => updateItem(i, "price", e.target.value)} />
                  </div>
                  <div className="col-span-2">
                    {i === 0 && <label className="label">Cost</label>}
                    <input className="input" type="number" step="0.01" min={0} value={it.base_cost} onChange={(e) => updateItem(i, "base_cost", e.target.value)} />
                  </div>
                  <div className="col-span-1 flex justify-end">
                    {lineItems.length > 1 && (
                      <button className="p-1.5 hover:bg-red-50 rounded text-red-400" onClick={() => setLineItems((p) => p.filter((_, idx) => idx !== i))}>
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="label">Notes</label>
            <textarea className="input h-16 resize-none" placeholder="Internal notes…" value={notes} onChange={(e) => setNotes(e.target.value)} />
          </div>
        </div>

        <div className="flex justify-end gap-2 mt-5 pt-4 border-t">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" onClick={submit} disabled={createMut.isPending}>
            {createMut.isPending ? "Creating…" : "Create Order"}
          </button>
        </div>
      </div>
    </div>
  );
}
