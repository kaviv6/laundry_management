from odoo import http
from odoo.http import request


class LaundryAPI(http.Controller):

    # --------------------------
    # 🔐 AUTH USING ODOO API KEY
    # --------------------------
    def _authenticate(self):
        auth_header = request.httprequest.headers.get('Authorization')

        if not auth_header:
            return None, {"status": False, "message": "Missing Authorization header"}

        try:
            # Expected format: "Basic login:api_key"
            auth_type, credentials = auth_header.split(' ')
            login, api_key = credentials.split(':')
        except Exception:
            return None, {"status": False, "message": "Invalid Authorization format"}

        uid = request.session.authenticate(request.db, login, api_key)

        if not uid:
            return None, {"status": False, "message": "Invalid credentials"}

        user = request.env['res.users'].browse(uid)
        return user, None

    # --------------------------
    # 📦 GET ORDERS
    # --------------------------
    @http.route('/api/v1/orders', type='json', auth='none', methods=['GET'], csrf=False)
    def get_orders(self, **kwargs):
        user, error = self._authenticate()
        if error:
            return error

        orders = request.env['laundry.order'].with_user(user).search([])

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
    @http.route('/api/v1/order/update_status', type='json', auth='none', methods=['POST'], csrf=False)
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
