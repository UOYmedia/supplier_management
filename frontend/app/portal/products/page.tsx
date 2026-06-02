"use client";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";

export default function PortalProductsPage() {
  const [products, setProducts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("supplier_token");
    fetch("/api/v1/portal/products", { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then(setProducts)
      .catch(() => toast.error("Failed to load products"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-gray-400">Loading…</div>;

  return (
    <div>
      <h1 className="page-title mb-6">My Products</h1>
      {products.length === 0 ? (
        <div className="card p-12 text-center text-gray-400">No products assigned yet.</div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {products.map((p) => (
            <div key={p.product_supplier_id} className="card p-4">
              {p.mockup_url ? (
                <img src={p.mockup_url} alt={p.name} className="w-full h-36 object-contain rounded-lg bg-gray-50 mb-3" />
              ) : (
                <div className="w-full h-36 rounded-lg bg-gray-100 mb-3 flex items-center justify-center text-gray-300 text-xs">No image</div>
              )}
              <div className="font-medium text-sm text-gray-900 line-clamp-2 mb-2">{p.name}</div>
              <div className="text-xs text-gray-500 font-mono mb-2">{p.sku}</div>
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-gray-900">${p.cost.toFixed(2)}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full ${p.stock > 0 ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"}`}>
                  {p.stock > 0 ? `${p.stock} in stock` : "Out of stock"}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
