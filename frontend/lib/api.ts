import axios from "axios";

export const api = axios.create({
  baseURL: "/api/v1",
});

// Attach admin JWT from localStorage on every request
api.interceptors.request.use((config) => {
  if (typeof window !== "undefined") {
    const token = localStorage.getItem("admin_token");
    if (token) config.headers["Authorization"] = `Bearer ${token}`;
  }
  return config;
});

// Redirect to login on 401
api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401 && typeof window !== "undefined") {
      const isPortal = window.location.pathname.startsWith("/portal");
      if (!isPortal) {
        localStorage.removeItem("admin_token");
        window.location.href = "/login";
      }
    }
    return Promise.reject(err);
  }
);

// Products
export const productsApi = {
  list: (params?: object) => api.get("/products", { params }).then((r) => r.data),
  get: (id: number) => api.get(`/products/${id}`).then((r) => r.data),
  create: (data: object) => api.post("/products", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/products/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/products/${id}`),
  importCsv: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return api.post("/products/import/csv", fd).then((r) => r.data);
  },
  listSuppliers: (id: number) => api.get(`/products/${id}/suppliers`).then((r) => r.data),
  addSupplier: (id: number, data: object) => api.post(`/products/${id}/suppliers`, data).then((r) => r.data),
  updateSupplier: (id: number, psId: number, data: object) => api.patch(`/products/${id}/suppliers/${psId}`, data).then((r) => r.data),
  removeSupplier: (id: number, psId: number) => api.delete(`/products/${id}/suppliers/${psId}`),
  listComponents: (id: number) => api.get(`/products/${id}/components`).then((r) => r.data),
  addComponent: (id: number, data: object) => api.post(`/products/${id}/components`, data).then((r) => r.data),
  updateComponent: (id: number, compId: number, data: object) => api.patch(`/products/${id}/components/${compId}`, data).then((r) => r.data),
  removeComponent: (id: number, compId: number) => api.delete(`/products/${id}/components/${compId}`),
  listMappings: (params?: object) => api.get("/products/mappings", { params }).then((r) => r.data),
  createMapping: (data: object) => api.post("/products/mappings", data).then((r) => r.data),
  deleteMapping: (componentId: number) => api.delete(`/products/mappings/${componentId}`),
  importMappingsCsv: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return api.post("/products/mappings/import/csv", fd).then((r) => r.data);
  },
};

// Suppliers
export const suppliersApi = {
  list: (params?: object) => api.get("/suppliers", { params }).then((r) => r.data),
  get: (id: number) => api.get(`/suppliers/${id}`).then((r) => r.data),
  create: (data: object) => api.post("/suppliers", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/suppliers/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/suppliers/${id}`),
  inventory: (id: number) => api.get(`/suppliers/${id}/inventory`).then((r) => r.data),
  updateStock: (id: number, psId: number, stock: number) =>
    api.patch(`/suppliers/${id}/inventory/${psId}`, null, { params: { stock } }).then((r) => r.data),
  orders: (id: number, params?: object) => api.get(`/suppliers/${id}/orders`, { params }).then((r) => r.data),
  invoices: (id: number) => api.get(`/suppliers/${id}/invoices`).then((r) => r.data),
  createInvoice: (id: number, data: object) => api.post(`/suppliers/${id}/invoices`, data).then((r) => r.data),
  updateInvoice: (id: number, invId: number, data: object) => api.patch(`/suppliers/${id}/invoices/${invId}`, data).then((r) => r.data),
  listProducts: (id: number, params?: { date_from?: string; date_to?: string }) =>
    api.get(`/suppliers/${id}/products`, { params }).then((r) => r.data),
  createProduct: (id: number, data: object) => api.post(`/suppliers/${id}/products`, data).then((r) => r.data),
  updateProduct: (id: number, spId: number, data: object) => api.patch(`/suppliers/${id}/products/${spId}`, data).then((r) => r.data),
  deleteProduct: (id: number, spId: number) => api.delete(`/suppliers/${id}/products/${spId}`),
  previewInvoiceFromOrders: (id: number) => api.get(`/suppliers/${id}/invoices/preview-from-orders`).then((r) => r.data),
  createInvoiceFromOrders: (id: number, data: object) => api.post(`/suppliers/${id}/invoices/create-from-orders`, data).then((r) => r.data),
  generateAllInvoices: () => api.post(`/suppliers/invoices/generate-all`).then((r) => r.data),
  invoicePdfUrl: (id: number, invId: number) => `/api/v1/suppliers/${id}/invoices/${invId}/pdf`,
  importCatalog: (id: number, file: File) => {
    const fd = new FormData(); fd.append("file", file);
    return api.post(`/suppliers/${id}/products/import/csv`, fd).then((r) => r.data);
  },
  exportCatalog: (id: number, filename: string) =>
    api.get(`/suppliers/${id}/products/export.csv`, { responseType: "blob" }).then((r) => {
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a"); a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
    }),
  downloadCatalogTemplate: (id: number) =>
    api.get(`/suppliers/${id}/products/template.csv`, { responseType: "blob" }).then((r) => {
      const url = URL.createObjectURL(r.data);
      const a = document.createElement("a"); a.href = url; a.download = "catalog_template.csv"; a.click();
      URL.revokeObjectURL(url);
    }),
};

