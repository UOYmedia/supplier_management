"use client";
import { useEffect, useState } from "react";
import toast from "react-hot-toast";
import { Package } from "lucide-react";

export default function PortalProductsPage() {
  const [products, setProducts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  useEffect(() => {
    const token = localStorage.getItem("supplier_token");
    fetch("/api/v1/portal/products", { headers: { Authorization: `Bearer ${token}` } })
      .then((r) => { if (!r.ok) throw new Error(); return r.json(); })
      .then(setProducts)
      .catch(() => toast.error("Failed to load catalog"))
      .finally(() => setLoading(false));
  }, []);

  const filtered = products.filter((p) =>
    p.name.toLowerCase().includes(search.toLowerCase()) ||
    p.sku.toLowerCase().includes(search.toLowerCase())
  );

  if (loading) return <div className="text-gray-400 p-6">Loading…</div>;

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">My Catalog</h1>
        <span className="text-sm text-gray-400">{products.length} products</span>
      </div>

      <input
        className="input w-64 mb-4"
        placeholder="Search by name or SKU…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
      />

      {filtered.length === 0 ? (
        <div className="card p-12 text-center text-gray-400">
          <Package className="w-10 h-10 mx-auto mb-3 opacity-30" />
          {products.length === 0 ? "No products in your catalog yet." : "No results found."}
        </div>
      ) : (
        <div className="card table-wrapper">
          <table>
            <thead>
              <tr>
                <th>Product</th>
                <th>SKU</th>
                <th>Unit Price</th>
                <th>Stock</th>
                <th>Dimensions (L×W×H in)</th>
                <th>Weight (oz)</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p) => (
                <tr key={p.id}>
                  <td className="font-medium">{p.name}</td>
                  <td className="font-mono text-xs text-gray-500">{p.sku}</td>
                  <td className="font-semibold">${p.unit_price.toFixed(2)}</td>
                  <td>
                    <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                      p.stock_quantity > 0 ? "bg-green-100 text-green-700" : "bg-red-100 text-red-600"
                    }`}>
                      {p.stock_quantity > 0 ? `${p.stock_quantity} in stock` : "Out of stock"}
                    </span>
                  </td>
                  <td className="text-sm text-gray-500">
                    {p.length && p.width && p.height
                      ? `${p.length} × ${p.width} × ${p.height}`
                      : "—"}
                  </td>
                  <td className="text-sm text-gray-500">{p.weight ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
