# MAGA FBM Tool — Dev Status (Stagging_jun8)

> Reviewed: 2026-06-25  
> Branch: `Stagging_jun8`  
> Stack: Next.js 14 + FastAPI + PostgreSQL

---

## Quick summary

| # | Feature | Done | Critical gap |
|---|---|---|---|
| 1 | Daily stock table | **85%** | Column order minor; logic correct |
| 2 | Stock Request / ordering | **50%** | PAID→stock increment missing; backend auth missing |
| 3 | Balance / period view | **35%** | Period is cumulative filter, not independent snapshot |
| 4 | Daily Invoice | **40%** | No PDF export, no auto-create, no footer A/R |
| 5 | SKU Mapping | **70%** | Engine solid; data not filled yet (blocker) |
| 6 | Bulk Label Import | **15%** | Full implementation in `main`, not in Stagging |

---

## Feature 1 — Daily stock table

**Implemented:**
- Status logic correct: `gap > 5` → OK, `0–5` → Low, `< 0` → Oversold
- Stock Left displays 0 (not negative), Oversold = abs(gap) ✓
- Per-column filter dropdowns ✓
- Status quick-filter (All / OK / Low / Oversold) with count badges ✓
- Unit Price hidden by default, toggle button to show ✓
- Hover Item name → tooltip shows unit price (`SKUTable.tsx:366`) ✓

**Missing / wrong:**
- Column order doesn't match spec. Spec: `Item | Ordered | Unit Price | Stock Avail | Stock Left | Oversold | Status`. Actual: `Item | Stock Avail | Ordered | Unit Price | ...` — columns 2 and 3 are swapped.
- Extra columns added (Today Cost, Amt Left) — useful but not in spec.

**Effort to fix:** Small — reorder columns in `SKUTable.tsx:303–315`.

---

## Feature 2 — Stock Request / ordering from supplier

**Implemented:**
- Request form: requester (Zoe/Grace/Jenny), supplier, product name, qty, unit cost, auto-total, notes ✓
- Status flow: PENDING → PARTIALLY_PAID → PAID → CANCELLED ✓
- Jenny-only approval enforced **in frontend** (`page.tsx:232`)
- `approved_by`, `paid_date`, `amount_paid` stored on PAID/PARTIALLY_PAID ✓
- Request history table (all requests by date) ✓

**Missing / wrong:**

1. **PAID → Stock auto-increment missing** (critical)  
   `purchase_orders.py:341–367` — update_request_status sets dates/approved_by but never touches `SupplierProduct.stock_quantity`. The core loop "Jenny approves → stock goes up" is not closed.

2. **Backend has no auth check**  
   `PATCH /purchase-orders/requests/{id}/status` depends only on `get_db`, no `get_current_user`. Anyone who can reach the API can change status to PAID. Frontend guard alone is insufficient.

3. **No filter on request history**  
   `GET /purchase-orders/requests` returns all, no WHERE clause for requester/supplier/status. No filter UI in `RequestList.tsx`.

4. **No totals row**  
   No aggregate "total paid / total unpaid" in history view.

**Effort to fix:**  
- PAID→stock: ~20 lines in `purchase_orders.py` (query `SupplierProduct`, increment `stock_quantity`, commit).  
- Backend auth: add `current_supplier = Depends(get_current_user)` + role check.  
- History filter: add query params to `list_requests()` + filter UI.

---

## Feature 3 — Balance / period view

**Implemented:**
- Period filter UI: Today / This Week / Last Week / This Month / Custom Range ✓
- 3-number display (opening balance, today cost, closing) in `POMetrics.tsx` ✓
- Balance formula: `closing = opening - total_cost` ✓

**Missing / wrong — core logic is wrong:**

The spec requires each period to be an **independent snapshot**:
```
Stock Left = opening_stock(start of period) + Purchased(PAID in period) - Sold(in period)
```

What's actually implemented (`purchase_orders.py:187–202`):
```python
agg[key]["ordered"] += po.qty_ordered   # cumulative sum across all days in period
agg[key]["available"] = po.qty_available  # latest day's value — not opening stock
```

This means:
- "Available" = whatever was last recorded, not the opening inventory of the period.
- "Ordered" = sum of all daily PO records in range, not units sold in that window via real orders.
- Switching "Last Week → This Week" does NOT give an independent reset — it just filters a different slice of the same cumulative data.

**What's needed:**
- An `opening_stock` snapshot per SKU per period start date (either stored snapshot or reconstructed via `OrderFulfillmentItem` activity before `period_start`).
- `Purchased(PAID)` = sum `PurchaseOrder.qty_ordered WHERE status=PAID AND requested_date IN period`.
- `Sold(in period)` = sum `OrderFulfillmentItem.quantity WHERE ordered_at IN period` (join through `OrderLineItem → Order`).

