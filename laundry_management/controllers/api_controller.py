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
        Odoo's record rules automatically filter: Admin see all; Customers see their own.
        """
        # Rely on Odoo's native security rules instead of sudo() and hardcoded domains
        orders = request.env['laundry.order'].search([], order='create_date desc')

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
    @http.route('/api/laundry/order/create', type='json', auth='user', methods=['POST'], csrf=False)
    def create_order(self, **kwargs):
        """
        Create a new laundry order with lines.
        Expects: { lines: [{service_type_id: int, qty: int}, ...] }
        """
        params = kwargs.get('params') if isinstance(kwargs.get('params'), dict) else kwargs

        partner_id = params.get('partner_id')
        if not partner_id:
            partner_id = request.env.user.partner_id.id

        lines = params.get('lines', [])

        try:
            order_line_ids = []
            for line in lines:
                service_type_id = line.get('service_type_id')
                qty = line.get('qty', 1)
                if service_type_id:
                    order_line_ids.append((0, 0, {
                        'service_type_id': int(service_type_id),
                        'qty': int(qty),
                    }))

            order = request.env["laundry.order"].create({
                "partner_id": partner_id,
                "order_line_ids": order_line_ids,
            })
            return {
                "status": True,
                "order": {
                    "id": order.id,
                    "name": order.name,
                    "state": order.state,
                    "amount_total": order.total_amount,
                }
            }
        except Exception as e:
            return {"status": False, "error": str(e)}

    # -----------------------------------------------------
    # 3️⃣ UPDATE ORDER STATUS
    # -----------------------------------------------------
    @http.route('/api/laundry/order/update', type='json', auth='user', methods=['POST'], csrf=False)
    def update_order(self, **kwargs):
        """
        Update order status.
        """
        params = kwargs.get('params') if isinstance(kwargs.get('params'), dict) else kwargs
        order_id = params.get("order_id")
        new_state = params.get("state")

        if not order_id or not new_state:
            return {"status": False, "error": "order_id and state are required"}

        order = request.env["laundry.order"].search([('id', '=', order_id)], limit=1)
        if not order:
            return {"status": False, "error": "Order not found or access denied"}

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

        order = request.env['laundry.order'].search([('id', '=', int(order_id))], limit=1)
        if not order:
            return {"status": False, "error": "Order not found or access denied"}

        # Check for related invoices
        invoices = request.env['account.move'].sudo().search([
            ('invoice_origin', '=', order.name),
            ('move_type', '=', 'out_invoice'),
        ])
        invoice_data = [{
            'id': inv.id,
            'name': inv.name,
            'state': inv.state,
            'amount_total': inv.amount_total,
        } for inv in invoices]

        return {
            "status": True,
            "order": {
                "id": order.id,
                "name": order.name,
                "customer": order.partner_id.name,
                "status": order.state,
                "amount_total": order.total_amount,
                "date": order.create_date.strftime("%Y-%m-%d %H:%M:%S"),
                "invoices": invoice_data,
                "lines": [{
                    "product": line.product_id.name,
                    "quantity": line.qty,
                    "price_unit": line.price_unit,
                    "subtotal": line.amount,
                    "description": line.description or "",
                    "service_type": line.service_type_id.name or "",
                } for line in order.order_line_ids]
            }
        }

    # -----------------------------------------------------
    # 5️⃣ CLOSE ORDER (confirm draft → Laundry Order)
    # -----------------------------------------------------
    @http.route('/api/laundry/order/close', type='json', auth='user', methods=['POST'], csrf=False)
    def close_order(self, **kwargs):
        """Close/confirm a draft order. No sudo — User has write ACL, record rules apply."""
        params = kwargs.get('params') if isinstance(kwargs.get('params'), dict) else kwargs
        order_id = params.get('order_id')

        if not order_id:
            return {"status": False, "error": "Order ID required"}

        order = request.env['laundry.order'].search([('id', '=', int(order_id))], limit=1)
        if not order:
            return {"status": False, "error": "Order not found or access denied"}

        if order.state != 'draft':
            return {"status": False, "error": f"Cannot close order in '{order.state}' state. Must be 'draft'."}

        try:
            order.close_order()
            return {
                "status": True,
                "order": {"id": order.id, "name": order.name, "state": order.state}
            }
        except Exception as e:
            return {"status": False, "error": str(e)}

    # -----------------------------------------------------
    # 6️⃣ CREATE INVOICE for order
    # -----------------------------------------------------
    @http.route('/api/laundry/order/invoice', type='json', auth='user', methods=['POST'], csrf=False)
    def create_order_invoice(self, **kwargs):
        """Create and post invoice for a confirmed order. Uses sudo for accounting."""
        params = kwargs.get('params') if isinstance(kwargs.get('params'), dict) else kwargs
        order_id = params.get('order_id')

        if not order_id:
            return {"status": False, "error": "Order ID required"}

        # Search without sudo — record rules apply
        order = request.env['laundry.order'].search([('id', '=', int(order_id))], limit=1)
        if not order:
            return {"status": False, "error": "Order not found or access denied"}

        if order.state == 'invoiced':
            return {"status": False, "error": "Order already invoiced"}

        if order.state == 'draft':
            return {"status": False, "error": "Please close the order first before invoicing"}

        try:
            # Use sudo for accounting operations
            invoice = request.env['account.move'].sudo().create({
                'partner_id': order.partner_id.id,
                'move_type': 'out_invoice',
                'invoice_date': fields.Date.today(),
                'invoice_origin': order.name,
            })

            product = request.env.ref('laundry_management.product_product_laundry_service')
            for line in order.order_line_ids:
                request.env['account.move.line'].sudo().create({
                    'move_id': invoice.id,
                    'product_id': product.id,
                    'quantity': line.qty,
                    'price_unit': line.price_unit,
                })

            invoice.sudo().action_post()
            order.sudo().write({'state': 'invoiced'})

            return {
                "status": True,
                "invoice": {
                    "id": invoice.id,
                    "name": invoice.name,
                    "amount_total": invoice.amount_total,
                    "state": invoice.state,
                }
            }
        except Exception as e:
            return {"status": False, "error": str(e)}

    # -----------------------------------------------------
    # 7️⃣ LIST INVOICES
    # -----------------------------------------------------
    @http.route('/api/invoices', type='json', auth='user', methods=['POST'], csrf=False)
    def get_invoices(self, **kwargs):
        """List invoices linked to the current user's laundry orders."""
        # Get user's laundry order names
        orders = request.env['laundry.order'].search([])
        order_names = [o.name for o in orders if o.name]

        if not order_names:
            return {"status": True, "invoices": []}

        # Find invoices by origin (sudo for accounting access)
        invoices = request.env['account.move'].sudo().search([
            ('invoice_origin', 'in', order_names),
            ('move_type', '=', 'out_invoice'),
        ], order='invoice_date desc')

        data = [{
            "id": inv.id,
            "name": inv.name or "Draft",
            "date": inv.invoice_date.strftime("%Y-%m-%d") if inv.invoice_date else "",
            "customer": inv.partner_id.name,
            "amount_total": inv.amount_total,
            "amount_residual": inv.amount_residual,
            "state": inv.state,
            "payment_state": inv.payment_state,
            "origin": inv.invoice_origin or "",
        } for inv in invoices]

        return {"status": True, "invoices": data}

    # -----------------------------------------------------
    # 6️⃣ INVOICE DETAILS
    # -----------------------------------------------------
    @http.route('/api/invoice/details', type='json', auth='user', methods=['POST'], csrf=False)
    def get_invoice_detail(self, **kwargs):
        """Get single invoice details with lines."""
        params = kwargs.get('params') if isinstance(kwargs.get('params'), dict) else kwargs
        invoice_id = params.get('invoice_id')

        if not invoice_id:
            return {"status": False, "error": "Invoice ID required"}

        invoice = request.env['account.move'].sudo().browse(int(invoice_id))
        if not invoice.exists():
            return {"status": False, "error": "Invoice not found"}

        # Verify the invoice belongs to this user's orders
        orders = request.env['laundry.order'].search([])
        order_names = [o.name for o in orders if o.name]
        if invoice.invoice_origin not in order_names:
            return {"status": False, "error": "Invoice not found or access denied"}

        return {
            "status": True,
            "invoice": {
                "id": invoice.id,
                "name": invoice.name or "Draft",
                "date": invoice.invoice_date.strftime("%Y-%m-%d") if invoice.invoice_date else "",
                "due_date": invoice.invoice_date_due.strftime("%Y-%m-%d") if invoice.invoice_date_due else "",
                "customer": invoice.partner_id.name,
                "amount_total": invoice.amount_total,
                "amount_residual": invoice.amount_residual,
                "amount_paid": invoice.amount_total - invoice.amount_residual,
                "state": invoice.state,
                "payment_state": invoice.payment_state,
                "origin": invoice.invoice_origin or "",
                "lines": [{
                    "product": line.product_id.name or "",
                    "description": line.name or "",
                    "quantity": line.quantity,
                    "price_unit": line.price_unit,
                    "subtotal": line.price_subtotal,
                } for line in invoice.invoice_line_ids.filtered(lambda l: l.display_type == 'product')]
            }
        }

    # -----------------------------------------------------
    # 7️⃣ SERVICE TYPES
    # -----------------------------------------------------
    @http.route('/api/service-types', type='json', auth='user', methods=['POST'], csrf=False)
    def get_service_types(self, **kwargs):
        """List all available service types for order/pickup create forms."""
        services = request.env['service.type'].search([])
        data = [{
            "id": s.id,
            "name": s.name,
            "amount": s.amount,
        } for s in services]
        return {"status": True, "service_types": data}

    # -----------------------------------------------------
    # 8️⃣ CREATE PICKUP REQUEST
    # -----------------------------------------------------
    @http.route('/api/laundry/pickup/create', type='json', auth='user', methods=['POST'], csrf=False)
    def create_pickup_request(self, **kwargs):
        """
        Create a new pickup request with lines.
        Expects: { schedule_date: str, lines: [{service_type_id: int, qty: int}, ...] }
        """
        params = kwargs.get('params') if isinstance(kwargs.get('params'), dict) else kwargs

        schedule_date = params.get('schedule_date')
        lines = params.get('lines', [])

        if not lines:
            return {"status": False, "error": "At least one service line is required"}

        try:
            line_ids = []
            for line in lines:
                service_type_id = line.get('service_type_id')
                qty = line.get('qty', 1)
                if service_type_id:
                    line_ids.append((0, 0, {
                        'service_type_id': int(service_type_id),
                        'qty': int(qty),
                    }))

            vals = {
                'partner_id': request.env.user.partner_id.id,
                'line_ids': line_ids,
            }
            if schedule_date:
                vals['schedule_date'] = schedule_date

            pickup = request.env['laundry.pickup.request'].create(vals)
            return {
                "status": True,
                "pickup": {
                    "id": pickup.id,
                    "name": pickup.name,
                    "state": pickup.state,
                    "total_amount": pickup.total_amount,
                }
            }
        except Exception as e:
            return {"status": False, "error": str(e)}

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
            laundry_user_group_id = request.env.ref('laundry_management.group_laundry_user').id
            
            values = {
                'name': name,
                'login': email,
                'password': password,
                'email': email,
                'group_ids': [(6, 0, [laundry_user_group_id])],  # Internal user with Laundry User group
                
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
