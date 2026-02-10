# Flutter Mobile App Analysis for `laundry_management`

## Repository analysis

This repository is an Odoo addon focused on laundry operations:

- Models: orders, contracts, pickup requests, services
- Views: backend and portal XML views
- Controllers: web/portal controllers plus JSON-RPC API controller

For mobile integration, the key file is:

- `laundry_management/controllers/api_controller.py`

## Available API endpoints for mobile

1. `/api/login` (POST, JSON-RPC)
   - Inputs: `db`, `username`, `password`
   - Returns: `status`, `uid`, `name`, `session_id`

2. `/api/laundry/orders` (GET, JSON-RPC)
   - Auth required
   - Returns visible orders list

3. `/api/laundry/order/create` (POST, JSON-RPC)
   - Auth required
   - Inputs: `partner_id`, `service_ids`

4. `/api/laundry/order/update` (POST, JSON-RPC)
   - Auth required
   - Inputs: `order_id`, `state`

5. `/api/laundry/order/<id>` (GET, JSON-RPC)
   - Auth required
   - Returns detailed order payload

## Recommended Flutter architecture

- `data/services/odoo_api_service.dart` for JSON-RPC transport and auth cookie
- `data/models/` for DTO/model mapping
- `features/auth/` for login flow
- `features/orders/` for list/detail/create/update
- State management: start with `setState`; migrate to Riverpod/Bloc when app grows

## Immediate MVP plan

- Phase 1 (included in this commit as starter code)
  - Login screen
  - Orders list screen
  - Session reuse via `session_id` cookie

- Phase 2
  - Order detail + pull-to-refresh
  - Create order form
  - Update status actions with validation

- Phase 3
  - Offline cache (Hive/sqflite)
  - Push notifications
  - Role-based UI and better error telemetry

## Backend suggestions for smoother mobile integration

- Add versioned routes (`/api/v1/...`).
- Normalize error envelopes for all methods.
- Add service catalog endpoint for `service_ids` discovery.
- Add pagination for orders endpoint.
- Consider token-based auth in addition to session cookie.
