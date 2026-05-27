"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { marketplaceApi } from "@/lib/api";
import toast from "react-hot-toast";
import { Plus, RefreshCw, Zap, Trash2, CheckCircle, XCircle, X, Package, Link2, MapPin, List } from "lucide-react";

export default function MarketplacePage() {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);

  const { data: connections = [], isLoading } = useQuery({ queryKey: ["connections"], queryFn: marketplaceApi.listConnections });

  const deleteMut = useMutation({
    mutationFn: (id: number) => marketplaceApi.deleteConnection(id),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["connections"] }); toast.success("Deleted"); },
  });

  const testMut = useMutation({
    mutationFn: (id: number) => marketplaceApi.testConnection(id),
    onSuccess: (data, id) => {
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
          <a
            href="/api/v1/shopify/auth?shop=gingerglow.myshopify.com"
            className="btn-secondary flex items-center gap-1 text-sm"
          >
            <Link2 className="w-4 h-4" /> Connect Shopify
          </a>
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
    </div>
  );
}

function ConnectionCard({ conn, onTest, onSyncOrders, onSyncProducts, onSyncLocations, onSyncListings, onDelete }: any) {
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
        <button className="p-1.5 hover:text-red-500 text-gray-400" onClick={onDelete}>
          <Trash2 className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

function ConnectionModal({ onClose, conn }: { onClose: () => void; conn?: any }) {
  const qc = useQueryClient();
  const [marketplace, setMarketplace] = useState(conn?.marketplace ?? "shopify");
  const [name, setName] = useState(conn?.name ?? "");
  const [shopUrl, setShopUrl] = useState(conn?.shop_url ?? "");
  const [accessToken, setAccessToken] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [refreshToken, setRefreshToken] = useState("");
  const [marketplaceId, setMarketplaceId] = useState("ATVPDKIKX0DER");

  const mut = useMutation({
    mutationFn: (data: object) => conn ? marketplaceApi.updateConnection(conn.id, data) : marketplaceApi.createConnection(data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["connections"] }); toast.success(conn ? "Updated" : "Created"); onClose(); },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  const handleSubmit = () => {
    const credentials = marketplace === "shopify"
      ? { access_token: accessToken }
      : { client_id: clientId, client_secret: clientSecret, refresh_token: refreshToken };
    mut.mutate({ name, marketplace, credentials, shop_url: shopUrl || undefined, marketplace_id: marketplaceId || undefined });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">{conn ? "Edit Connection" : "New Connection"}</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <div className="space-y-3">
          <div>
            <label className="label">Name *</label>
            <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="My Shopify Store" />
          </div>
          <div>
            <label className="label">Marketplace</label>
            <select className="input" value={marketplace} onChange={(e) => setMarketplace(e.target.value)}>
              <option value="shopify">Shopify</option>
              <option value="amazon">Amazon</option>
            </select>
          </div>
          {marketplace === "shopify" ? (
            <>
              <div><label className="label">Shop URL</label><input className="input" value={shopUrl} onChange={(e) => setShopUrl(e.target.value)} placeholder="https://mystore.myshopify.com" /></div>
              <div><label className="label">Access Token</label><input className="input" type="password" value={accessToken} onChange={(e) => setAccessToken(e.target.value)} /></div>
            </>
          ) : (
            <>
              <div><label className="label">Client ID</label><input className="input" value={clientId} onChange={(e) => setClientId(e.target.value)} /></div>
              <div><label className="label">Client Secret</label><input className="input" type="password" value={clientSecret} onChange={(e) => setClientSecret(e.target.value)} /></div>
              <div><label className="label">Refresh Token</label><input className="input" type="password" value={refreshToken} onChange={(e) => setRefreshToken(e.target.value)} /></div>
              <div><label className="label">Marketplace ID</label><input className="input" value={marketplaceId} onChange={(e) => setMarketplaceId(e.target.value)} /></div>
            </>
          )}
        </div>
        <div className="flex justify-end gap-2 mt-4">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={!name} onClick={handleSubmit}>
            {conn ? "Save" : "Connect"}
          </button>
        </div>
      </div>
    </div>
  );
}
