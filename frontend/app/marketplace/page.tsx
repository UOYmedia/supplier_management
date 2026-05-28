"use client";
import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { marketplaceApi } from "@/lib/api";
import toast from "react-hot-toast";
import { Plus, RefreshCw, Zap, Trash2, CheckCircle, XCircle, X, Package, Link2, MapPin, List, Pencil } from "lucide-react";
import NextLink from "next/link";

export default function MarketplacePage() {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [editConn, setEditConn] = useState<any>(null);

  const { data: connections = [], isLoading } = useQuery({ queryKey: ["connections"], queryFn: marketplaceApi.listConnections });

  // Handle return from Shopify OAuth
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("connected") === "shopify") {
      toast.success("Shopify connected successfully!");
      qc.invalidateQueries({ queryKey: ["connections"] });
      window.history.replaceState({}, "", "/marketplace");
    } else if (params.get("error")) {
      toast.error(decodeURIComponent(params.get("error") || "Shopify connection failed"));
      window.history.replaceState({}, "", "/marketplace");
    }
  }, []);

  const deleteMut = useMutation({
    mutationFn: (id: number) => marketplaceApi.deleteConnection(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["connections"] }); toast.success("Deleted"); },
  });

  const testMut = useMutation({
    mutationFn: (id: number) => marketplaceApi.testConnection(id),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["connections"] });
      toast[data.success ? "success" : "error"](data.success ? "Connection OK" : "Connection failed");
    },
  });

  const syncOrdersMut = useMutation({
    mutationFn: (id: number) => marketplaceApi.syncOrders(id),
    onSuccess: () => toast.success("Order sync started"),
  });

  const syncProductsMut = useMutation({
    mutationFn: (id: number) => marketplaceApi.syncProducts(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["products"] }); toast.success("Product sync started"); },
  });

  const syncLocationsMut = useMutation({
    mutationFn: (id: number) => marketplaceApi.syncLocations(id),
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ["suppliers"] });
      toast.success(`Locations synced — ${data.created} created, ${data.updated} updated`);
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Location sync failed"),
  });

  const syncListingsMut = useMutation({
    mutationFn: (id: number) => marketplaceApi.syncListings(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["listings"] }); toast.success("Listing sync started"); },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Listing sync failed"),
  });

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Marketplace Connections</h1>
        <div className="flex gap-2">
          <NextLink href="/marketplace/listings" className="btn-secondary flex items-center gap-1 text-sm">
            <List className="w-4 h-4" /> Listings Mapping
          </NextLink>
          <button className="btn-primary" onClick={() => setShowCreate(true)}>
            <Plus className="w-4 h-4" /> Add Connection
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="text-gray-400 text-sm">Loading…</div>
      ) : connections.length === 0 ? (
        <div className="card p-12 text-center text-gray-400">
          <p className="text-lg mb-2">No marketplace connections yet</p>
          <p className="text-sm">Connect Amazon or Shopify to sync listings and orders.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {connections.map((c: any) => (
            <ConnectionCard key={c.id} conn={c}
              onTest={() => testMut.mutate(c.id)}
              onEdit={() => setEditConn(c)}
              onSyncOrders={() => syncOrdersMut.mutate(c.id)}
              onSyncProducts={() => syncProductsMut.mutate(c.id)}
              onSyncLocations={() => syncLocationsMut.mutate(c.id)}
              onSyncListings={() => syncListingsMut.mutate(c.id)}
              onDelete={() => confirm("Delete?") && deleteMut.mutate(c.id)}
            />
          ))}
        </div>
      )}

      {showCreate && <ConnectionModal onClose={() => setShowCreate(false)} />}
      {editConn && <ConnectionModal conn={editConn} onClose={() => setEditConn(null)} />}
    </div>
  );
}