**Note:** The date-range filter just added to `GET /suppliers/{id}/products` (commit `5fc3726`) gives `ordered` in a window, but it's from `OrderFulfillmentItem`, not the `purchase_orders` table. These are different data sources and both need to exist for F3 to work properly.

**Effort to fix:** Medium–large. Requires rethinking the period endpoint's query structure.

---

## Feature 4 — Daily Invoice

**Implemented:**
- `Invoice` + `InvoiceLineItem` models with status enum (pending/sent/paid/overdue) ✓
- CRUD endpoints: list, create, create-from-orders, update status (`suppliers.py:578–757`) ✓
- Preview endpoint (unfulfilled items before committing invoice) ✓
- Supplier portal can view own invoices (`portal.py:699–721`) ✓

**Missing / wrong:**

1. **No PDF export** — spec says "Export PDF opens new tab". The PO page has a PDF generator (`/api/v1/purchase-orders/generate-pdf`) but invoices have nothing. No `weasyprint`/`reportlab` calls in invoice endpoints.

2. **Invoice body incomplete** — `InvoiceLineItem` stores description/qty/unit_amount/total_amount. Missing: stock_left, oversold qty, status per line. These can't be backfilled from the model without joining `OrderFulfillmentItem`.

3. **No remittance slip on invoice** — `RemittanceSlip.tsx` exists in PO card context but is not wired into invoice display.

4. **No auto-create at end of day** — no cron job, no scheduled task, no one-click "create today's invoices for all suppliers" button in admin UI.

5. **No Copy button** — spec requires copying invoice text to paste into supplier chat.

**Effort to fix:** Large. PDF generation requires a template; body needs richer line-item data; auto-create needs a cron or webhook trigger.

---

## Feature 5 — SKU Mapping

**Implemented:**
- `Product ↔ ProductSupplier ↔ Supplier` + `ProductComponent → SupplierProduct` models ✓
- `GET/POST/DELETE /mappings` endpoints (`products.py:83–412`) ✓
- CSV bulk import with smart matching (case-insensitive, supplier disambiguation, encoding detection) ✓
- Multi-supplier per product supported ✓
- Stock deduction on shipment uses `OrderFulfillmentItem.supplier_product_id` ✓
- Frontend "SKU Mappings" page with add/import/delete ✓

**Missing / wrong:**
- No dedicated reconciliation table UI: Amazon SKU ↔ supplier name ↔ supplier in a single view.
- No bulk-edit UI (CSV import works, but no in-page mass update).
- No search/browse for supplier products when creating a mapping in the UI.

**Blocker (not a code problem):**  
The engine is solid but the **mapping data is empty**. Until `ProductComponent` rows exist linking Amazon SKUs to `SupplierProduct`, all downstream features (stock table, period view, invoices) will show 0 for pending/sold/ordered. This is a data-entry task, not a code task.

**Effort to fix code gaps:** Small–medium (reconciliation view, search in mapping form).

---

## Feature 6 — Bulk Label Import

