"use client";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";
import { Package } from "lucide-react";

interface CatalogItem {
  id: number;
  name: string;
  short_name: string | null;
  sku: string;
  unit_price: number;
  stock_quantity: number;
  image_url: string | null;
}

export default function PortalProductsPage() {
  const [products, setProducts] = useState<CatalogItem[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("supplier_token");
    fetch("/api/v1/portal/products", { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then(setProducts)
      .catch(() => toast.error("Failed to load catalog"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="text-gray-400">Loading…</div>;

  return (
    <div>
      <h1 className="page-title mb-6">My Catalog</h1>
      {products.length === 0 ? (
        <div className="card p-12 text-center text-gray-400">No catalog items yet.</div>
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          {products.map((p) => (
            <div key={p.id} className="card p-4">
              {p.image_url ? (
                <img src={p.image_url} alt={p.name} className="w-full h-36 object-contain rounded-lg bg-gray-50 mb-3" />
              ) : (
                <div className="w-full h-36 rounded-lg bg-gray-100 mb-3 flex items-center justify-center text-gray-300">
                  <Package className="w-8 h-8" />
                </div>
              )}
              <div className="font-medium text-sm text-gray-900 line-clamp-2 mb-1">{p.name}</div>
              {p.short_name && <div className="text-xs font-semibold text-blue-600 mb-1">"{p.short_name}"</div>}
              <div className="text-xs text-gray-500 font-mono mb-2">{p.sku}</div>
              <div className="flex items-center justify-between">
                <span className="text-sm font-semibold text-gray-900">${(p.unit_price ?? 0).toFixed(2)}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full ${p.stock_quantity > 0 ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"}`}>
                  {p.stock_quantity > 0 ? `${p.stock_quantity} in stock` : "Out of stock"}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
