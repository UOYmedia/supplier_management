"use client";
import { useEffect, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { marketplaceApi } from "@/lib/api";
import toast from "react-hot-toast";
import { Plus, RefreshCw, Zap, Trash2, CheckCircle, XCircle, X, Package, Link2, MapPin, List, Pencil, Bug, Loader2 } from "lucide-react";
import NextLink from "next/link";

export default function MarketplacePage() {
  const qc = useQueryClient();
  const [showCreate, setShowCreate] = useState(false);
  const [editConn, setEditConn] = useState<any>(null);
  const [debugConn, setDebugConn] = useState<any>(null);

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
              onDebug={() => setDebugConn(c)}
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
      {debugConn && <ConnectionDebugModal conn={debugConn} onClose={() => setDebugConn(null)} />}
    </div>
  );
}

function ConnectionCard({ conn, onTest, onDebug, onEdit, onSyncOrders, onSyncProducts, onSyncLocations, onSyncListings, onDelete }: any) {
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
        <button className="btn-secondary text-xs py-1 flex-1" onClick={onDebug}>
          <Bug className="w-3 h-3" /> Debug
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

function toShopDomain(raw: string): string {
  return raw.replace(/^https?:\/\//, "").replace(/\/$/, "").toLowerCase();
}

function ConnectionModal({ onClose, conn }: { onClose: () => void; conn?: any }) {
  const qc = useQueryClient();

  const [marketplace, setMarketplace] = useState<string>(conn?.marketplace ?? "shopify");
  const [name, setName] = useState(conn?.name ?? "");
  const [shopUrl, setShopUrl] = useState(conn?.shop_url ?? "");
  // Shopify: client_id returned from API (non-secret); client_secret must be re-entered
  const [shopClientId, setShopClientId] = useState(conn?.client_id ?? "");
  const [shopClientSecret, setShopClientSecret] = useState("");
  // Amazon
  const [amzClientId, setAmzClientId] = useState(conn?.client_id ?? "");
  const [amzClientSecret, setAmzClientSecret] = useState("");
  const [refreshToken, setRefreshToken] = useState("");
  const [marketplaceId, setMarketplaceId] = useState(conn?.marketplace_id ?? "ATVPDKIKX0DER");
  const [sandbox, setSandbox] = useState(conn?.sandbox ?? false);
  const [connecting, setConnecting] = useState(false);

  const shopDomain = toShopDomain(shopUrl);
  const shopifyReady = shopDomain.endsWith(".myshopify.com") && !!shopClientId;

  // Shopify: save credentials then navigate to OAuth
  const handleShopifyConnect = async () => {
    if (!shopifyReady) return;
    setConnecting(true);
    try {
      const credentials: Record<string, unknown> = { client_id: shopClientId };
      if (shopClientSecret) credentials.client_secret = shopClientSecret;

      let connId: number;
      if (conn) {
        const updated = await marketplaceApi.updateConnection(conn.id, { name: name || undefined, credentials });
        connId = updated.id;
      } else {
        const autoName = shopDomain.replace(".myshopify.com", "").replace(/-/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
        const created = await marketplaceApi.createConnection({
          name: name || autoName,
          marketplace: "shopify",
          shop_url: `https://${shopDomain}`,
          credentials,
        });
        connId = created.id;
      }
      // Get the Shopify OAuth consent URL from the backend and navigate there
      const { oauth_url } = await import("@/lib/api").then(({ api }) =>
        api.get(`/shopify/auth?connection_id=${connId}`).then((r) => r.data)
      );
      window.location.href = oauth_url;
    } catch (e: any) {
      toast.error(e.response?.data?.error || e.response?.data?.detail || "Failed to start OAuth");
      setConnecting(false);
    }
  };

  // Amazon: save via API
  const amazonMut = useMutation({
    mutationFn: () => {
      const credentials: Record<string, unknown> = { client_id: amzClientId, sandbox };
      if (amzClientSecret) credentials.client_secret = amzClientSecret;
      if (refreshToken) credentials.refresh_token = refreshToken;
      const payload = { name, marketplace: "amazon" as const, credentials, marketplace_id: marketplaceId || undefined };
      return conn ? marketplaceApi.updateConnection(conn.id, payload) : marketplaceApi.createConnection(payload);
    },
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["connections"] }); toast.success(conn ? "Updated" : "Created"); onClose(); },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">{conn ? "Edit Connection" : "New Connection"}</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>

        <div className="space-y-3">
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
              <div>
                <label className="label">Display Name</label>
                <input className="input" value={name} onChange={(e) => setName(e.target.value)}
                  placeholder={conn ? conn.name : "auto from shop URL"} />
              </div>
              <div>
                <label className="label">Shop URL *</label>
                <input className="input" value={shopUrl} onChange={(e) => setShopUrl(e.target.value)}
                  placeholder="yourstore.myshopify.com" readOnly={!!conn} />
                {shopUrl && !shopDomain.endsWith(".myshopify.com") && (
                  <p className="text-xs text-red-500 mt-1">Must end with .myshopify.com</p>
                )}
              </div>
              <div>
                <label className="label">Client ID (Partner App) *</label>
                <input className="input" value={shopClientId} onChange={(e) => setShopClientId(e.target.value)}
                  placeholder="From Shopify Partner Dashboard → API credentials" />
              </div>
              <div>
                <label className="label">Client Secret {conn && <span className="text-gray-400 font-normal">(leave blank to keep current)</span>}</label>
                <input className="input" type="password" value={shopClientSecret}
                  onChange={(e) => setShopClientSecret(e.target.value)}
                  placeholder={conn ? "••••••••" : "From Shopify Partner Dashboard → API credentials"} />
              </div>

              <div className="rounded-lg border border-blue-100 bg-blue-50 p-3 text-xs text-blue-700 space-y-1">
                <p className="font-medium">Shopify Partner App (OAuth 2.0)</p>
                <p>Set redirect URL in Partner Dashboard → App setup → <b>Allowed redirect URLs</b>:</p>
                <code className="block bg-blue-100 rounded px-2 py-1 break-all">
                  {typeof window !== "undefined" ? window.location.origin.replace(/:\d+$/, "") + "/api/v1/shopify/callback" : "https://your-backend/api/v1/shopify/callback"}
                </code>
              </div>

              <button
                className={`btn-primary w-full flex items-center justify-center gap-2 ${(!shopifyReady || connecting) ? "opacity-50 cursor-not-allowed" : ""}`}
                disabled={!shopifyReady || connecting}
                onClick={handleShopifyConnect}
              >
                <Link2 className="w-4 h-4" />
                {connecting ? "Redirecting…" : conn ? "Reconnect with Shopify" : "Connect with Shopify"}
              </button>
              <div className="flex justify-end">
                <button className="btn-secondary text-sm" onClick={onClose}>Cancel</button>
              </div>
            </>
          )}

          {/* ── AMAZON ─────────────────────────────── */}
          {marketplace === "amazon" && (
            <>
              <div>
                <label className="label">Name *</label>
                <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="My Amazon Store" />
              </div>
              <div>
                <label className="label">Client ID (LWA) {conn && <span className="text-gray-400 font-normal">(current: {conn.client_id || "—"})</span>}</label>
                <input className="input" value={amzClientId} onChange={(e) => setAmzClientId(e.target.value)} />
              </div>
              <div>
                <label className="label">Client Secret {conn && <span className="text-gray-400 font-normal">(leave blank to keep)</span>}</label>
                <input className="input" type="password" value={amzClientSecret} onChange={(e) => setAmzClientSecret(e.target.value)} placeholder={conn ? "••••••••" : ""} />
              </div>
              <div>
                <label className="label">Refresh Token {conn && <span className="text-gray-400 font-normal">(leave blank to keep)</span>}</label>
                <input className="input" type="password" value={refreshToken} onChange={(e) => setRefreshToken(e.target.value)} placeholder={conn ? "••••••••" : ""} />
              </div>
              <div>
                <label className="label">Marketplace ID</label>
                <input className="input" value={marketplaceId} onChange={(e) => setMarketplaceId(e.target.value)} />
              </div>
              <div className="flex items-center gap-2 pt-1">
                <input type="checkbox" id="sandbox" checked={sandbox} onChange={(e) => setSandbox(e.target.checked)} className="w-4 h-4" />
                <label htmlFor="sandbox" className="text-sm text-gray-600">Sandbox mode</label>
              </div>
              <div className="flex justify-end gap-2 pt-1">
                <button className="btn-secondary" onClick={onClose}>Cancel</button>
                <button className="btn-primary" disabled={!name} onClick={() => amazonMut.mutate()}>
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

function ConnectionDebugModal({ conn, onClose }: { conn: any; onClose: () => void }) {
  const [report, setReport] = useState<any | null>(null);
  const [busy, setBusy] = useState(false);
  const [showRaw, setShowRaw] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const data = await marketplaceApi.debugConnection(conn.id);
      setReport(data);
    } catch (e: any) {
      setError(e.response?.data?.detail || "Debug failed");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => { run(); }, []);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-2xl p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="flex items-center gap-2">
              <Bug className="w-5 h-5 text-blue-600" />
              <h2 className="font-semibold">Debug — {conn.name}</h2>
              <span className="badge-gray text-xs capitalize">{conn.marketplace}</span>
            </div>
            <p className="text-xs text-gray-500 mt-0.5">
              Inspects credentials and live API responses so you can pinpoint exactly which step fails.
            </p>
          </div>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>

        {busy && (
          <div className="flex items-center justify-center gap-2 py-12 text-gray-400">
            <Loader2 className="w-5 h-5 animate-spin" /> Running diagnostics…
          </div>
        )}

        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-700">{error}</div>
        )}

        {report && !busy && (
          <div className="space-y-4">
            {/* Connection summary */}
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div className="p-3 bg-gray-50 rounded-lg border border-gray-200">
                <div className="text-gray-500 uppercase tracking-wide font-semibold mb-2">Connection</div>
                <div><span className="text-gray-500">Name:</span> {report.connection.name}</div>
                <div><span className="text-gray-500">Marketplace:</span> {report.connection.marketplace} {report.connection.marketplace_id && `(${report.connection.marketplace_id})`}</div>
                <div><span className="text-gray-500">Status:</span> <span className={`badge text-xs ${report.connection.status === "active" ? "badge-green" : "badge-red"}`}>{report.connection.status}</span></div>
                {report.connection.shop_url && <div className="truncate"><span className="text-gray-500">Shop URL:</span> {report.connection.shop_url}</div>}
                <div><span className="text-gray-500">Last synced:</span> {report.connection.last_synced_at ? new Date(report.connection.last_synced_at).toLocaleString() : "Never"}</div>
                {report.connection.error_message && (
                  <div className="mt-1 text-red-600">{report.connection.error_message}</div>
                )}
              </div>
              <div className="p-3 bg-gray-50 rounded-lg border border-gray-200">
                <div className="text-gray-500 uppercase tracking-wide font-semibold mb-2">Credentials</div>
                {Object.entries(report.credentials_present).map(([k, v]) => (
                  <div key={k} className="flex justify-between">
                    <span className="text-gray-600">{k}</span>
                    <span>
                      {v ? <span className="text-green-600">✓</span> : <span className="text-red-500">✗</span>}
                      {report.credentials_masked[k] && (
                        <span className="ml-2 font-mono text-[10px] text-gray-400">{report.credentials_masked[k]}</span>
                      )}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Steps */}
            <div className="space-y-2">
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Diagnostic steps</div>
              {report.checks.length === 0 && (
                <div className="text-xs text-gray-400 p-3 border border-dashed border-gray-300 rounded-lg text-center">No checks run.</div>
              )}
              {report.checks.map((c: any, i: number) => (
                <div
                  key={i}
                  className={`p-3 rounded-lg border text-xs ${c.ok ? "border-green-200 bg-green-50" : "border-red-200 bg-red-50"}`}
                >
                  <div className="flex items-center gap-2 font-semibold">
                    {c.ok ? <CheckCircle className="w-4 h-4 text-green-600" /> : <XCircle className="w-4 h-4 text-red-500" />}
                    <span className={c.ok ? "text-green-800" : "text-red-800"}>{c.step}</span>
                    {c.status != null && <span className="text-gray-500 font-normal">HTTP {c.status}</span>}
                  </div>
                  {c.error && <div className="mt-1 text-red-700 font-mono">{c.error}</div>}
                  {c.hint && <div className="mt-1 text-gray-600 italic">→ {c.hint}</div>}
                  {c.missing && c.missing.length > 0 && (
                    <div className="mt-1 text-red-700">Missing: <span className="font-mono">{c.missing.join(", ")}</span></div>
                  )}
                  {/* Step-specific data */}
                  {c.step === "lwa_token_exchange" && c.ok && (
                    <div className="mt-1 text-gray-700">
                      Token type: <span className="font-mono">{c.token_type}</span> · expires_in: {c.expires_in}s
                    </div>
                  )}
                  {c.step === "sp_api_participations" && c.ok && (
                    <div className="mt-2 space-y-1">
                      <div>Base URL: <span className="font-mono text-[10px]">{c.base_url}</span></div>
                      <div>Configured marketplace: <span className="font-mono">{c.configured_marketplace_id}</span> — {c.configured_marketplace_in_list ? <span className="text-green-700">in account ✓</span> : <span className="text-red-700">NOT in account ✗</span>}</div>
                      <div className="mt-1">Marketplaces ({c.participation_count}):</div>
                      <div className="grid gap-1">
                        {c.marketplaces?.map((m: any) => (
                          <div key={m.id} className="bg-white p-2 rounded border border-gray-200 flex items-center gap-2">
                            <span className="font-mono text-[10px]">{m.id}</span>
                            <span className="font-medium">{m.name}</span>
                            <span className="text-gray-400">{m.country_code}</span>
                            <span className="text-gray-400">{m.default_currency_code}</span>
                            {m.is_participating ? <span className="badge-green text-[10px] ml-auto">active</span> : <span className="badge-gray text-[10px] ml-auto">inactive</span>}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {c.step === "shop_api" && c.ok && (
                    <div className="mt-1 grid grid-cols-2 gap-1 text-gray-700">
                      <div>Shop: <span className="font-medium">{c.shop_name}</span></div>
                      <div>Domain: <span className="font-mono text-[10px]">{c.myshopify_domain}</span></div>
                      <div>Country: {c.country_code}</div>
                      <div>Currency: {c.currency}</div>
                      <div>Plan: {c.plan_name}</div>
                      <div>ID: <span className="font-mono text-[10px]">{c.shop_id}</span></div>
                    </div>
                  )}
                </div>
              ))}
            </div>

            <div className="flex items-center justify-between pt-2 border-t border-gray-100">
              <button className="text-xs text-blue-600 hover:underline" onClick={() => setShowRaw((v) => !v)}>
                {showRaw ? "Hide raw JSON" : "Show raw JSON"}
              </button>
              <div className="flex gap-2">
                <button className="btn-secondary text-xs py-1" onClick={run} disabled={busy}>
                  <RefreshCw className="w-3 h-3" /> Re-run
                </button>
                <button className="btn-primary text-xs py-1" onClick={onClose}>Close</button>
              </div>
            </div>

            {showRaw && (
              <pre className="text-[10px] leading-tight p-2 max-h-60 overflow-auto bg-gray-900 text-gray-100 rounded font-mono">
{JSON.stringify(report, null, 2)}
              </pre>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
