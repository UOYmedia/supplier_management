"use client";
import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { scanLogsApi } from "@/lib/api";
import toast from "react-hot-toast";
import { RefreshCw, Trash2, CheckCircle2, XCircle, MinusCircle } from "lucide-react";

const STATUS_FILTERS = [
  { value: "", label: "All" },
  { value: "updated", label: "Updated" },
  { value: "already_has_address", label: "Already had address" },
  { value: "scan_failed", label: "Failed" },
  { value: "not_found", label: "Order not found" },
  { value: "no_api_key", label: "No API key" },
];

function statusBadge(status: string) {
  if (status === "updated") return { cls: "badge-green", Icon: CheckCircle2 };
  if (status === "scan_failed") return { cls: "badge-red", Icon: XCircle };
  return { cls: "badge-gray", Icon: MinusCircle };
}

function fmtAddress(a: any): string {
  if (!a || typeof a !== "object") return "—";
  const parts = [a.name, a.line1, a.line2, [a.city, a.state, a.zip].filter(Boolean).join(" ")];
  return parts.filter(Boolean).join(", ") || "—";
}

export default function ScanLogsPage() {
  const qc = useQueryClient();
  const [status, setStatus] = useState("");

  const { data: logs = [], isLoading, isFetching, refetch } = useQuery({
    queryKey: ["scan-logs", status],
    queryFn: () => scanLogsApi.list({ status: status || undefined, limit: 500 }),
    refetchInterval: 15000,
  });

  const clearMut = useMutation({
    mutationFn: () => scanLogsApi.clear(),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["scan-logs"] }); toast.success("Cleared"); },
    onError: (e: any) => toast.error(e.response?.data?.detail || "Error"),
  });

  return (
    <div>
      <div className="page-header">
        <h1 className="page-title">Scan Logs</h1>
        <div className="flex items-center gap-2">
          <button className="btn-secondary" onClick={() => refetch()}>
            <RefreshCw className={`w-4 h-4 ${isFetching ? "animate-spin" : ""}`} /> Refresh
          </button>
          <button className="btn-secondary text-red-600"
            onClick={() => confirm("Clear all scan logs?") && clearMut.mutate()}
            disabled={clearMut.isPending || logs.length === 0}>
            <Trash2 className="w-4 h-4" /> Clear
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1 mb-4">
        {STATUS_FILTERS.map((f) => (
          <button key={f.value} onClick={() => setStatus(f.value)}
            className={`badge text-xs cursor-pointer ${status === f.value ? "badge-blue" : "badge-gray"}`}>
            {f.label}
          </button>
        ))}
      </div>

      <div className="card table-wrapper">
        <table>
          <thead><tr>
            <th>Time</th><th>Order ID</th><th>Status</th><th>Address</th><th>Filled</th><th>Error</th>
          </tr></thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={6} className="text-center py-8 text-gray-400">Loading…</td></tr>
            ) : logs.length === 0 ? (
              <tr><td colSpan={6} className="text-center py-8 text-gray-400">No scans yet</td></tr>
            ) : logs.map((l: any) => {
              const { cls, Icon } = statusBadge(l.status);
              return (
                <tr key={l.id}>
                  <td className="text-xs text-gray-500 whitespace-nowrap">
                    {new Date(l.created_at).toLocaleString()}
                  </td>
                  <td className="font-mono text-xs">{l.order_id || "—"}</td>
                  <td>
                    <span className={`badge text-xs ${cls} inline-flex items-center gap-1`}>
                      <Icon className="w-3 h-3" />{l.status}
                    </span>
                  </td>
                  <td className="text-xs text-gray-600 max-w-xs truncate" title={fmtAddress(l.address)}>
                    {fmtAddress(l.address)}
                  </td>
                  <td className="text-xs text-gray-500">
                    {Array.isArray(l.filled) && l.filled.length ? l.filled.join(", ") : "—"}
                  </td>
                  <td className="text-xs text-red-500 max-w-xs truncate" title={l.error || ""}>
                    {l.error || "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
