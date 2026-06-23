export type Supplier = "JOE" | "SKY" | "FAIRY"

export interface SKUItem {
  sku: string
  supplier: Supplier
  ordered: number
  available: number
  unit_cost: number
  gap: number
  oversold: number
  avail_final: number
  total_cost: number
  oversold_value: number
  avail_value: number
  status: "ok" | "exact" | "low" | "oversold"
}

export interface POBalance {
  starting_balance: number
  total_cost: number
  available_value: number
  oversold_value: number
  ending_balance: number
}

export function computeItem(
  raw: Omit<SKUItem, "gap" | "oversold" | "avail_final" | "total_cost" | "oversold_value" | "avail_value" | "status">
): SKUItem {
  const gap = raw.available - raw.ordered
  const oversold = Math.max(0, -gap)
  const avail_final = Math.max(0, gap)
  const total_cost = raw.ordered * raw.unit_cost
  const oversold_value = oversold * raw.unit_cost
  const avail_value = avail_final * raw.unit_cost

  let status: SKUItem["status"]
  if (gap > 3) status = "ok"
  else if (gap > 0) status = "low"
  else if (gap === 0) status = "exact"
  else status = "oversold"

  return { ...raw, gap, oversold, avail_final, total_cost, oversold_value, avail_value, status }
}

export function computeBalance(items: SKUItem[], startingBalance: number): POBalance {
  const total_cost = items.reduce((s, i) => s + i.total_cost, 0)
  const available_value = items.reduce((s, i) => s + i.avail_value, 0)
  const oversold_value = items.reduce((s, i) => s + i.oversold_value, 0)
  const ending_balance = startingBalance - total_cost
  return { starting_balance: startingBalance, total_cost, available_value, oversold_value, ending_balance }
}

export const SUPPLIER_INFO: Record<Supplier, { name: string; address: string; city: string }> = {
  JOE:   { name: "Terry Panter Nursery",  address: "70 B.Panter Rd.",  city: "McMinnville, TN 37110" },
  SKY:   { name: "Sky Nursery",           address: "123 Garden Way",   city: "Nashville, TN 37201"   },
  FAIRY: { name: "Fairy Garden Nursery",  address: "456 Bloom Ave",    city: "Knoxville, TN 37902"   },
}

export const RAW_ITEMS: Omit<SKUItem, "gap" | "oversold" | "avail_final" | "total_cost" | "oversold_value" | "avail_value" | "status">[] = [
  { sku: "Meyer Lemon Tree",       supplier: "JOE",   ordered: 5,  available: 8,  unit_cost: 15.00 },
  { sku: "Baby Breath",            supplier: "JOE",   ordered: 6,  available: 4,  unit_cost: 5.00  },
  { sku: "Crown of Thorn Red",     supplier: "JOE",   ordered: 10, available: 7,  unit_cost: 7.50  },
  { sku: "French Tarragon",        supplier: "JOE",   ordered: 4,  available: 12, unit_cost: 5.00  },
  { sku: "Spanish Lavender",       supplier: "SKY",   ordered: 8,  available: 8,  unit_cost: 5.00  },
  { sku: "English Lavender",       supplier: "SKY",   ordered: 4,  available: 10, unit_cost: 5.00  },
  { sku: "Night Blooming Jasmine", supplier: "SKY",   ordered: 6,  available: 6,  unit_cost: 6.50  },
  { sku: "Rasp Buddleia",          supplier: "SKY",   ordered: 5,  available: 3,  unit_cost: 6.50  },
  { sku: "Peppermint",             supplier: "FAIRY", ordered: 3,  available: 5,  unit_cost: 5.00  },
  { sku: "Confederate Jasmine",    supplier: "FAIRY", ordered: 7,  available: 7,  unit_cost: 6.50  },
  { sku: "Thai Constellation",     supplier: "FAIRY", ordered: 2,  available: 4,  unit_cost: 13.50 },
]

export function fmt(n: number) {
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
