"use client"

import { Suspense, useEffect, useState } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import LiveSupplierPO from "@/components/purchase-orders/LiveSupplierPO"
import RequestList from "@/components/purchase-orders/RequestList"
import { purchaseRequestsApi } from "@/lib/api"

type PageTab = "orders" | "requests"

function PurchaseOrdersPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const qc = useQueryClient()

  const pageTab = (searchParams.get("tab") === "requests" ? "requests" : "orders") as PageTab
  const [username, setUsername] = useState("")
  const [userRole, setUserRole] = useState("")

  function setPageTab(tab: PageTab) {
    const params = new URLSearchParams(searchParams.toString())
    if (tab === "requests") params.set("tab", "requests")
    else params.delete("tab")
    router.push(`/purchase-orders?${params.toString()}`)
  }

  useEffect(() => {
    const user = JSON.parse(localStorage.getItem("admin_user") || "{}")
    setUsername(user.username || "")
    setUserRole(user.role || "")
  }, [])

  const { data: pendingRequests = [] } = useQuery({
    queryKey: ["purchase-requests"],
    queryFn: () => purchaseRequestsApi.list(),
    select: (data: any[]) => data.filter((r) => r.status === "PENDING"),
  })

  const canApprove =
    userRole === "admin" ||
    username.toLowerCase() === "jenny" ||
    username.toLowerCase() === "admin"

  return (
    <div>
      {/* Page-level tabs */}
      <div className="flex items-center gap-1 mb-0 border-b border-gray-200">
        <button
          onClick={() => setPageTab("orders")}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            pageTab === "orders"
              ? "border-blue-600 text-blue-700"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          Daily Orders
        </button>
        <button
          onClick={() => setPageTab("requests")}
          className={`flex items-center gap-1.5 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            pageTab === "requests"
              ? "border-blue-600 text-blue-700"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          Requests
          {pendingRequests.length > 0 && (
            <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 rounded-full text-[10px] font-bold bg-red-500 text-white">
              {pendingRequests.length}
            </span>
          )}
        </button>
      </div>

      {pageTab === "requests" ? (
        <div className="mt-6">
          <div className="page-header">
            <div>
              <h1 className="page-title">Purchase Requests</h1>
            </div>
          </div>
          <RequestList
            username={username}
            canApprove={canApprove}
            isAdmin={userRole === "admin"}
            onPaidSuccess={() => {
              qc.invalidateQueries({ queryKey: ["live-catalog"] })
              qc.invalidateQueries({ queryKey: ["live-suppliers"] })
            }}
          />
        </div>
      ) : (
        <div className="mt-6">
          <div className="page-header">
            <div>
              <h1 className="page-title">Purchase Orders</h1>
            </div>
          </div>
          <LiveSupplierPO />
        </div>
      )}
    </div>
  )
}

export default function PurchaseOrdersPageWrapper() {
  return (
    <Suspense>
      <PurchaseOrdersPage />
    </Suspense>
  )
}
