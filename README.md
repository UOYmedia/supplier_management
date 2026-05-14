# Maga — Supplier Fulfillment Platform

Quản lý sản phẩm, suppliers, đơn hàng và tích hợp marketplace (Amazon, Shopify).

## Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI + SQLAlchemy (async) + PostgreSQL |
| Frontend | Next.js 14 + TailwindCSS + React Query |
| Queue | Redis (background tasks) |
| Infra | Docker Compose |

## Khởi động nhanh

```bash
# 1. Copy env
cp .env.example .env

# 2. Khởi động tất cả services
docker compose up -d

# 3. Mở browser
# Frontend: http://localhost:3000
# Backend API docs: http://localhost:8000/docs
```

## Cấu trúc dự án

```
maga/
├── backend/
│   └── app/
│       ├── models/          # SQLAlchemy models
│       ├── schemas/         # Pydantic request/response
│       ├── api/v1/          # REST API routes
│       └── integrations/    # Amazon SP-API & Shopify connectors
├── frontend/
│   └── app/
│       ├── page.tsx         # Dashboard
│       ├── products/        # Quản lý sản phẩm
│       ├── suppliers/       # Quản lý suppliers + inventory + invoices
│       ├── orders/          # Quản lý đơn hàng + shipping labels
│       └── marketplace/     # Kết nối Amazon/Shopify
└── docker-compose.yml
```

## API Endpoints

### Products  `GET/POST /api/v1/products`
- Import CSV: `POST /api/v1/products/import/csv`
- Suppliers per product: `/api/v1/products/{id}/suppliers`

### Suppliers  `GET/POST /api/v1/suppliers`
- Inventory: `/api/v1/suppliers/{id}/inventory`
- Orders (chỉ thấy sản phẩm của mình): `/api/v1/suppliers/{id}/orders`
- Invoices: `/api/v1/suppliers/{id}/invoices`

### Orders  `GET/POST /api/v1/orders`
- Update line item: `PATCH /api/v1/orders/{id}/line-items/{li_id}`
- Shipping labels: `/api/v1/orders/{id}/labels`

### Marketplace  `/api/v1/marketplace`
- Connections: `/connections` — kết nối Amazon/Shopify
- Push listing: `POST /marketplace/push`
- Sync orders: `POST /marketplace/connections/{id}/sync-orders`

### Reports  `/api/v1/reports`
- `GET /reports/summary`
- `GET /reports/by-marketplace`
- `GET /reports/by-supplier`
- `GET /reports/inventory-alert`

## Tích hợp Marketplace

### Shopify
1. Tạo Private App trong Shopify Admin
2. Lấy Access Token (scopes: `read_products,write_products,read_orders,write_orders`)
3. Thêm connection trên trang Marketplace

### Amazon SP-API
1. Đăng ký Selling Partner API tại [developer.amazonservices.com](https://developer.amazonservices.com)
2. Lấy Client ID, Client Secret, Refresh Token
3. Thêm connection trên trang Marketplace

## Import CSV

Cột bắt buộc: `name`, `sku`  
Cột tùy chọn: `base_cost`, `weight`, `length`, `width`, `height`, `description`

```csv
name,sku,base_cost,weight,length,width,height
Widget A,WID-001,5.50,0.3,20,15,10
Widget B,WID-002,12.00,0.8,30,20,15
```

## Development (không dùng Docker)

```bash
# Backend
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```