**Note:** A more complete implementation exists on `main` (anh dev's work). The assessment below is `Stagging_jun8` only.

**Implemented:**
- Single-file label upload: `POST /{order_id}/labels/{label_id}/upload` (PDF validation + base64 store) ✓
- PDF utilities in `integrations/pdf_labels.py`: stamp_label, concat_pdfs, image_to_pdf ✓
- Bulk label *download* endpoint (GET /bulk-labels) — note: this is download, not upload ✓

**Missing (in Stagging):**
1. No bulk upload endpoint — no `POST /orders/bulk-label-upload` accepting multiple files.
2. No filename → OrderID parsing — current upload requires `order_id` in URL, not filename.
3. No supplier assignment popup when order has no supplier.
4. No customer info autofill (buyer_name/email/shipping_address exist on Order model, but no fill logic).
5. No order status → Processing transition on label apply.

**Recommendation:** Don't rebuild F6 in Stagging. Pull/merge from `main` and handle conflicts (which are additive — confirmed earlier).

---

## Root cause analysis — why numbers are all zeros in live mode

The whole system depends on this chain:
```
Amazon Order
  → sync creates OrderLineItem (product_id = null if SKU not matched)
        → fulfillment_helper creates OrderFulfillmentItem (only if product_id exists AND ProductComponent exists)
              → _supplier_product_out() sums OFI.quantity for pending/sold
```

If any link is broken → pending/sold = 0 → stock table, balance, invoices all show nothing.

**Current breaks in staging:**
- Amazon SKU → Product match fails (different SKU formats, no `ProductComponent` rows).
- Team fulfills orders on Amazon directly, not on the tool → `fulfill_status` never updates past `unfulfilled`.

**Stock suppliers (JOE):** affected — pending/sold = 0, stock stays at whatever was manually set.  
**Balance suppliers (SKY/FAIRY):** doubly affected — they don't use stock columns anyway, and their balance deduction logic also relies on OFI data.

---

## BUG (branch `main`) — F6 label stamping skips manually-uploaded Amazon labels

**Symptom:** When a label is downloaded from Amazon, uploaded to its matching order via
`POST /orders/{id}/labels/{label_id}/upload`, then re-downloaded from the tool
(`GET /orders/bulk-labels`), the product info line (Qty + NAME + size + date) is **NOT**
stamped onto the label. It only stamps for labels bought through the tool (EasyPost).

**Root cause:** The stamp path is gated on `label.label_url`, but manual uploads only
populate `label.label_data`.

- `upload_label_pdf` (`orders.py:978`) stores the raw PDF into `label.label_data` and
  never sets `label_url`, never stamps.
- `_pdf_for_label` (`orders.py:364`) inside `bulk_labels`:
  ```python
  if label.label_url:                       # EasyPost-bought labels only
      ... await _stamp_carrier_for_label(...)   # ← stamps here
  if label.label_data:                      # manually-uploaded Amazon labels land here
      return decode_label_data(label.label_data)   # ← returns raw, NO stamp
  ```

**Fix direction:** In `_pdf_for_label`, route the `label_data` branch through
`_stamp_carrier_for_label` too — decode the stored PDF first, then stamp it, instead of
returning it raw. Guard against double-stamping (the `label_data` may already be stamped
from a prior run; safest is to keep `label_url` as the pristine source and only stamp
`label_data` when no `label_url` exists). `regenerate_label` (`orders.py:1032`) is also
`label_url`/`shipment_id`-gated, so it doesn't cover this case either.

### Full stamping chain (for reference when fixing)

```
GATE: label.label_url must exist  ──❌ no url → return raw (THE BUG: Amazon uploads have no url)
   ↓ yes
_catalog_items_for_line_item (orders.py:1355) — resolve the NAME, 3 sources in priority:
   1. OrderFulfillmentItem → SupplierProduct   (name = short_name | name | product_name)
   2. line_item.product_id → ProductComponent → SupplierProduct
   3. fallback: li.product_name (raw Amazon name)
   ↓
_build_label_lines (pdf_labels.py:38) — "<Qty> <NAME> <size> - <date>"
   • size only if SupplierProduct has it
   • date only for supplier named "JOE"
   • clipped to 55 chars
   ↓
_find_blank_band (pdf_labels.py:85) — scan pixels for white band in footer
   ↓
stamp_label / _crop_and_stamp_fitz (pdf_labels.py:300) — draw text, barcode preserved
```

**Two failure points to be aware of:**
1. `label_url` gate → manually-uploaded Amazon labels never stamp (this bug).
2. SKU mapping → even when it stamps, an unmapped order falls to the raw `product_name`
   fallback instead of the clean supplier catalog name.

So for a correct + readable stamp you need BOTH: label has `label_url` (or the fix above)
AND the order is mapped to a `SupplierProduct` (ideally with `short_name`/`size`).

---

## Priority list for dev handoff

| Priority | Task | Effort | Unblocks |
|---|---|---|---|
| P0 | Fill `ProductComponent` data (SKU mapping) | Data entry | Everything |
| P1 | `PAID → SupplierProduct.stock_quantity += qty` in `purchase_orders.py` | Small (~20 lines) | F2 closes loop |
| P1 | Backend auth on `PATCH /requests/{id}/status` | Small | Real access control |
| P2 | Fix period logic (F3) — per-period snapshot with opening stock | Medium–large | F3 trustworthy |
| P2 | Invoice PDF + body (stock_left/oversold per line) | Large | F4 usable |
| P3 | Fix column order in SKUTable | Trivial | F1 matches spec |
| P3 | Merge F6 from `main` → `Stagging_jun8` | Merge + conflict resolve | F6 in Stagging |

---

## Files to reference

| File | Relevance |
|---|---|
| `backend/app/api/v1/purchase_orders.py` | F2 status update (missing stock logic), F3 period query |
| `backend/app/api/v1/suppliers.py:774` | `_supplier_product_out()` — where pending/sold are counted |
| `backend/app/integrations/fulfillment_helper.py` | Chain that creates OFI — requires ProductComponent data |
| `frontend/components/purchase-orders/SKUTable.tsx:303` | Column order fix |
| `frontend/app/purchase-orders/page.tsx:232` | Jenny-only check (frontend only) |
| `backend/app/models/order.py:79` | OrderFulfillmentItem — central table for all counts |