function ConnectionCard({ conn, onTest, onEdit, onSyncOrders, onSyncProducts, onSyncLocations, onSyncListings, onDelete }: any) {
  const statusIcon = conn.status === "active" ? (
    <CheckCircle className="w-4 h-4 text-green-500" />
  ) : conn.status === "error" ? (
    <XCircle className="w-4 h-4 text-red-500" />
  ) : (
    <div className="w-4 h-4 rounded-full border-2 border-gray-300" />
  );

  return (
    <div className="card p-5">
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2">
            {statusIcon}
            <span className="font-semibold">{conn.name}</span>
          </div>
          <div className="text-xs text-gray-500 capitalize mt-0.5">{conn.marketplace}</div>
        </div>
        <span className={`badge text-xs ${conn.status === "active" ? "badge-green" : conn.status === "error" ? "badge-red" : "badge-gray"}`}>
          {conn.status}
        </span>
      </div>
      {conn.shop_url && <div className="text-xs text-gray-400 mb-3 truncate">{conn.shop_url}</div>}
      {conn.error_message && (
        <div className="text-xs text-red-500 bg-red-50 rounded p-2 mb-3">{conn.error_message}</div>
      )}
      <div className="text-xs text-gray-400 mb-4">
        Last synced: {conn.last_synced_at ? new Date(conn.last_synced_at).toLocaleString() : "Never"}
      </div>
      <div className="flex flex-wrap gap-2">
        <button className="btn-secondary text-xs py-1 flex-1" onClick={onTest}>
          <Zap className="w-3 h-3" /> Test
        </button>
        <button className="btn-secondary text-xs py-1 flex-1" onClick={onSyncOrders}>
          <RefreshCw className="w-3 h-3" /> Sync Orders
        </button>
        <button className="btn-secondary text-xs py-1 flex-1" onClick={onSyncProducts}>
          <Package className="w-3 h-3" /> Sync Products
        </button>
        {conn.marketplace === "shopify" && (
          <button className="btn-secondary text-xs py-1 flex-1" onClick={onSyncLocations}>
            <MapPin className="w-3 h-3" /> Sync Locations
          </button>
        )}
        {conn.marketplace === "amazon" && (
          <button className="btn-secondary text-xs py-1 flex-1" onClick={onSyncListings}>
            <List className="w-3 h-3" /> Sync Listings
          </button>
        )}
        <button className="p-1.5 hover:text-blue-500 text-gray-400" onClick={onEdit} title="Edit">
          <Pencil className="w-4 h-4" />
        </button>
        <button className="p-1.5 hover:text-red-500 text-gray-400" onClick={onDelete} title="Delete">
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

// Extract the bare .myshopify.com domain from whatever the user typed
function toShopDomain(raw: string): string {
  return raw.replace(/^https?:\/\//, "").replace(/\/$/, "").toLowerCase();
}

function ConnectionModal({ onClose, conn }: { onClose: () => void; conn?: any }) {
  const qc = useQueryClient();
  const isShopify = conn ? conn.marketplace === "shopify" : true; // new connections default to shopify
  const creds = conn?.credentials ?? {};

  const [marketplace, setMarketplace] = useState<string>(conn?.marketplace ?? "shopify");
  const [name, setName] = useState(conn?.name ?? "");
  const [shopUrl, setShopUrl] = useState(conn?.shop_url ?? "");
  const [clientId, setClientId] = useState(creds.client_id ?? "");
  const [clientSecret, setClientSecret] = useState(creds.client_secret ?? "");
  const [refreshToken, setRefreshToken] = useState(creds.refresh_token ?? "");
  const [marketplaceId, setMarketplaceId] = useState(conn?.marketplace_id ?? "ATVPDKIKX0DER");
  const [sandbox, setSandbox] = useState(creds.sandbox ?? false);

  // Amazon-only: save via API
  const mut = useMutation({
    mutationFn: (data: object) =>
      conn ? marketplaceApi.updateConnection(conn.id, data) : marketplaceApi.createConnection(data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["connections"] }); toast.success(conn ? "Updated" : "Created"); onClose(); },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  // Rename existing Shopify connection
  const renameMut = useMutation({
    mutationFn: () => marketplaceApi.updateConnection(conn.id, { name }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["connections"] }); toast.success("Name updated"); onClose(); },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  const handleAmazonSubmit = () => {
    mut.mutate({
      name,
      marketplace: "amazon",
      credentials: { client_id: clientId, client_secret: clientSecret, refresh_token: refreshToken, sandbox },
      marketplace_id: marketplaceId || undefined,
    });
  };

  // Shopify OAuth redirect
  const shopDomain = toShopDomain(shopUrl);
  const oauthHref = `/api/v1/shopify/auth?shop=${encodeURIComponent(shopDomain)}`;
  const shopifyReady = shopDomain.endsWith(".myshopify.com");

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">{conn ? "Edit Connection" : "New Connection"}</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>

        <div className="space-y-3">
          {/* Marketplace selector — only for new connections */}
          {!conn && (
            <div>
              <label className="label">Marketplace</label>
              <select className="input" value={marketplace} onChange={(e) => setMarketplace(e.target.value)}>
                <option value="shopify">Shopify</option>
                <option value="amazon">Amazon</option>
              </select>
            </div>
          )}

          {/* ── SHOPIFY ─────────────────────────────── */}
          {marketplace === "shopify" && (
            <>
              {conn && (
                /* Edit mode: allow renaming */
                <div>
                  <label className="label">Name</label>
                  <input className="input" value={name} onChange={(e) => setName(e.target.value)} />
                </div>
              )}

              <div>
                <label className="label">Shop URL</label>
                <input
                  className="input"
                  value={shopUrl}
                  onChange={(e) => setShopUrl(e.target.value)}
                  placeholder="yourstore.myshopify.com"
                  readOnly={!!conn}
                />
                {shopUrl && !shopifyReady && (
                  <p className="text-xs text-red-500 mt-1">Must end with .myshopify.com</p>
                )}
              </div>

              <div className="rounded-lg border border-blue-100 bg-blue-50 p-4 text-sm text-blue-800 space-y-2">
                <p className="font-medium flex items-center gap-1"><Link2 className="w-4 h-4" /> Shopify Partner App (OAuth)</p>
                <p className="text-xs text-blue-600">
                  Clicking the button below will open Shopify's authorization page. After you approve,
                  you'll be redirected back here automatically.
                </p>
              </div>

              <a
                href={shopifyReady ? oauthHref : undefined}
                onClick={!shopifyReady ? (e) => e.preventDefault() : undefined}
                className={`btn-primary w-full flex items-center justify-center gap-2 ${!shopifyReady ? "opacity-50 cursor-not-allowed" : ""}`}
              >
                <Link2 className="w-4 h-4" />
                {conn ? "Reconnect with Shopify" : "Connect with Shopify"}
              </a>

              {conn && (
                <div className="flex justify-end gap-2 pt-1">
                  <button className="btn-secondary" onClick={onClose}>Cancel</button>
                  <button className="btn-primary" disabled={!name} onClick={() => renameMut.mutate()}>
                    Save Name
                  </button>
                </div>
              )}
            </>
          )}

          {/* ── AMAZON ─────────────────────────────── */}
          {marketplace === "amazon" && (
            <>
              <div>
                <label className="label">Name *</label>
                <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="My Amazon Store" />
              </div>
              <div><label className="label">Client ID (LWA)</label><input className="input" value={clientId} onChange={(e) => setClientId(e.target.value)} /></div>
              <div><label className="label">Client Secret</label><input className="input" type="password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} /></div>
              <div><label className="label">Refresh Token</label><input className="input" type="password" value={refreshToken} onChange={(e) => setRefreshToken(e.target.value)} /></div>
              <div><label className="label">Marketplace ID</label><input className="input" value={marketplaceId} onChange={(e) => setMarketplaceId(e.target.value)} /></div>
              <div className="flex items-center gap-2 pt-1">
                <input type="checkbox" id="sandbox" checked={sandbox} onChange={(e) => setSandbox(e.target.checked)} className="w-4 h-4" />
                <label htmlFor="sandbox" className="text-sm text-gray-600">Sandbox mode</label>
              </div>

              <div className="flex justify-end gap-2 pt-1">
                <button className="btn-secondary" onClick={onClose}>Cancel</button>
                <button className="btn-primary" disabled={!name} onClick={handleAmazonSubmit}>
                  {conn ? "Save" : "Connect"}
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
