# Laundry Management Mobile App (Flutter)

This repository is an **Odoo module** (`laundry_management`) with existing JSON-RPC APIs that can be consumed by a Flutter app.

## What already exists in backend

The module exposes these APIs in `laundry_management/controllers/api_controller.py`:

- `POST /api/login`
- `GET /api/laundry/orders`
- `POST /api/laundry/order/create`
- `POST /api/laundry/order/update`
- `GET /api/laundry/order/<id>`

These are enough to bootstrap an MVP mobile app for:

1. Login
2. List orders
3. View order details
4. Create order
5. Update order status

## Suggested app scope (Phase 1)

- Authentication with persisted session cookie
- Orders dashboard
- Order detail screen
- Create order screen
- Basic status update action

## Included starter app

A starter Flutter app is provided under:

`mobile_app/flutter_laundry_app`

It includes:

- JSON-RPC client service
- Domain model (`LaundryOrder`)
- Login + Orders UI flow
- Basic widget test

## How to run

1. Install Flutter SDK.
2. Start Odoo backend.
3. Update `baseUrl` in `lib/main.dart` to your server URL.
4. Run:

```bash
cd mobile_app/flutter_laundry_app
flutter pub get
flutter run
```

## Notes

- The backend uses `type='jsonrpc'`; requests are sent in JSON-RPC envelope.
- Session cookies are required after login; this starter includes cookie forwarding logic.
