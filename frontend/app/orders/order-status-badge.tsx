"use client";

export function OrderStatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    pending: "badge-yellow",
    processing: "badge-blue",
    partially_fulfilled: "badge-blue",
    fulfilled: "badge-green",
    cancelled: "badge-red",
    refunded: "badge-gray",
  };
  return <span className={map[status] || "badge-gray"}>{status.replace(/_/g, " ")}</span>;
}
