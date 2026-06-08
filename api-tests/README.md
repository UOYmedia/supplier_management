# API Tests

HTTP test files for VS Code [REST Client](https://marketplace.visualstudio.com/items?itemName=humao.rest-client) extension.

## Files

| File | Coverage |
|------|----------|
| `easypost.http` | EasyPost rates + buy label endpoints |

## Setup

1. Install VS Code extension **REST Client** (`humao.rest-client`)
2. Open any `.http` file
3. Run the **Login** request and paste the token into `@authToken`
4. Run requests in order (rates -> buy)

## Environments

Edit `@baseUrl` in each file:

| Env | URL |
|-----|-----|
| Railway (prod) | `https://frontend-production-ecfc.up.railway.app/api/v1` |
| Local | `http://localhost:3000/api/v1` |
| Backend direct | `http://localhost:8000/api/v1` |

## EasyPost Flow

```
POST /orders/{id}/easypost/rates   -> returns shipment_id + list of rates
POST /orders/{id}/easypost/buy     -> buys the chosen rate_id
```

Each EasyPost shipment can only be purchased **once**.
To retry, call `/rates` again to get a fresh `shipment_id`.
