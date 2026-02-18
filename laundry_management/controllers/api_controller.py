from odoo import http, fields
from odoo.http import request

class LaundryAPIController(http.Controller):

    # -----------------------------------------------------
    # LOGIN ENDPOINT (already working)
    # -----------------------------------------------------
    @http.route('/api/login', type='json', auth='none', methods=['POST'], csrf=False)
    def api_login(self, **kwargs):

        db = kwargs.get('db')
        username = kwargs.get('username')
        password = kwargs.get('password')

        if not db or not username or not password:
            return {"status": False, "error": "Missing credentials"}

        try:
            request.session.db = db

            credential = {
                "type": "password",
                "login": username,
                "password": password,
            }

            # THIS IS THE CORRECT CALL IN ODOO 19
            auth_info = request.session.authenticate(request.env, credential)

            if not auth_info or not auth_info.get("uid"):
                return {"status": False, "error": "Invalid credentials"}

            uid = auth_info["uid"]
            user = request.env['res.users'].sudo().browse(uid)
            print("UID:", request.session.uid)
            print("TOKEN:", request.session.session_token)
            return {
                "status": True,
                "uid": uid,
                "name": user.name,
                "session_id": request.session.sid,
            }

        except Exception as e:
            return {"status": False, "error": str(e)}

    # -----------------------------------------------------
    # 1️⃣ LIST LAUNDRY ORDERS
    # -----------------------------------------------------
    @http.route('/api/laundry/orders', type='json', auth='user', methods=['POST'], csrf=False)
    def get_orders(self, **kwargs):
        """
        List all laundry orders visible to the current user.
        Admin/Staff see all; Customers see their own.
        """
        user = request.env.user
        domain = []
        if not user.has_group('base.group_system'):
            domain = [('partner_id', '=', user.partner_id.id)]

        orders = request.env['laundry.order'].sudo().search(domain, order='create_date desc')

        data = [{
            "id": o.id,
            "name": o.name,
            "customer": o.partner_id.name,
            "status": o.state,
            "amount_total": o.total_amount,
            "date": o.create_date.strftime("%Y-%m-%d %H:%M:%S")
        } for o in orders]

        return {"status": True, "orders": data}

    # -----------------------------------------------------
    # 2️⃣ CREATE NEW ORDER
    # -----------------------------------------------------
    @http.route('/api/laundry/order/create', type='jsonrpc', auth='user', methods=['POST'], csrf=False)
    def create_order(self, **kwargs):
        """
        Create a new laundry order:
        {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "partner_id": 5,
                "service_ids": [2,3]
            }
        }
        """
        params = kwargs.get('params') if isinstance(kwargs.get('params'), dict) else kwargs
        partner_id = params.get('partner_id')
        service_ids = params.get('service_ids', [])

        if not partner_id:
            return {"status": False, "error": "partner_id is required"}

        try:
            order_vals = {
                "partner_id": partner_id,
                "service_ids": [(6, 0, service_ids)],
            }
            order = request.env["laundry.order"].sudo().create(order_vals)
            return {
                "status": True,
                "order": {
                    "id": order.id,
                    "name": order.name,
                    "state": order.state
                }
            }
        except Exception as e:
            return {"status": False, "error": str(e)}

    # -----------------------------------------------------
    # 3️⃣ UPDATE ORDER STATUS
    # -----------------------------------------------------
    @http.route('/api/laundry/order/update', type='jsonrpc', auth='user', methods=['POST'], csrf=False)
    def update_order(self, **kwargs):
        """
        Update order status:
        {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "order_id": 15,
                "state": "done"
            }
        }
        """
        params = kwargs.get('params') if isinstance(kwargs.get('params'), dict) else kwargs
        order_id = params.get("order_id")
        new_state = params.get("state")

        if not order_id or not new_state:
            return {"status": False, "error": "order_id and state are required"}

        order = request.env["laundry.order"].sudo().browse(order_id)
        if not order.exists():
            return {"status": False, "error": "Order not found"}

        try:
            order.write({"state": new_state})
            return {"status": True, "id": order.id, "state": order.state}
        except Exception as e:
            return {"status": False, "error": str(e)}

    # -----------------------------------------------------
    # 4️⃣ GET SINGLE ORDER DETAILS
    # -----------------------------------------------------
    @http.route('/api/laundry/order/details', type='json', auth='user', methods=['POST'], csrf=False)
    def get_order_detail(self, **kwargs):
        params = kwargs.get('params') if isinstance(kwargs.get('params'), dict) else kwargs
        order_id = params.get('order_id')
        
        if not order_id:
            return {"status": False, "error": "Order ID required"}

        order = request.env['laundry.order'].sudo().browse(int(order_id))
        if not order.exists():
            return {"status": False, "error": "Order not found"}

        return {
            "status": True,
            "order": {
                "id": order.id,
                "name": order.name,
                "customer": order.partner_id.name,
                "status": order.state,
                "amount_total": order.total_amount,
                "date": order.create_date.strftime("%Y-%m-%d %H:%M:%S"),
                "lines": [{
                    "product": line.product_id.name,
                    "quantity": line.qty,
                    "price_unit": line.price_unit,
                    "subtotal": line.amount,
                    "description": line.description or ""
                } for line in order.order_line_ids]
            }
        }

    # -----------------------------------------------------
    # 5️⃣ SIGNUP ENDPOINT
    # -----------------------------------------------------
    @http.route('/api/signup', type='json', auth='public', methods=['POST'], csrf=False)
    def signup(self, **kwargs):
        try:
            params = kwargs.get('params') if isinstance(kwargs.get('params'), dict) else kwargs
            
            name = params.get('name')
            email = params.get('login')
            password = params.get('password')
            mobile = params.get('mobile')
            
            if not all([name, email, password]):
                return {'error': 'Missing required fields (name, email, password)'}

            # Check if user exists
            User = http.request.env['res.users'].sudo()
            existing_user = User.search([('login', '=', email)], limit=1)
            if existing_user:
                return {'error': 'User with this email already exists'}

            # Prepare values for User creation (inherits Partner fields)
            portal_group_id = request.env.ref('base.group_portal').id
            
            values = {
                'name': name,
                'login': email,
                'password': password,
                'email': email,
                'group_ids': [(6, 0, [portal_group_id])], # Correct field name for Odoo 19
                
                # Partner Details (Delegated to res.partner)
                'phone': mobile,
                'street': params.get('street'),
                'street2': params.get('street2'),
                'city': params.get('city'),
                'zip': params.get('zip'),
            }

            # Handle State
            state_name = params.get('state')
            if state_name:
                state = request.env['res.country.state'].sudo().search([('name', '=ilike', state_name)], limit=1)
                if state:
                    values['state_id'] = state.id

            # Handle Country
            country_name = params.get('country')
            if country_name:
                country = request.env['res.country'].sudo().search([('name', '=ilike', country_name)], limit=1)
                if country:
                    values['country_id'] = country.id
            
            # Handle Coordinates
            latitude = params.get('latitude')
            longitude = params.get('longitude')
            if latitude and longitude:
                values.update({
                    'partner_latitude': float(latitude),
                    'partner_longitude': float(longitude),
                    'date_localization': fields.Date.today(),
                })

            # Create User (and Partner implicitly)
            new_user = User.create(values)

            # Authenticate to generate session
            credential = {
                "type": "password",
                "login": email,
                "password": password,
            }
            request.session.authenticate(request.env, credential)
            session_id = http.request.session.sid

            return {
                'status': 'success',
                'user_id': new_user.id,
                'session_id': session_id,
                'name': new_user.name,
                'email': new_user.login,
            }

        except Exception as e:
            return {'error': str(e)}
