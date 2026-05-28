import axios from "axios";

function downloadBlob(data: Blob, filename: string) {
  const url = URL.createObjectURL(data);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export const api = axios.create({
  baseURL: "/api/v1",
  headers: { "Content-Type": "application/json" },
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
    return api.post("/products/import/csv", fd, { headers: { "Content-Type": "multipart/form-data" } }).then((r) => r.data);
  },
  listSuppliers: (id: number) => api.get(`/products/${id}/suppliers`).then((r) => r.data),
  addSupplier: (id: number, data: object) => api.post(`/products/${id}/suppliers`, data).then((r) => r.data),
  updateSupplier: (id: number, psId: number, data: object) => api.patch(`/products/${id}/suppliers/${psId}`, data).then((r) => r.data),
  removeSupplier: (id: number, psId: number) => api.delete(`/products/${id}/suppliers/${psId}`),
  // Product components
  listComponents: (id: number) => api.get(`/products/${id}/components`).then((r) => r.data),
  addComponent: (id: number, data: object) => api.post(`/products/${id}/components`, data).then((r) => r.data),
  updateComponent: (id: number, compId: number, data: object) =>
    api.patch(`/products/${id}/components/${compId}`, data).then((r) => r.data),
  removeComponent: (id: number, compId: number) => api.delete(`/products/${id}/components/${compId}`),
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
  // Supplier product catalog
  listProducts: (id: number) => api.get(`/suppliers/${id}/products`).then((r) => r.data),
  createProduct: (id: number, data: object) => api.post(`/suppliers/${id}/products`, data).then((r) => r.data),
  updateProduct: (id: number, spId: number, data: object) =>
    api.patch(`/suppliers/${id}/products/${spId}`, data).then((r) => r.data),
  deleteProduct: (id: number, spId: number) => api.delete(`/suppliers/${id}/products/${spId}`),
  exportCatalog: (id: number, filename: string) =>
    api
      .get(`/suppliers/${id}/products/export.csv`, { responseType: "blob" })
      .then((r) => downloadBlob(r.data, filename)),
  downloadCatalogTemplate: (id: number) =>
    api
      .get(`/suppliers/${id}/products/template.csv`, { responseType: "blob" })
      .then((r) => downloadBlob(r.data, "catalog_template.csv")),
  importCatalog: (id: number, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return api
      .post(`/suppliers/${id}/products/import/csv`, fd, {
        headers: { "Content-Type": "multipart/form-data" },
      })
      .then((r) => r.data);
  },
  orders: (id: number, params?: object) => api.get(`/suppliers/${id}/orders`, { params }).then((r) => r.data),
  invoices: (id: number) => api.get(`/suppliers/${id}/invoices`).then((r) => r.data),
  createInvoice: (id: number, data: object) => api.post(`/suppliers/${id}/invoices`, data).then((r) => r.data),
  updateInvoice: (id: number, invId: number, data: object) => api.patch(`/suppliers/${id}/invoices/${invId}`, data).then((r) => r.data),
};

// EasyPost
export const easypostApi = {
  getRates: (orderId: number, data: object) =>
    api.post(`/orders/${orderId}/easypost/rates`, data).then((r) => r.data),
  buyLabel: (orderId: number, data: object) =>
    api.post(`/orders/${orderId}/easypost/buy`, data).then((r) => r.data),
};

// Amazon shipping (MFN)
export const amazonShippingApi = {
  getRates: (orderId: number, data: object) =>
    api.post(`/orders/${orderId}/amazon/rates`, data).then((r) => r.data),
  buyLabel: (orderId: number, data: object) =>
    api.post(`/orders/${orderId}/amazon/buy`, data).then((r) => r.data),
  downloadLabelUrl: (orderId: number, labelId: number) =>
    `/api/v1/orders/${orderId}/labels/${labelId}/download`,
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
  listFulfillments: (orderId: number, liId: number) =>
    api.get(`/orders/${orderId}/line-items/${liId}/fulfillments`).then((r) => r.data),
  updateFulfillment: (orderId: number, liId: number, fiId: number, data: object) =>
    api.patch(`/orders/${orderId}/line-items/${liId}/fulfillments/${fiId}`, data).then((r) => r.data),
  createLabel: (orderId: number, data: object) => api.post(`/orders/${orderId}/labels`, data).then((r) => r.data),
  listLabels: (orderId: number) => api.get(`/orders/${orderId}/labels`).then((r) => r.data),
  labelDownloadUrl: (orderId: number, labelId: number) => `/api/v1/orders/${orderId}/labels/${labelId}/download`,
  parcelEstimate: (orderId: number, params: { supplier_id?: number; line_item_ids?: number[] }) => {
    const q: any = {};
    if (params.supplier_id != null) q.supplier_id = params.supplier_id;
    if (params.line_item_ids?.length) q.line_item_ids = params.line_item_ids.join(",");
    return api.get(`/orders/${orderId}/parcel-estimate`, { params: q }).then((r) => r.data);
  },
};

// Marketplace
export const marketplaceApi = {
  listConnections: () => api.get("/marketplace/connections").then((r) => r.data),
  createConnection: (data: object) => api.post("/marketplace/connections", data).then((r) => r.data),
  updateConnection: (id: number, data: object) => api.patch(`/marketplace/connections/${id}`, data).then((r) => r.data),
  deleteConnection: (id: number) => api.delete(`/marketplace/connections/${id}`),
  testConnection: (id: number) => api.post(`/marketplace/connections/${id}/test`).then((r) => r.data),
  syncOrders: (id: number) => api.post(`/marketplace/connections/${id}/sync-orders`).then((r) => r.data),
  syncProducts: (id: number) => api.post(`/marketplace/connections/${id}/sync-products`).then((r) => r.data),
  syncLocations: (id: number) => api.post(`/marketplace/connections/${id}/sync-locations`).then((r) => r.data),
  syncListings: (id: number) => api.post(`/marketplace/connections/${id}/sync-listings`).then((r) => r.data),
  listListings: (params?: object) => api.get("/marketplace/listings", { params }).then((r) => r.data),
  createListing: (data: object) => api.post("/marketplace/listings", data).then((r) => r.data),
  updateListing: (id: number, data: object) => api.patch(`/marketplace/listings/${id}`, data).then((r) => r.data),
  autoMap: () => api.post("/marketplace/auto-map").then((r) => r.data),
  push: (data: object) => api.post("/marketplace/push", data).then((r) => r.data),
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
};
