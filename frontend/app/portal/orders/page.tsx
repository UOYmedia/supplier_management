"use client";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";
import { Printer, CheckCircle, ChevronDown, ChevronUp, Package } from "lucide-react";

const STATUS_COLORS: Record<string, string> = {
  unfulfilled: "badge-yellow",
  pending: "badge-yellow",
  shipped: "badge-blue",
  delivered: "badge-green",
  cancelled: "badge-red",
};

interface LineItem {
  line_item_id: number;
  order_id: number;
  external_order_id: string | null;
  marketplace: string;
  ordered_at: string;
  buyer_name: string | null;
  shipping_address: any;
  product_name: string;
  sku: string | null;
  quantity: number;
  fulfill_status: string;
  tracking_number: string | null;
  label_url: string | null;
  fulfilled_at: string | null;
}

export default function PortalOrdersPage() {
  const [items, setItems] = useState<LineItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("unfulfilled");
  const [expandedOrder, setExpandedOrder] = useState<number | null>(null);
  const [shipping, setShipping] = useState<Record<number, string>>({});

  const load = () => {
    const token = localStorage.getItem("supplier_token");
    const q = filter ? `?status=${filter}` : "";
    fetch(`/api/v1/portal/orders${q}`, { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then(setItems)
      .catch(() => toast.error("Failed to load orders"))
      .finally(() => setLoading(false));
  };

  useEffect(() => { setLoading(true); load(); }, [filter]);

  const markShipped = async (itemId: number) => {
    const token = localStorage.getItem("supplier_token");
    const tracking = shipping[itemId] || "";
    const resp = await fetch(`/api/v1/portal/orders/${itemId}/ship`, {
      method: "PATCH",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ tracking_number: tracking }),
    });
    if (resp.ok) {
      toast.success("Marked as shipped");
      load();
    } else {
      toast.error("Failed to update");
    }
  };

  const printLabel = (url: string) => {
    if (!url) { toast.error("No label available"); return; }
    window.open(url, "_blank");
  };

  const addrText = (a: any) =>
    a ? [a.name, a.line1, a.line2, a.city, a.state, a.zip, a.country].filter(Boolean).join(", ") : "—";

  if (loading) return <div className="text-gray-400">Loading…</div>;

  // Group items by order_id
  const orderGroups = items.reduce((acc, item) => {
    const key = item.order_id;
    if (!acc[key]) acc[key] = [];
    acc[key].push(item);
    return acc;
  }, {} as Record<number, LineItem[]>);

  const orderIds = Object.keys(orderGroups).map(Number);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="page-title">Orders to Fulfill</h1>
        <div className="flex gap-2">
          {["unfulfilled", "pending", "shipped", ""].map((s) => (
            <button key={s} onClick={() => setFilter(s)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${filter === s ? "bg-blue-600 text-white" : "bg-white border border-gray-200 text-gray-600 hover:bg-gray-50"}`}>
              {s === "" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {orderIds.length === 0 ? (
        <div className="card p-12 text-center text-gray-400">No orders found.</div>
      ) : (
        <div className="space-y-3">
          {orderIds.map((orderId) => {
            const orderItems = orderGroups[orderId];
            const first = orderItems[0];
            const isExpanded = expandedOrder === orderId;
            const allShipped = orderItems.every((i) => i.fulfill_status === "shipped" || i.fulfill_status === "delivered");
            const someShipped = orderItems.some((i) => i.fulfill_status === "shipped" || i.fulfill_status === "delivered");

            return (
              <div key={orderId} className="card overflow-hidden">
                {/* Order header */}
                <div
                  className="p-4 flex items-center gap-4 cursor-pointer hover:bg-gray-50 transition-colors"
                  onClick={() => setExpandedOrder(isExpanded ? null : orderId)}
                >
                  <Package className="w-4 h-4 text-gray-400 shrink-0" />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-semibold text-sm">Order #{orderId}</span>
                      {first.external_order_id && (
                        <span className="text-xs text-gray-400 font-mono">{first.external_order_id}</span>
                      )}
                      <span className="text-xs text-gray-400 capitalize">{first.marketplace}</span>
                      <span className={`badge text-xs ${allShipped ? "badge-green" : someShipped ? "badge-blue" : "badge-yellow"}`}>
                        {allShipped ? "All shipped" : someShipped ? "Partial" : "Pending"}
                      </span>
                    </div>
                    <div className="text-xs text-gray-500 mt-0.5">
                      {orderItems.length} item(s) · {first.buyer_name || "—"} · {new Date(first.ordered_at).toLocaleDateString()}
                    </div>
                  </div>
                  <button className="p-1.5 hover:bg-gray-100 rounded text-gray-400 shrink-0">
                    {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                  </button>
                </div>

                {/* Expanded order items */}
                {isExpanded && (
                  <div className="border-t border-gray-100">
                    {/* Ship-to address */}
                    <div className="px-4 py-3 bg-gray-50 text-xs text-gray-600">
                      <span className="font-medium text-gray-500 uppercase mr-2">Ship to:</span>
                      {addrText(first.shipping_address)}
                    </div>

                    {/* Items */}
                    <div className="divide-y divide-gray-100">
                      {orderItems.map((item) => (
                        <div key={item.line_item_id} className="p-4">
                          <div className="flex items-start gap-3">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-2 mb-1">
                                <span className="font-medium text-sm">{item.product_name}</span>
                                {item.sku && <span className="text-xs text-gray-400 font-mono">{item.sku}</span>}
                                <span className={`badge text-xs ${STATUS_COLORS[item.fulfill_status] || "badge-gray"}`}>
                                  {item.fulfill_status}
                                </span>
                              </div>
                              <div className="text-xs text-gray-500">Qty: {item.quantity}</div>

                              {item.tracking_number && (
                                <div className="mt-1 text-xs text-gray-600">
                                  <span className="font-medium">Tracking:</span>{" "}
                                  <span className="font-mono">{item.tracking_number}</span>
                                </div>
                              )}
                            </div>

                            <div className="flex items-center gap-2 shrink-0">
                              {item.label_url && (
                                <button
                                  onClick={() => printLabel(item.label_url!)}
                                  className="btn-secondary text-xs py-1.5"
                                >
                                  <Printer className="w-3 h-3" /> Print Label
                                </button>
                              )}
                            </div>
                          </div>

                          {/* Ship action */}
                          {item.fulfill_status !== "shipped" && item.fulfill_status !== "delivered" && item.fulfill_status !== "cancelled" && (
                            <div className="flex gap-2 items-center mt-3">
                              <input
                                className="input flex-1 text-sm"
                                placeholder="Tracking number (optional)"
                                value={shipping[item.line_item_id] || ""}
                                onChange={(e) => setShipping((p) => ({ ...p, [item.line_item_id]: e.target.value }))}
                              />
                              <button
                                onClick={() => markShipped(item.line_item_id)}
                                className="btn-primary text-sm py-2 whitespace-nowrap"
                              >
                                <CheckCircle className="w-4 h-4" /> Mark Shipped
                              </button>
                            </div>
                          )}

                          {(item.fulfill_status === "shipped" || item.fulfill_status === "delivered") && item.fulfilled_at && (
                            <div className="mt-2 text-xs text-green-600">
                              Shipped on {new Date(item.fulfilled_at).toLocaleString()}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
