"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { marketplaceApi, productsApi } from "@/lib/api";
import toast from "react-hot-toast";
import { ArrowLeft, Wand2, Link2, X, Check, AlertCircle } from "lucide-react";
import Link from "next/link";

export default function ListingsMappingPage() {
  const qc = useQueryClient();
  const [filter, setFilter] = useState<"all" | "unlinked">("all");
  const [linkTarget, setLinkTarget] = useState<any>(null);

  const { data: listings = [], isLoading } = useQuery({
    queryKey: ["listings", filter],
    queryFn: () => marketplaceApi.listListings(filter === "unlinked" ? { unlinked: true } : {}),
  });

  const { data: connections = [] } = useQuery({
    queryKey: ["connections"],
    queryFn: marketplaceApi.listConnections,
  });

  const connMap = Object.fromEntries(connections.map((c: any) => [c.id, c]));

  const autoMapMut = useMutation({
    mutationFn: marketplaceApi.autoMap,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["listings"] });
      toast.success(`Auto-mapped ${data.mapped} listing${data.mapped !== 1 ? "s" : ""}${data.unmatched.length ? ` — ${data.unmatched.length} unmatched` : ""}`);
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Auto-map failed"),
  });

  const unlinkedCount = listings.filter((l: any) => !l.product_id).length;

  return (
    <div>
      <div className="page-header">
        <div className="flex items-center gap-3">
          <Link href="/marketplace" className="text-gray-400 hover:text-gray-600">
            <ArrowLeft className="w-5 h-5" />
          </Link>
          <h1 className="page-title">Listings Mapping</h1>
          {unlinkedCount > 0 && (
            <span className="badge badge-yellow text-xs">{unlinkedCount} unlinked</span>
          )}
        </div>
        <button
          className="btn-primary flex items-center gap-1"
          onClick={() => autoMapMut.mutate()}
          disabled={autoMapMut.isPending}
        >
          <Wand2 className="w-4 h-4" />
          {autoMapMut.isPending ? "Mapping…" : "Auto-Map by SKU"}
        </button>
      </div>

      <div className="mb-4 flex gap-2">
        <button
          className={`px-3 py-1.5 rounded text-sm font-medium ${filter === "all" ? "bg-gray-900 text-white" : "bg-white border text-gray-600 hover:bg-gray-50"}`}
          onClick={() => setFilter("all")}
        >
          All listings
        </button>
        <button
          className={`px-3 py-1.5 rounded text-sm font-medium ${filter === "unlinked" ? "bg-gray-900 text-white" : "bg-white border text-gray-600 hover:bg-gray-50"}`}
          onClick={() => setFilter("unlinked")}
        >
          Unlinked only
        </button>
      </div>

      <div className="card overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-gray-400 text-sm">Loading…</div>
        ) : listings.length === 0 ? (
          <div className="p-8 text-center text-gray-400">
            <p>{filter === "unlinked" ? "All listings are linked to products." : "No listings found. Sync listings from Marketplace connections first."}</p>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b bg-gray-50">
                <th className="px-4 py-2.5 text-left font-medium text-gray-500">Platform</th>
                <th className="px-4 py-2.5 text-left font-medium text-gray-500">SKU</th>
                <th className="px-4 py-2.5 text-left font-medium text-gray-500">Title</th>
                <th className="px-4 py-2.5 text-left font-medium text-gray-500">Status</th>
                <th className="px-4 py-2.5 text-left font-medium text-gray-500">Linked Product</th>
                <th className="px-4 py-2.5 text-left font-medium text-gray-500"></th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {listings.map((listing: any) => {
                const conn = connMap[listing.connection_id];
                const isLinked = !!listing.product_id;
                return (
                  <tr key={listing.id} className={isLinked ? "" : "bg-yellow-50/40"}>
                    <td className="px-4 py-2.5">
                      <span className={`badge text-xs ${conn?.marketplace === "amazon" ? "badge-blue" : "badge-green"}`}>
                        {conn?.marketplace || "—"}
                      </span>
                    </td>
                    <td className="px-4 py-2.5 font-mono text-xs">{listing.marketplace_sku || "—"}</td>
                    <td className="px-4 py-2.5 text-gray-700 max-w-xs truncate">{listing.title || "—"}</td>
                    <td className="px-4 py-2.5">
                      <span className={`badge text-xs ${listing.status === "active" ? "badge-green" : "badge-gray"}`}>
                        {listing.status}
                      </span>
                    </td>
                    <td className="px-4 py-2.5">
                      {isLinked ? (
                        <div className="flex items-center gap-1.5 text-green-700">
                          <Check className="w-3.5 h-3.5" />
                          <span className="font-medium">{listing.product_name}</span>
                          <span className="text-gray-400 font-mono text-xs">({listing.product_sku})</span>
                        </div>
                      ) : (
                        <div className="flex items-center gap-1 text-yellow-600">
                          <AlertCircle className="w-3.5 h-3.5" />
                          <span>Not linked</span>
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <button
                        className="btn-secondary text-xs py-1 px-2"
                        onClick={() => setLinkTarget(listing)}
                      >
                        <Link2 className="w-3 h-3" /> {isLinked ? "Change" : "Link"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {linkTarget && (
        <LinkProductModal
          listing={linkTarget}
          onClose={() => setLinkTarget(null)}
          onSaved={() => { qc.invalidateQueries({ queryKey: ["listings"] }); setLinkTarget(null); }}
        />
      )}
    </div>
  );
}

function LinkProductModal({ listing, onClose, onSaved }: { listing: any; onClose: () => void; onSaved: () => void }) {
  const [search, setSearch] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(listing.product_id || null);

  const { data: products = [] } = useQuery({
    queryKey: ["products"],
    queryFn: () => productsApi.list(),
  });

  const filtered = products.filter(
    (p: any) =>
      p.name.toLowerCase().includes(search.toLowerCase()) ||
      p.sku.toLowerCase().includes(search.toLowerCase())
  );

  const mut = useMutation({
    mutationFn: () => marketplaceApi.updateListing(listing.id, { product_id: selectedId }),
    onSuccess: () => { toast.success("Listing linked"); onSaved(); },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Failed"),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Link listing to product</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <div className="text-xs text-gray-500 mb-3">
          Listing: <span className="font-mono">{listing.marketplace_sku}</span> — {listing.title}
        </div>
        <input
          className="input mb-3"
          placeholder="Search products by name or SKU…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          autoFocus
        />
        <div className="border rounded max-h-64 overflow-y-auto divide-y">
          {filtered.length === 0 ? (
            <div className="p-4 text-center text-sm text-gray-400">No products found</div>
          ) : (
            filtered.map((p: any) => (
              <button
                key={p.id}
                className={`w-full text-left px-3 py-2.5 hover:bg-gray-50 flex items-center justify-between ${selectedId === p.id ? "bg-blue-50" : ""}`}
                onClick={() => setSelectedId(p.id)}
              >
                <div>
                  <div className="font-medium text-sm">{p.name}</div>
                  <div className="text-xs text-gray-400 font-mono">{p.sku}</div>
                </div>
                {selectedId === p.id && <Check className="w-4 h-4 text-blue-600" />}
              </button>
            ))
          )}
        </div>
        {listing.product_id && (
          <button
            className="mt-2 text-xs text-red-500 hover:underline"
            onClick={() => setSelectedId(null)}
          >
            Remove link
          </button>
        )}
        <div className="flex justify-end gap-2 mt-4">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button
            className="btn-primary"
            disabled={mut.isPending}
            onClick={() => mut.mutate()}
          >
            Save
          </button>
        </div>
      </div>
    </div>
  );
}
