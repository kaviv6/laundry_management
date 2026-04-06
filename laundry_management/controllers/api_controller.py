from odoo import http
from odoo.http import request
import secrets


class LaundryAPI(http.Controller):

    # --------------------------
    # 🔐 AUTH USING TOKEN
    # --------------------------
    def _authenticate(self):
        auth_header = request.httprequest.headers.get('Authorization')

        if not auth_header:
            return None, {"status": False, "message": "Token missing"}

        try:
            token = auth_header.replace("Bearer ", "").strip()
        except Exception:
            return None, {"status": False, "message": "Invalid token format"}

        user = request.env['res.users'].sudo().search([
            ('api_token', '=', token)
        ], limit=1)

        if not user:
            return None, {"status": False, "message": "Invalid token"}

        return user, None

    # --------------------------
    # 🔑 LOGIN
    # --------------------------
    @http.route('/api/v1/login', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def login(self, **kwargs):
        login = kwargs.get('login')
        password = kwargs.get('password')

        if not login or not password:
            return {"status": False, "message": "Missing credentials"}

        uid = request.session.authenticate(request.db, login, password)

        if not uid:
            return {"status": False, "message": "Invalid credentials"}

        user = request.env['res.users'].browse(uid)

        # Generate new token
        token = secrets.token_hex(32)
        user.sudo().write({'api_token': token})

        return {
            "status": True,
            "message": "Login successful",
            "data": {
                "user_id": user.id,
                "name": user.name,
                "token": token
            }
        }

    # --------------------------
    # 👤 SIGNUP
    # --------------------------
    @http.route('/api/v1/signup', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def signup(self, **kwargs):
        name = kwargs.get('name')
        login = kwargs.get('login')
        password = kwargs.get('password')

        if not all([name, login, password]):
            return {"status": False, "message": "Missing fields"}

        existing = request.env['res.users'].sudo().search([
            ('login', '=', login)
        ], limit=1)

        if existing:
            return {"status": False, "message": "User already exists"}

        user = request.env['res.users'].sudo().create({
            'name': name,
            'login': login,
            'password': password,
        })

        token = secrets.token_hex(32)
        user.sudo().write({'api_token': token})

        return {
            "status": True,
            "message": "User created",
            "data": {
                "user_id": user.id,
                "token": token
            }
        }

    # --------------------------
    # 📦 GET ORDERS
    # --------------------------
    @http.route('/api/v1/orders', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def get_orders(self, **kwargs):
        user, error = self._authenticate()
        if error:
            return error

        domain = []

        # Restrict customers to their own records
        if not user.has_group('base.group_system'):
            domain.append(('partner_id', '=', user.partner_id.id))

        orders = request.env['laundry.order'].with_user(user).search(domain)

        data = []
        for order in orders:
            data.append({
                "id": order.id,
                "name": order.name,
                "customer": order.partner_id.name,
                "state": order.state,
                "amount_total": order.amount_total,
            })

        return {
            "status": True,
            "data": data
        }

    # --------------------------
    # 🔄 UPDATE ORDER STATUS
    # --------------------------
    @http.route('/api/v1/order/update_status', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def update_order_status(self, **kwargs):
        user, error = self._authenticate()
        if error:
            return error

        order_id = kwargs.get('order_id')
        new_state = kwargs.get('state')

        allowed_states = ['draft', 'confirmed', 'done', 'cancel']

        if not order_id or not new_state:
            return {"status": False, "message": "Missing parameters"}

        if new_state not in allowed_states:
            return {"status": False, "message": "Invalid state"}

        order = request.env['laundry.order'].with_user(user).browse(order_id)

        if not order.exists():
            return {"status": False, "message": "Order not found"}

        order.write({"state": new_state})

        return {
            "status": True,
            "message": "Order updated successfully"
        }
