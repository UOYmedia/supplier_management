"use client";
import { useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { productsApi, suppliersApi } from "@/lib/api";
import toast from "react-hot-toast";
import { Plus, Search, Trash2, X, ChevronRight, Upload, Download } from "lucide-react";
import Link from "next/link";

export default function ProductsPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const [showImport, setShowImport] = useState(false);

  const { data: mappings = [], isLoading } = useQuery({
    queryKey: ["mappings", search],
    queryFn: () => productsApi.listMappings({ search: search || undefined }),
  });

  const deleteMut = useMutation({
    mutationFn: (componentId: number) => productsApi.deleteMapping(componentId),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["mappings"] }); toast.success("Mapping removed"); },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  // Group by product_sku for display
  const grouped: Record<string, any[]> = {};
  for (const m of mappings) {
    if (!grouped[m.product_sku]) grouped[m.product_sku] = [];
    grouped[m.product_sku].push(m);
  }
  const skus = Object.keys(grouped).sort();

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">SKU Mappings</h1>
          <p className="text-sm text-gray-500 mt-0.5">Map marketplace SKUs to supplier catalog items</p>
        </div>
        <div className="flex gap-2">
          <button className="btn-secondary" onClick={() => setShowImport(true)}>
            <Upload className="w-4 h-4" /> Import CSV
          </button>
          <button className="btn-primary" onClick={() => setShowAdd(true)}>
            <Plus className="w-4 h-4" /> Add Mapping
          </button>
        </div>
      </div>

      <div className="card mb-4 px-3 py-2 flex items-center gap-2">
        <Search className="w-4 h-4 text-gray-400" />
        <input
          className="flex-1 text-sm outline-none bg-transparent"
          placeholder="Search by SKU, catalog name…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && <button onClick={() => setSearch("")}><X className="w-4 h-4 text-gray-400" /></button>}
      </div>

      <div className="card table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Marketplace SKU</th>
              <th>Catalog Item</th>
              <th>Short Name</th>
              <th>Supplier</th>
              <th>Units / order</th>
              <th>Stock</th>
              <th>Price</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={8} className="text-center py-8 text-gray-400">Loading…</td></tr>
            ) : skus.length === 0 ? (
              <tr><td colSpan={8} className="text-center py-8 text-gray-400">
                No mappings yet. Click <strong>Add Mapping</strong> to link a marketplace SKU to a supplier catalog item.
              </td></tr>
            ) : skus.map((sku) => {
              const rows = grouped[sku];
              return rows.map((m: any, i: number) => (
                <tr key={m.component_id}>
                  {i === 0 && (
                    <td rowSpan={rows.length} className="align-top">
                      <div className="font-mono text-xs font-medium text-gray-800">{sku}</div>
                      <Link href={`/products/${m.product_id}`} className="text-xs text-blue-500 hover:underline flex items-center gap-0.5 mt-0.5">
                        <ChevronRight className="w-3 h-3" /> Advanced
                      </Link>
                    </td>
                  )}
                  <td className="font-medium text-sm">{m.catalog_name}</td>
                  <td className="text-xs text-gray-500">{m.catalog_short_name || <span className="text-gray-300">—</span>}</td>
                  <td className="text-sm">{m.supplier_name}</td>
                  <td className="text-center">{m.units}</td>
                  <td>
                    <span className={`text-xs font-medium ${m.stock_quantity > 0 ? "text-green-600" : "text-red-500"}`}>
                      {m.stock_quantity}
                    </span>
                  </td>
                  <td className="text-sm">${m.unit_price.toFixed(2)}</td>
                  <td>
                    <button
                      className="p-1 hover:bg-red-50 rounded text-gray-400 hover:text-red-500"
                      title="Remove mapping"
                      onClick={() => confirm(`Remove mapping: ${sku} → ${m.catalog_name}?`) && deleteMut.mutate(m.component_id)}
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </td>
                </tr>
              ));
            })}
          </tbody>
        </table>
      </div>

      {showAdd && <AddMappingModal onClose={() => setShowAdd(false)} />}
      {showImport && <ImportMappingsModal onClose={() => setShowImport(false)} />}
    </div>
  );
}

function ImportMappingsModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<{ created: number; updated: number; errors: string[] } | null>(null);

  const mut = useMutation({
    mutationFn: (f: File) => productsApi.importMappingsCsv(f),
    onSuccess: (data) => {
      setResult(data);
      qc.invalidateQueries({ queryKey: ["mappings"] });
      if (data.errors.length === 0) {
        toast.success(`Imported: ${data.created} created, ${data.updated} updated`);
      } else {
        toast(`${data.created} created, ${data.updated} updated, ${data.errors.length} errors`, { icon: "⚠️" });
      }
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Import failed"),
  });

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="card w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Import SKU Mappings from CSV</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>

        <div className="text-sm text-gray-600 space-y-1 mb-4">
          <p>CSV must have columns: <code className="bg-gray-100 px-1 rounded">marketplace_sku</code>, <code className="bg-gray-100 px-1 rounded">supplier_sku</code>, and optionally <code className="bg-gray-100 px-1 rounded">units</code> (default 1).</p>
          <p>The <code className="bg-gray-100 px-1 rounded">supplier_sku</code> must match an existing catalog item SKU exactly.</p>
        </div>

        <a
          href="/api/v1/products/mappings/template.csv"
          download
          className="inline-flex items-center gap-1.5 text-sm text-blue-600 hover:underline mb-4"
        >
          <Download className="w-4 h-4" /> Download template
        </a>

        {!result ? (
          <>
            <div
              className="border-2 border-dashed border-gray-200 rounded-lg p-6 text-center cursor-pointer hover:border-blue-300 transition-colors"
              onClick={() => fileRef.current?.click()}
            >
              <Upload className="w-8 h-8 text-gray-300 mx-auto mb-2" />
              {file ? (
                <p className="text-sm font-medium text-gray-700">{file.name}</p>
              ) : (
                <p className="text-sm text-gray-400">Click to select a CSV file</p>
              )}
            </div>
            <input
              ref={fileRef}
              type="file"
              accept=".csv,text/csv"
              className="hidden"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <div className="flex justify-end gap-2 mt-4">
              <button className="btn-secondary" onClick={onClose}>Cancel</button>
              <button
                className="btn-primary"
                disabled={!file || mut.isPending}
                onClick={() => file && mut.mutate(file)}
              >
                {mut.isPending ? "Importing…" : "Import"}
              </button>
            </div>
          </>
        ) : (
          <>
            <div className="rounded-lg bg-gray-50 border border-gray-200 p-4 text-sm space-y-1 mb-4">
              <div className="text-green-700 font-medium">Created: {result.created}</div>
              <div className="text-blue-700 font-medium">Updated: {result.updated}</div>
              {result.errors.length > 0 && (
                <div className="mt-2">
                  <div className="text-red-600 font-medium mb-1">Errors ({result.errors.length}):</div>
                  <ul className="space-y-0.5 max-h-40 overflow-y-auto">
                    {result.errors.map((e, i) => (
                      <li key={i} className="text-red-600 text-xs font-mono">{e}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            <div className="flex justify-end gap-2">
              <button className="btn-secondary" onClick={() => { setFile(null); setResult(null); }}>Import Another</button>
              <button className="btn-primary" onClick={onClose}>Done</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function AddMappingModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [sku, setSku] = useState("");
  const [supplierId, setSupplierId] = useState("");
  const [selectedSpId, setSelectedSpId] = useState<number | null>(null);
  const [units, setUnits] = useState("1");
  const [spQuery, setSpQuery] = useState("");

  const { data: suppliers = [] } = useQuery({ queryKey: ["suppliers"], queryFn: () => suppliersApi.list() });
  const { data: catalog = [] } = useQuery({
    queryKey: ["supplier-catalog", supplierId],
    queryFn: () => suppliersApi.listProducts(parseInt(supplierId)),
    enabled: !!supplierId,
  });

  const filtered = spQuery
    ? catalog.filter((sp: any) =>
        sp.name.toLowerCase().includes(spQuery.toLowerCase()) ||
        sp.sku.toLowerCase().includes(spQuery.toLowerCase())
      )
    : catalog;

  const selectedSp = catalog.find((sp: any) => sp.id === selectedSpId);

  const mut = useMutation({
    mutationFn: (data: object) => productsApi.createMapping(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["mappings"] });
      toast.success("Mapping saved");
      onClose();
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  const handleSubmit = () => {
    if (!sku.trim() || !selectedSpId) { toast.error("SKU and catalog item required"); return; }
    mut.mutate({ marketplace_sku: sku.trim(), supplier_product_id: selectedSpId, units: parseInt(units) || 1 });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="card w-full max-w-md p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold">Add SKU Mapping</h2>
          <button onClick={onClose}><X className="w-5 h-5 text-gray-400" /></button>
        </div>
        <p className="text-xs text-gray-500 mb-4">
          Link a marketplace SKU (e.g. Amazon ASIN or Shopify variant SKU) to a supplier catalog item.
        </p>
        <div className="space-y-3">
          <div>
            <label className="label">Marketplace SKU *</label>
            <input className="input font-mono" value={sku} onChange={(e) => setSku(e.target.value)} placeholder="e.g. B0GX5Z686V" />
          </div>
          <div>
            <label className="label">Supplier *</label>
            <select className="input" value={supplierId} onChange={(e) => { setSupplierId(e.target.value); setSelectedSpId(null); setSpQuery(""); }}>
              <option value="">Select supplier…</option>
              {suppliers.map((s: any) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </div>
          {supplierId && (
            <div>
              <label className="label">Catalog Item *</label>
              {selectedSp ? (
                <div className="flex items-center justify-between gap-2 p-2 rounded-lg border border-blue-200 bg-blue-50">
                  <div className="min-w-0">
                    <div className="font-medium text-sm truncate">{selectedSp.name}</div>
                    {selectedSp.short_name && <div className="text-xs text-blue-600">Short: {selectedSp.short_name}</div>}
                    <div className="text-xs text-gray-500 font-mono">{selectedSp.sku} · ${parseFloat(selectedSp.unit_price).toFixed(2)} · stock {selectedSp.stock_quantity}</div>
                  </div>
                  <button className="text-xs text-gray-500 hover:text-red-500" onClick={() => setSelectedSpId(null)}>Change</button>
                </div>
              ) : (
                <>
                  <input className="input" placeholder="Search catalog…" value={spQuery} onChange={(e) => setSpQuery(e.target.value)} />
                  <div className="mt-1 border border-gray-200 rounded-lg max-h-48 overflow-y-auto bg-white">
                    {filtered.length === 0 ? (
                      <div className="p-2 text-xs text-gray-400">No catalog items</div>
                    ) : filtered.slice(0, 50).map((sp: any) => (
                      <button key={sp.id} type="button"
                        className="w-full text-left px-2 py-1.5 text-sm hover:bg-blue-50 border-b border-gray-100 last:border-0"
                        onClick={() => { setSelectedSpId(sp.id); setSpQuery(""); }}>
                        <div className="font-medium truncate">{sp.name}</div>
                        <div className="text-xs text-gray-500 font-mono">{sp.sku} · ${parseFloat(sp.unit_price).toFixed(2)}</div>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}
          <div>
            <label className="label">Units per marketplace order unit</label>
            <input className="input" type="number" min="1" value={units} onChange={(e) => setUnits(e.target.value)} />
            <p className="text-xs text-gray-400 mt-1">How many catalog units are shipped per 1 unit sold on the marketplace.</p>
          </div>
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button className="btn-secondary" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={!sku.trim() || !selectedSpId || mut.isPending} onClick={handleSubmit}>
            {mut.isPending ? "Saving…" : "Save Mapping"}
          </button>
        </div>
      </div>
    </div>
  );
}