// Orders
export const ordersApi = {
  list: (params?: object) => api.get("/orders", { params }).then((r) => r.data),
  get: (id: number) => api.get(`/orders/${id}`).then((r) => r.data),
  create: (data: object) => api.post("/orders", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/orders/${id}`, data).then((r) => r.data),
  updateLineItem: (orderId: number, liId: number, data: object) =>
    api.patch(`/orders/${orderId}/line-items/${liId}`, data).then((r) => r.data),
  assignSupplier: (orderId: number, liId: number, data: object) =>
    api.patch(`/orders/${orderId}/line-items/${liId}/assign-supplier`, data).then((r) => r.data),
  createLabel: (orderId: number, data: object) => api.post(`/orders/${orderId}/labels`, data).then((r) => r.data),
  listLabels: (orderId: number) => api.get(`/orders/${orderId}/labels`).then((r) => r.data),
  markLabelPrinted: (orderId: number, labelId: number) => api.post(`/orders/${orderId}/labels/${labelId}/mark-printed`).then((r) => r.data),
  updateLabel: (orderId: number, labelId: number, data: object) => api.patch(`/orders/${orderId}/labels/${labelId}`, data).then((r) => r.data),
  uploadLabel: (orderId: number, labelId: number, file: File) => {
    return new Promise<any>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => {
        const result = reader.result as string;
        const b64 = result.includes(",") ? result.split(",")[1] : result;
        api.post(`/orders/${orderId}/labels/${labelId}/upload-b64`, { data: b64 })
          .then((r) => resolve(r.data))
          .catch(reject);
      };
      reader.onerror = () => reject(new Error("Failed to read file"));
      reader.readAsDataURL(file);
    });
  },
  regenerateLabel: (orderId: number, labelId: number, size: string) =>
    api.post(`/orders/${orderId}/labels/${labelId}/regenerate`, null, { params: { size } }).then((r) => r.data),
  labelDownloadUrl: (orderId: number, labelId: number) => `/api/v1/orders/${orderId}/labels/${labelId}/download`,
  parcelEstimate: (orderId: number, params?: object) => api.get(`/orders/${orderId}/parcel-estimate`, { params }).then((r) => r.data),
  syncTracking: (orderId: number) => api.post(`/orders/${orderId}/sync-tracking`).then((r) => r.data),
  bulkLabels: (params: { date: string; supplier_id?: number }) =>
    api.get("/orders/bulk-labels", { params, responseType: "blob" }).then((r) => r.data),
  bulkFulfill: (params: { date: string; supplier_id?: number }) =>
    api.post("/orders/bulk-fulfill", null, { params }).then((r) => r.data),
  bulkLabelsUrl: (params: { date: string; supplier_id?: number }) => {
    const qs = new URLSearchParams({ date: params.date, ...(params.supplier_id != null ? { supplier_id: String(params.supplier_id) } : {}) });
    return `/api/v1/orders/bulk-labels?${qs}`;
  },
  listDelayed: () => api.get("/orders/delayed").then((r) => r.data),
};

// Marketplace
export const marketplaceApi = {
  listConnections: () => api.get("/marketplace/connections").then((r) => r.data),
  createConnection: (data: object) => api.post("/marketplace/connections", data).then((r) => r.data),
  updateConnection: (id: number, data: object) => api.patch(`/marketplace/connections/${id}`, data).then((r) => r.data),
  deleteConnection: (id: number) => api.delete(`/marketplace/connections/${id}`),
  testConnection: (id: number) => api.post(`/marketplace/connections/${id}/test`).then((r) => r.data),
  debugConnection: (id: number) => api.post(`/marketplace/connections/${id}/debug`).then((r) => r.data),
  syncOrders: (id: number, opts?: { forceRefresh?: boolean; createdAfter?: string }) => {
    const params = new URLSearchParams();
    if (opts?.forceRefresh) params.set("force_refresh", "true");
    if (opts?.createdAfter) params.set("created_after", opts.createdAfter);
    const qs = params.toString() ? `?${params.toString()}` : "";
    return api.post(`/marketplace/connections/${id}/sync-orders${qs}`).then((r) => r.data);
  },
  syncProducts: (id: number) => api.post(`/marketplace/connections/${id}/sync-products`).then((r) => r.data),
  listListings: (params?: object) => api.get("/marketplace/listings", { params }).then((r) => r.data),
  createListing: (data: object) => api.post("/marketplace/listings", data).then((r) => r.data),
  updateListing: (id: number, data: object) => api.patch(`/marketplace/listings/${id}`, data).then((r) => r.data),
  push: (data: object) => api.post("/marketplace/push", data).then((r) => r.data),
  autoMap: () => api.post("/marketplace/listings/auto-map").then((r) => r.data),
};

// Auth & Users
export const authApi = {
  login: (data: object) => api.post("/auth/login", data).then((r) => r.data),
  me: () => api.get("/auth/me").then((r) => r.data),
};

export const usersApi = {
  list: () => api.get("/users").then((r) => r.data),
  create: (data: object) => api.post("/users", data).then((r) => r.data),
  update: (id: number, data: object) => api.patch(`/users/${id}`, data).then((r) => r.data),
  delete: (id: number) => api.delete(`/users/${id}`),
};

// Reports
export const reportsApi = {
  summary: (params?: object) => api.get("/reports/summary", { params }).then((r) => r.data),
  byMarketplace: () => api.get("/reports/by-marketplace").then((r) => r.data),
  bySupplier: () => api.get("/reports/by-supplier").then((r) => r.data),
  inventoryAlert: (threshold?: number) => api.get("/reports/inventory-alert", { params: { threshold } }).then((r) => r.data),
  stockInsights: (params?: { days?: number; threshold?: number; target_days?: number }) => api.get("/reports/stock-insights", { params }).then((r) => r.data),
  supplierScorecard: (supplier_id: number, days: number = 30) => api.get("/reports/supplier-scorecard", { params: { supplier_id, days } }).then((r) => r.data),
  marginBreakdown: (params?: { from_date?: string; to_date?: string }) => api.get("/reports/margin-breakdown", { params }).then((r) => r.data),
  ordersBreakdown: (params?: { from_date?: string; to_date?: string }) => api.get("/reports/orders-breakdown", { params }).then((r) => r.data),
  getDailyBalance: (date: string) => api.get("/reports/daily-balance", { params: { date } }).then((r) => r.data).catch(() => null),
  saveDailyBalance: (date: string, ending_balance: number, top_up: number = 0, external_cogs: number = 0) => api.post("/reports/daily-balance", { date, ending_balance, top_up, external_cogs }).then((r) => r.data).catch(() => null),
};

// EasyPost (admin)
export const easypostApi = {
  getRates: (orderId: number, data: object) => api.post(`/orders/${orderId}/easypost/rates`, data).then((r) => r.data),
  buyLabel: (orderId: number, data: object) => api.post(`/orders/${orderId}/easypost/buy`, data).then((r) => r.data),
  refundLabel: (orderId: number, data: object) => api.post(`/orders/${orderId}/easypost/refund`, data).then((r) => r.data),
};

// Purchase Requests
export const purchaseRequestsApi = {
  list: () => api.get("/purchase-orders/requests").then((r) => r.data),
  create: (data: object) => api.post("/purchase-orders/requests", data).then((r) => r.data),
  updateStatus: (id: number, data: { status: string; amount_paid?: number; approved_by?: string }) =>
    api.patch(`/purchase-orders/requests/${id}/status`, data).then((r) => r.data),
};

// Amazon Shipping (admin)
export const amazonShippingApi = {
  getRates: (orderId: number, data: object) => api.post(`/orders/${orderId}/amazon/rates`, data).then((r) => r.data),
  buyLabel: (orderId: number, data: object) => api.post(`/orders/${orderId}/amazon/buy`, data).then((r) => r.data),
};
