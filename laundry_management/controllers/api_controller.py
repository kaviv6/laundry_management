import re
import secrets
from datetime import timedelta

from odoo import http, fields
from odoo.http import request

TOKEN_TTL_DAYS = 30

VALID_ORDER_STATES = ['draft', 'order', 'cancel']
VALID_PAYMENT_METHODS = ['cod', 'online', 'wallet']
VALID_RIDER_ACTIONS = ['schedule', 'pickup', 'deliver', 'cancel']


class LaundryAPI(http.Controller):

    # ==========================================
    # INTERNAL HELPERS
    # ==========================================

    def _authenticate(self):
        auth_header = request.httprequest.headers.get('Authorization')
        if not auth_header:
            return None, {"status": False, "message": "Token missing"}
        try:
            token = auth_header.replace("Bearer ", "").strip()
        except Exception:
            return None, {"status": False, "message": "Invalid token format"}

        user = request.env['res.users'].sudo().search(
            [('api_token', '=', token)], limit=1
        )
        if not user:
            return None, {"status": False, "message": "Invalid token"}
        if user.api_token_expiry and user.api_token_expiry < fields.Datetime.now():
            return None, {"status": False, "message": "Token expired, please login again"}
        return user, None

    def _is_admin(self, user):
        return (
            user.has_group('laundry_management.group_laundry_manager') or
            user.has_group('base.group_system')
        )

    def _is_rider(self, user):
        return user.has_group('laundry_management.group_laundry_rider')

    def _issue_token(self, user):
        token = secrets.token_hex(32)
        expiry = fields.Datetime.now() + timedelta(days=TOKEN_TTL_DAYS)
        user.sudo().write({'api_token': token, 'api_token_expiry': expiry})
        return token

    @staticmethod
    def _fmt_dt(dt):
        """Return ISO-8601 string or None — consistent format for Flutter."""
        return dt.isoformat() if dt else None

    def _format_order(self, order, include_lines=False):
        subtotal = sum(order.order_line_ids.mapped('amount'))
        data = {
            "id": order.id,
            "name": order.name,
            "customer": order.partner_id.name,
            "customer_id": order.partner_id.id,
            "order_date": self._fmt_dt(order.order_date),
            "state": order.state,
            "subtotal": subtotal,
            "promo_code": order.promo_id.code if order.promo_id else None,
            "promo_discount": order.promo_discount,
            "total_amount": order.total_amount,
            "payment_method": order.payment_method,
            "is_express": order.is_express,
            "eta": self._fmt_dt(order.eta),
            "rider_id": order.rider_id.id if order.rider_id else None,
            "rider_name": order.rider_id.name if order.rider_id else None,
            "garment_count": order.garment_count,
        }
        if include_lines:
            data["note"] = order.note or ''
            data["lines"] = [
                {
                    "id": line.id,
                    "product": line.product_id.name,
                    "service_type": line.service_type_id.name if line.service_type_id else None,
                    "quantity": line.qty,
                    "price_unit": line.price_unit,
                    "subtotal": line.amount,
                    "description": line.description or '',
                }
                for line in order.order_line_ids
            ]
        return data

    def _format_pickup(self, pr, include_lines=False):
        data = {
            "id": pr.id,
            "name": pr.name,
            "customer": pr.partner_id.name,
            "customer_id": pr.partner_id.id,
            "schedule_date": self._fmt_dt(pr.schedule_date),
            "pickup_date": self._fmt_dt(pr.pickup_date),
            "state": pr.state,
            "total_amount": pr.total_amount,
            "payment_method": pr.payment_method,
            "order_id": pr.order_id.id if pr.order_id else None,
            "rider_id": pr.laundry_person_id.id if pr.laundry_person_id else None,
            "rider_name": pr.laundry_person_id.name if pr.laundry_person_id else None,
            "address": {
                "street": pr.street or '',
                "street2": pr.street2 or '',
                "city": pr.city or '',
                "zip": pr.zip or '',
                "state": pr.state_id.name if pr.state_id else '',
                "country": pr.country_id.name if pr.country_id else '',
            },
        }
        if include_lines:
            data["lines"] = [
                {
                    "id": line.id,
                    "product": line.product_id.name,
                    "service_type": line.service_type_id.name if line.service_type_id else None,
                    "quantity": line.qty,
                    "price_unit": line.price_unit,
                    "subtotal": line.amount,
                }
                for line in pr.line_ids
            ]
        return data

    # ==========================================
    # AUTH
    # ==========================================

    @http.route('/api/v1/login', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def login(self, **kwargs):
        login = kwargs.get('username')
        password = kwargs.get('password')

        if not login or not password:
            return {"status": False, "message": "Missing credentials"}

        try:
            auth_info = request.session.authenticate(request.env, {
                'login': login,
                'password': password,
                'type': 'password',
            })
            uid = auth_info.get('uid')
        except Exception:
            return {"status": False, "message": "Invalid credentials"}

        if not uid:
            return {"status": False, "message": "Invalid credentials"}

        user = request.env['res.users'].browse(uid)
        token = self._issue_token(user)

        return {
            "status": True,
            "message": "Login successful",
            "data": {
                "user_id": user.id,
                "name": user.name,
                "email": user.login,
                "token": token,
                "is_rider": self._is_rider(user),
                "is_admin": self._is_admin(user),
            }
        }

    @http.route('/api/v1/logout', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def logout(self, **kwargs):
        user, error = self._authenticate()
        if error:
            return error
        user.sudo().write({'api_token': False, 'api_token_expiry': False})
        return {"status": True, "message": "Logged out successfully"}

    @http.route('/api/v1/signup', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def signup(self, **kwargs):
        name = kwargs.get('name')
        login = kwargs.get('login')
        password = kwargs.get('password')

        if not all([name, login, password]):
            return {"status": False, "message": "Missing required fields: name, login, password"}

        if request.env['res.users'].sudo().search([('login', '=', login)], limit=1):
            return {"status": False, "message": "User already exists"}

        user = request.env['res.users'].sudo().create({
            'name': name,
            'login': login,
            'password': password,
        })

        laundry_group = request.env.ref('laundry_management.group_laundry_user')
        user.sudo().write({'group_ids': [(4, laundry_group.id)]})

        partner_vals = {}
        for field in ('phone', 'street', 'street2', 'city', 'zip'):
            if kwargs.get(field):
                partner_vals[field] = kwargs[field]
        if kwargs.get('latitude') is not None:
            partner_vals['partner_latitude'] = kwargs['latitude']
        if kwargs.get('longitude') is not None:
            partner_vals['partner_longitude'] = kwargs['longitude']
        if kwargs.get('state'):
            st = request.env['res.country.state'].sudo().search(
                [('name', 'ilike', kwargs['state'])], limit=1
            )
            if st:
                partner_vals['state_id'] = st.id
        if kwargs.get('country'):
            co = request.env['res.country'].sudo().search(
                [('name', 'ilike', kwargs['country'])], limit=1
            )
            if co:
                partner_vals['country_id'] = co.id
        if partner_vals:
            user.partner_id.sudo().write(partner_vals)

        token = self._issue_token(user)
        return {
            "status": True,
            "message": "User created successfully",
            "data": {
                "user_id": user.id,
                "name": user.name,
                "email": user.login,
                "token": token,
                "is_rider": False,
                "is_admin": False,
            }
        }

    # ==========================================
    # PROFILE
    # ==========================================

    @http.route('/api/v1/profile', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def profile(self, **kwargs):
        """Get or update the current user's profile."""
        user, error = self._authenticate()
        if error:
            return error

        partner = user.partner_id

        partner_vals = {}
        for field in ('name', 'phone', 'street', 'street2', 'city', 'zip'):
            if kwargs.get(field):
                partner_vals[field] = kwargs[field]
        if kwargs.get('latitude') is not None:
            partner_vals['partner_latitude'] = kwargs['latitude']
        if kwargs.get('longitude') is not None:
            partner_vals['partner_longitude'] = kwargs['longitude']
        if partner_vals:
            partner.sudo().write(partner_vals)

        return {
            "status": True,
            "data": {
                "user_id": user.id,
                "name": user.name,
                "email": user.login,
                "phone": partner.phone or '',
                "street": partner.street or '',
                "street2": partner.street2 or '',
                "city": partner.city or '',
                "zip": partner.zip or '',
                "state": partner.state_id.name if partner.state_id else '',
                "country": partner.country_id.name if partner.country_id else '',
                "latitude": partner.partner_latitude,
                "longitude": partner.partner_longitude,
            }
        }

    # ==========================================
    # PUSH NOTIFICATION TOKEN
    # ==========================================

    @http.route('/api/v1/push/register', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def push_register(self, **kwargs):
        """Store the device FCM token for push notifications."""
        user, error = self._authenticate()
        if error:
            return error

        fcm_token = kwargs.get('fcm_token')
        if not fcm_token:
            return {"status": False, "message": "Missing fcm_token"}

        user.sudo().write({'push_token': fcm_token})
        return {"status": True, "message": "Push token registered"}

    # ==========================================
    # SERVICE CATALOG
    # ==========================================

    @http.route('/api/v1/services', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def get_services(self, **kwargs):
        """Return the full service type catalog with prices."""
        user, error = self._authenticate()
        if error:
            return error

        services = request.env['service.type'].with_user(user).search([])
        return {
            "status": True,
            "data": [
                {
                    "id": s.id,
                    "name": s.name,
                    "price": s.amount,
                }
                for s in services
            ]
        }

    # ==========================================
    # ORDERS — CUSTOMER
    # ==========================================

    @http.route('/api/v1/orders', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def get_orders(self, **kwargs):
        user, error = self._authenticate()
        if error:
            return error

        domain = [] if self._is_admin(user) else [('partner_id', '=', user.partner_id.id)]
        orders = request.env['laundry.order'].with_user(user).search(domain)
        return {"status": True, "data": [self._format_order(o) for o in orders]}

    @http.route('/api/v1/order/details', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def get_order_details(self, **kwargs):
        user, error = self._authenticate()
        if error:
            return error

        order_id = kwargs.get('order_id')
        if not order_id:
            return {"status": False, "message": "Missing order_id"}

        order = request.env['laundry.order'].with_user(user).browse(order_id)
        if not order.exists():
            return {"status": False, "message": "Order not found"}
        if not self._is_admin(user) and order.partner_id != user.partner_id:
            return {"status": False, "message": "Access denied"}

        # "data" key — consistent with all other endpoints
        return {"status": True, "data": self._format_order(order, include_lines=True)}

    @http.route('/api/v1/order/create', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def create_order(self, **kwargs):
        """
        Create a laundry order from the mobile app.

        Body:
          lines: [{service_type_id, qty, description (optional)}]  — required
          note: str — optional
          payment_method: cod | online | wallet — default cod
        """
        user, error = self._authenticate()
        if error:
            return error

        lines_data = kwargs.get('lines')
        if not lines_data or not isinstance(lines_data, list):
            return {"status": False, "message": "Missing or invalid 'lines' (must be a list)"}

        payment_method = kwargs.get('payment_method', 'cod')
        if payment_method not in VALID_PAYMENT_METHODS:
            return {"status": False, "message": f"Invalid payment_method. Allowed: {VALID_PAYMENT_METHODS}"}

        line_vals = []
        for item in lines_data:
            stype_id = item.get('service_type_id')
            qty = item.get('qty')
            if not stype_id or not qty:
                return {"status": False, "message": "Each line needs service_type_id and qty"}
            stype = request.env['service.type'].sudo().browse(int(stype_id))
            if not stype.exists():
                return {"status": False, "message": f"service_type_id {stype_id} not found"}
            line_vals.append((0, 0, {
                'service_type_id': stype.id,
                'qty': int(qty),
                'description': item.get('description', ''),
            }))

        # Admin user as operator — customer is not the laundry person
        admin_user = request.env.ref('base.user_admin')
        order = request.env['laundry.order'].with_user(user).create({
            'partner_id': user.partner_id.id,
            'laundry_person_id': admin_user.id,
            'payment_method': payment_method,
            'note': kwargs.get('note', ''),
            'order_line_ids': line_vals,
        })

        return {
            "status": True,
            "message": "Order created successfully",
            "data": self._format_order(order, include_lines=True),
        }

    @http.route('/api/v1/order/cancel', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def cancel_order(self, **kwargs):
        user, error = self._authenticate()
        if error:
            return error

        order_id = kwargs.get('order_id')
        if not order_id:
            return {"status": False, "message": "Missing order_id"}

        order = request.env['laundry.order'].with_user(user).browse(order_id)
        if not order.exists():
            return {"status": False, "message": "Order not found"}
        if not self._is_admin(user) and order.partner_id != user.partner_id:
            return {"status": False, "message": "Access denied"}
        if order.state not in ('draft',):
            return {"status": False, "message": f"Cannot cancel an order in state '{order.state}'"}

        order.action_cancel_order()
        return {
            "status": True,
            "message": "Order cancelled",
            "data": self._format_order(order),
        }

    @http.route('/api/v1/order/update_status', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def update_order_status(self, **kwargs):
        user, error = self._authenticate()
        if error:
            return error

        order_id = kwargs.get('order_id')
        new_state = kwargs.get('state')

        if not order_id or not new_state:
            return {"status": False, "message": "Missing parameters"}
        if new_state not in VALID_ORDER_STATES:
            return {"status": False, "message": f"Invalid state. Allowed: {VALID_ORDER_STATES}"}

        order = request.env['laundry.order'].with_user(user).browse(order_id)
        if not order.exists():
            return {"status": False, "message": "Order not found"}
        if not self._is_admin(user) and order.partner_id != user.partner_id:
            return {"status": False, "message": "Access denied"}

        order.write({"state": new_state})
        return {
            "status": True,
            "message": "Order updated successfully",
            "data": self._format_order(order),
        }

    # ==========================================
    # PICKUP REQUESTS — CUSTOMER
    # ==========================================

    @http.route('/api/v1/pickup/list', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def list_pickups(self, **kwargs):
        user, error = self._authenticate()
        if error:
            return error

        domain = [] if self._is_admin(user) else [('partner_id', '=', user.partner_id.id)]
        pickups = request.env['laundry.pickup.request'].with_user(user).search(domain)
        return {"status": True, "data": [self._format_pickup(p) for p in pickups]}

    @http.route('/api/v1/pickup/details', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def get_pickup_details(self, **kwargs):
        user, error = self._authenticate()
        if error:
            return error

        pickup_id = kwargs.get('pickup_id')
        if not pickup_id:
            return {"status": False, "message": "Missing pickup_id"}

        pr = request.env['laundry.pickup.request'].with_user(user).browse(pickup_id)
        if not pr.exists():
            return {"status": False, "message": "Pickup request not found"}
        if not self._is_admin(user) and pr.partner_id != user.partner_id:
            return {"status": False, "message": "Access denied"}

        return {"status": True, "data": self._format_pickup(pr, include_lines=True)}

    @http.route('/api/v1/serviceable', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def check_serviceable(self, **kwargs):
        """
        Check if a pin code (or city) is in our service area.

        Body:
          zip: str    — pin code to check (preferred)
          city: str   — city name fallback if zip not provided
        """
        zip_code = kwargs.get('zip', '')
        city = kwargs.get('city', '')

        Zone = request.env['laundry.service.zone'].sudo()
        serviceable = Zone.is_serviceable(zip_code, city)

        zone = Zone.find_zone_for_zip(zip_code) if zip_code else False
        return {
            "status": True,
            "data": {
                "serviceable": serviceable,
                "zip": zip_code,
                "zone": zone.name if zone else None,
                "city": zone.city if zone else None,
                "message": (
                    f"We serve your area ({zone.name})." if serviceable
                    else "Sorry, we don't serve your area yet. We currently operate in Rajkot city."
                ),
            }
        }

    @http.route('/api/v1/zones', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def list_zones(self, **kwargs):
        """Return list of active service zones (so app can show coverage info)."""
        zones = request.env['laundry.service.zone'].sudo().search([('active', '=', True)])
        return {
            "status": True,
            "data": [
                {
                    "id": z.id,
                    "name": z.name,
                    "city": z.city,
                    "zip_codes": [
                        code.strip()
                        for code in re.split(r'[,\n\r]+', z.zip_codes or '')
                        if code.strip()
                    ],
                }
                for z in zones
            ]
        }

    @http.route('/api/v1/pickup/create', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def create_pickup(self, **kwargs):
        """
        Schedule a pickup request from the mobile app.

        Body:
          schedule_date: '2026-07-10 10:00:00'  — required (UTC)
          lines: [{service_type_id, qty}]         — required
          payment_method: cod | online | wallet   — default cod
        """
        user, error = self._authenticate()
        if error:
            return error

        schedule_date = kwargs.get('schedule_date')
        lines_data = kwargs.get('lines')

        if not schedule_date:
            return {"status": False, "message": "Missing schedule_date"}
        if not lines_data or not isinstance(lines_data, list):
            return {"status": False, "message": "Missing or invalid 'lines' (must be a list)"}

        # ── Serviceability check ──────────────────────────────────────────
        partner = user.partner_id
        Zone = request.env['laundry.service.zone'].sudo()
        if not Zone.is_serviceable(partner.zip, partner.city):
            return {
                "status": False,
                "message": (
                    "Sorry, we don't serve your area yet. "
                    "We currently operate within Rajkot city. "
                    "Please update your address or contact us."
                ),
            }

        payment_method = kwargs.get('payment_method', 'cod')
        if payment_method not in VALID_PAYMENT_METHODS:
            return {"status": False, "message": f"Invalid payment_method. Allowed: {VALID_PAYMENT_METHODS}"}

        line_vals = []
        for item in lines_data:
            stype_id = item.get('service_type_id')
            qty = item.get('qty')
            if not stype_id or not qty:
                return {"status": False, "message": "Each line needs service_type_id and qty"}
            stype = request.env['service.type'].sudo().browse(int(stype_id))
            if not stype.exists():
                return {"status": False, "message": f"service_type_id {stype_id} not found"}
            line_vals.append((0, 0, {
                'service_type_id': stype.id,
                'qty': int(qty),
            }))

        pr = request.env['laundry.pickup.request'].with_user(user).create({
            'partner_id': user.partner_id.id,
            'schedule_date': schedule_date,
            'payment_method': payment_method,
            'line_ids': line_vals,
        })

        return {
            "status": True,
            "message": "Pickup request created successfully",
            "data": self._format_pickup(pr, include_lines=True),
        }

    # ==========================================
    # DASHBOARD (admin only)
    # ==========================================

    @http.route('/api/v1/dashboard', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def dashboard(self, **kwargs):
        """Return KPI summary for the admin dashboard (uses Odoo ORM directly)."""
        user, error = self._authenticate()
        if error:
            return error
        if not self._is_admin(user):
            return {"status": False, "message": "Access denied: Admin only"}

        Order = request.env['laundry.order'].with_user(user)
        Pickup = request.env['laundry.pickup.request'].with_user(user)

        today = fields.Date.today()
        month_start = today.replace(day=1)

        invoiced = Order.search([('state', '=', 'invoiced'), ('order_date', '>=', month_start)])
        revenue_this_month = sum(invoiced.mapped('total_amount'))

        # Per-rider stats
        rider_group = request.env.ref('laundry_management.group_laundry_rider')
        riders = request.env['res.users'].sudo().search(
            [('group_ids', 'in', [rider_group.id])]
        )
        rider_stats = []
        for rider in riders:
            rider_stats.append({
                'rider_id': rider.id,
                'name': rider.name,
                'delivered_total': Pickup.search_count(
                    [('laundry_person_id', '=', rider.id), ('state', '=', 'delivered')]
                ),
                'active_pickups': Pickup.search_count(
                    [('laundry_person_id', '=', rider.id), ('state', 'in', ('scheduled', 'picked'))]
                ),
            })

        # Ratings from our custom per-order field
        rated_orders = Order.search([('customer_rating', '>', 0)])
        avg_rating = (
            sum(rated_orders.mapped('customer_rating')) / len(rated_orders)
        ) if rated_orders else 0.0

        kpis = {
            'revenue_this_month': revenue_this_month,
            'draft_orders': Order.search_count([('state', '=', 'draft')]),
            'confirmed_orders': Order.search_count([('state', '=', 'order')]),
            'active_pickups': Pickup.search_count([('state', 'in', ('scheduled', 'picked'))]),
            'delivered_today': Pickup.search_count([
                ('state', '=', 'delivered'),
                ('pickup_date', '>=', fields.Datetime.today()),
            ]),
            'avg_rating': round(avg_rating, 2),
            'total_ratings': len(rated_orders),
            'rider_stats': rider_stats,
        }
        return {"status": True, "data": kpis}

    # ==========================================
    # PAYMENTS — CASHFREE
    # ==========================================

    @http.route('/api/v1/order/pay', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def initiate_payment(self, **kwargs):
        """
        Initiate a Cashfree payment for a laundry order.

        Returns payment_session_id and cashfree_order_id for the Flutter cashfree_pg SDK.

        Body:
          order_id: int  — laundry.order id to pay
        """
        user, error = self._authenticate()
        if error:
            return error

        order_id = kwargs.get('order_id')
        if not order_id:
            return {"status": False, "message": "Missing order_id"}

        order = request.env['laundry.order'].with_user(user).browse(int(order_id))
        if not order.exists():
            return {"status": False, "message": "Order not found"}
        if not self._is_admin(user) and order.partner_id != user.partner_id:
            return {"status": False, "message": "Access denied"}
        if order.state in ('invoiced', 'cancel'):
            return {"status": False, "message": f"Cannot pay an order in state '{order.state}'"}
        if order.total_amount <= 0:
            return {"status": False, "message": "Order has no amount to pay"}

        provider = request.env['payment.provider'].sudo().search(
            [('code', '=', 'cashfree'), ('state', 'in', ('test', 'enabled'))], limit=1
        )
        if not provider:
            return {"status": False, "message": "Cashfree payment provider not configured"}

        payment_method = request.env['payment.method'].sudo().search(
            [('code', 'in', ('upi', 'card', 'netbanking'))], limit=1
        )
        if not payment_method:
            return {"status": False, "message": "No payment method available"}

        try:
            reference = request.env['payment.transaction'].sudo()._compute_reference('cashfree')
            tx = request.env['payment.transaction'].sudo().create({
                'provider_id': provider.id,
                'payment_method_id': payment_method.id,
                'amount': order.total_amount,
                'currency_id': order.currency_id.id,
                'partner_id': order.partner_id.id,
                'reference': reference,
                'operation': 'online_direct',
            })
            order_data = tx._cashfree_create_payment_order()
            return {
                "status": True,
                "data": {
                    "payment_session_id": order_data.get('payment_session_id'),
                    "cashfree_order_id": order_data.get('order_id'),
                    "txn_env": "sandbox" if provider.state == 'test' else "production",
                    "amount": order.total_amount,
                    "currency": order.currency_id.name,
                    "laundry_order_id": order.id,
                    "transaction_reference": tx.reference,
                }
            }
        except Exception as e:
            return {"status": False, "message": str(e)}

    # ==========================================
    # PROMO CODES
    # ==========================================

    @http.route('/api/v1/promo/validate', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def validate_promo(self, **kwargs):
        """
        Validate a promo code and preview the discounted amount.

        Body:
          code: str         — required
          order_amount: float — required
        """
        user, error = self._authenticate()
        if error:
            return error

        code = kwargs.get('code')
        order_amount = kwargs.get('order_amount', 0)
        if not code:
            return {"status": False, "message": "Missing promo code"}

        try:
            promo = request.env['laundry.promo.code'].sudo().validate_and_get(
                code, float(order_amount)
            )
        except Exception as e:
            return {"status": False, "message": str(e)}

        discounted = promo.apply_discount(float(order_amount))
        return {
            "status": True,
            "data": {
                "code": promo.code,
                "discount_type": promo.discount_type,
                "discount_value": promo.discount_value,
                "original_amount": float(order_amount),
                "discounted_amount": discounted,
                "savings": float(order_amount) - discounted,
            }
        }

    # ==========================================
    # WALLET
    # ==========================================

    @http.route('/api/v1/wallet', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def wallet_info(self, **kwargs):
        """Get current wallet balance."""
        user, error = self._authenticate()
        if error:
            return error
        return {"status": True, "data": {"balance": user.wallet_balance}}

    @http.route('/api/v1/wallet/topup', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def wallet_topup(self, **kwargs):
        """
        Top up the wallet (admin only — in production this is called after payment confirmation).

        Body:
          user_id: int    — required (admin only)
          amount: float   — required
        """
        user, error = self._authenticate()
        if error:
            return error

        if not self._is_admin(user):
            return {"status": False, "message": "Access denied: Admin only"}

        target_id = kwargs.get('user_id')
        amount = kwargs.get('amount')
        if not target_id or not amount:
            return {"status": False, "message": "Missing user_id or amount"}

        target = request.env['res.users'].sudo().browse(int(target_id))
        if not target.exists():
            return {"status": False, "message": "User not found"}

        try:
            target.wallet_topup(float(amount))
        except Exception as e:
            return {"status": False, "message": str(e)}

        return {"status": True, "data": {"balance": target.wallet_balance}}

    # ==========================================
    # RATINGS
    # ==========================================

    @http.route('/api/v1/order/rate', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def rate_order(self, **kwargs):
        """
        Submit a rating for a completed order using Odoo's rating.mixin.

        Body:
          order_id: int     — required
          rating: int 1-5   — required
          review: str       — optional
        """
        user, error = self._authenticate()
        if error:
            return error

        order_id = kwargs.get('order_id')
        rating_val = kwargs.get('rating')
        if not order_id or not rating_val:
            return {"status": False, "message": "Missing order_id or rating"}

        try:
            rating_val = int(rating_val)
        except (TypeError, ValueError):
            return {"status": False, "message": "rating must be an integer 1-5"}

        if rating_val < 1 or rating_val > 5:
            return {"status": False, "message": "rating must be between 1 and 5"}

        order = request.env['laundry.order'].with_user(user).browse(int(order_id))
        if not order.exists():
            return {"status": False, "message": "Order not found"}
        if not self._is_admin(user) and order.partner_id != user.partner_id:
            return {"status": False, "message": "Access denied"}
        if order.state != 'invoiced':
            return {"status": False, "message": "Can only rate completed (invoiced) orders"}

        order.sudo().write({
            'customer_rating': float(rating_val),
            'customer_review': kwargs.get('review', ''),
        })
        return {
            "status": True,
            "message": "Rating submitted",
            "data": {
                "rating": rating_val,
                "review": kwargs.get('review', ''),
                "rating_avg": order.customer_rating,
                "rating_count": 1,
            }
        }

    @http.route('/api/v1/order/rating', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def get_order_rating(self, **kwargs):
        """Get rating stats for an order (via rating.mixin fields)."""
        user, error = self._authenticate()
        if error:
            return error

        order_id = kwargs.get('order_id')
        if not order_id:
            return {"status": False, "message": "Missing order_id"}

        order = request.env['laundry.order'].with_user(user).browse(int(order_id))
        if not order.exists():
            return {"status": False, "message": "Order not found"}

        return {
            "status": True,
            "data": {
                "rating_avg": order.customer_rating,
                "rating_count": 1 if order.customer_rating > 0 else 0,
                "rating_last": order.customer_rating,
                "review": order.customer_review or '',
            }
        }

    # ==========================================
    # PICKUP REQUESTS — RIDER
    # ==========================================

    @http.route('/api/v1/rider/pickups', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def rider_pickups(self, **kwargs):
        """Rider: list pickup requests assigned to them."""
        user, error = self._authenticate()
        if error:
            return error

        if not self._is_rider(user) and not self._is_admin(user):
            return {"status": False, "message": "Access denied: Rider role required"}

        domain = [('laundry_person_id', '=', user.id)] if not self._is_admin(user) else []

        state_filter = kwargs.get('state')
        if state_filter:
            domain.append(('state', '=', state_filter))

        pickups = request.env['laundry.pickup.request'].with_user(user).search(domain)
        return {"status": True, "data": [self._format_pickup(p, include_lines=True) for p in pickups]}

    # ==========================================
    # GARMENT TRACKING
    # ==========================================

    @http.route('/api/v1/garment/list', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def garment_list(self, **kwargs):
        """
        List garments for an order so the customer can track per-item status.

        Body:
          order_id: int  — required
        """
        user, error = self._authenticate()
        if error:
            return error

        order_id = kwargs.get('order_id')
        if not order_id:
            return {"status": False, "message": "Missing order_id"}

        order = request.env['laundry.order'].with_user(user).browse(int(order_id))
        if not order.exists():
            return {"status": False, "message": "Order not found"}
        if not self._is_admin(user) and order.partner_id != user.partner_id:
            return {"status": False, "message": "Access denied"}

        garments = request.env['laundry.garment'].with_user(user).search(
            [('order_id', '=', order.id)]
        )
        return {
            "status": True,
            "data": [
                {
                    "id": g.id,
                    "name": g.name,
                    "barcode": g.barcode,
                    "service_type": g.service_type_id.name if g.service_type_id else None,
                    "qty": g.qty,
                    "state": g.state,
                    "notes": g.notes or '',
                }
                for g in garments
            ]
        }

    @http.route('/api/v1/garment/scan', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def garment_scan(self, **kwargs):
        """
        Rider scans a garment barcode to advance its cleaning state.

        Body:
          barcode: str               — required
          state: cleaning|ready|delivered  — required
        """
        user, error = self._authenticate()
        if error:
            return error

        if not self._is_rider(user) and not self._is_admin(user):
            return {"status": False, "message": "Access denied: Rider role required"}

        barcode = kwargs.get('barcode')
        new_state = kwargs.get('state')

        if not barcode:
            return {"status": False, "message": "Missing barcode"}

        valid_scan_states = ['cleaning', 'ready', 'delivered']
        if new_state not in valid_scan_states:
            return {"status": False, "message": f"Invalid state. Allowed: {valid_scan_states}"}

        garment = request.env['laundry.garment'].sudo().search(
            [('barcode', '=', barcode)], limit=1
        )
        if not garment:
            return {"status": False, "message": f"Garment not found for barcode '{barcode}'"}

        state_transitions = {
            'received': ['cleaning'],
            'cleaning': ['ready'],
            'ready': ['delivered'],
        }
        allowed_next = state_transitions.get(garment.state, [])
        if new_state not in allowed_next:
            return {
                "status": False,
                "message": f"Cannot transition from '{garment.state}' to '{new_state}'. "
                           f"Next allowed: {allowed_next}",
            }

        action_map = {
            'cleaning': garment.action_cleaning,
            'ready': garment.action_ready,
            'delivered': garment.action_delivered,
        }
        action_map[new_state]()

        return {
            "status": True,
            "message": f"Garment updated to '{new_state}'",
            "data": {
                "id": garment.id,
                "barcode": garment.barcode,
                "name": garment.name,
                "state": garment.state,
                "order_id": garment.order_id.id,
            }
        }

    # ==========================================
    # PROMO CODE — APPLY
    # ==========================================

    @http.route('/api/v1/order/apply_promo', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def apply_promo(self, **kwargs):
        """
        Apply a validated promo code to an order and reduce its total.

        Body:
          order_id: int   — required
          code: str       — required
        """
        user, error = self._authenticate()
        if error:
            return error

        order_id = kwargs.get('order_id')
        code = kwargs.get('code')
        if not order_id or not code:
            return {"status": False, "message": "Missing order_id or code"}

        order = request.env['laundry.order'].with_user(user).browse(int(order_id))
        if not order.exists():
            return {"status": False, "message": "Order not found"}
        if not self._is_admin(user) and order.partner_id != user.partner_id:
            return {"status": False, "message": "Access denied"}
        if order.state != 'draft':
            return {"status": False, "message": "Promo codes can only be applied to draft orders"}
        if order.promo_id:
            return {"status": False, "message": "A promo code has already been applied"}

        try:
            discount_amount = order.sudo().action_apply_promo(str(code).strip().upper())
        except Exception as e:
            return {"status": False, "message": str(e)}

        return {
            "status": True,
            "message": "Promo code applied successfully",
            "data": {
                "promo_code": order.promo_id.code,
                "discount_amount": discount_amount,
                "total_amount": order.total_amount,
            }
        }

    # ==========================================
    # WALLET — PAY FOR ORDER
    # ==========================================

    @http.route('/api/v1/wallet/pay', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def wallet_pay(self, **kwargs):
        """
        Pay an order using the customer's wallet balance.

        Body:
          order_id: int  — required
        """
        user, error = self._authenticate()
        if error:
            return error

        order_id = kwargs.get('order_id')
        if not order_id:
            return {"status": False, "message": "Missing order_id"}

        order = request.env['laundry.order'].with_user(user).browse(int(order_id))
        if not order.exists():
            return {"status": False, "message": "Order not found"}
        if not self._is_admin(user) and order.partner_id != user.partner_id:
            return {"status": False, "message": "Access denied"}
        if order.state in ('invoiced', 'cancel'):
            return {"status": False, "message": f"Cannot pay an order in state '{order.state}'"}
        if order.total_amount <= 0:
            return {"status": False, "message": "Order has no amount to pay"}
        if user.wallet_balance < order.total_amount:
            return {
                "status": False,
                "message": f"Insufficient wallet balance. "
                           f"Available: {user.wallet_balance:.2f}, Required: {order.total_amount:.2f}",
            }

        try:
            order.sudo().action_wallet_pay()
        except Exception as e:
            return {"status": False, "message": str(e)}

        return {
            "status": True,
            "message": "Payment successful",
            "data": {
                "order_id": order.id,
                "order_name": order.name,
                "amount_paid": order.total_amount,
                "wallet_balance": user.wallet_balance,
            }
        }

    @http.route('/api/v1/rider/pickup/action', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def rider_pickup_action(self, **kwargs):
        """
        Rider: trigger a state transition on a pickup request.

        Body:
          pickup_id: int  — required
          action: schedule | pickup | deliver | cancel  — required
        """
        user, error = self._authenticate()
        if error:
            return error

        if not self._is_rider(user) and not self._is_admin(user):
            return {"status": False, "message": "Access denied: Rider role required"}

        pickup_id = kwargs.get('pickup_id')
        action = kwargs.get('action')

        if not pickup_id or not action:
            return {"status": False, "message": "Missing pickup_id or action"}
        if action not in VALID_RIDER_ACTIONS:
            return {"status": False, "message": f"Invalid action. Allowed: {VALID_RIDER_ACTIONS}"}

        pr = request.env['laundry.pickup.request'].with_user(user).browse(pickup_id)
        if not pr.exists():
            return {"status": False, "message": "Pickup request not found"}

        valid_actions_for_state = {
            'draft': ['schedule', 'cancel'],
            'scheduled': ['pickup', 'cancel'],
            'picked': ['deliver', 'cancel'],
        }
        allowed = valid_actions_for_state.get(pr.state, [])
        if action not in allowed:
            return {
                "status": False,
                "message": f"Action '{action}' not allowed in state '{pr.state}'. Allowed: {allowed}"
            }

        action_map = {
            'schedule': pr.action_schedule,
            'pickup': pr.action_pickup,
            'deliver': pr.action_deliver,
            'cancel': pr.action_cancel,
        }
        action_map[action]()

        return {
            "status": True,
            "message": f"Action '{action}' completed",
            "data": self._format_pickup(pr, include_lines=True),
        }
