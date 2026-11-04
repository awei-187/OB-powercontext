import json

from .orders import list_orders

orders = [
    {"id": 1, "status": "pending"},
    {"id": 2, "status": "paid"},
    {"id": 3, "status": "paid"},
]
print(json.dumps(list_orders(orders), ensure_ascii=False))
