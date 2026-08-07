import json
import re
import secrets
from datetime import timedelta

from odoo import api, http, fields, SUPERUSER_ID
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

    @staticmethod
    def _format_address(partner, primary_partner):
        """Format a res.partner (the customer's own record, or one of its
        `type='delivery'` child contacts) as a saved address for the app.
        `primary_partner` is the customer's own partner — used to flag
        whether this address is the one that can't be deleted.
        """
        return {
            "id": partner.id,
            "is_primary": partner.id == primary_partner.id,
            "is_default": partner.laundry_is_default_address,
            "label": partner.laundry_address_label or (
                'Default' if partner.id == primary_partner.id else partner.name
            ),
            "street": partner.street or '',
            "street2": partner.street2 or '',
            "city": partner.city or '',
            "zip": partner.zip or '',
            "state": partner.state_id.name if partner.state_id else '',
            "country": partner.country_id.name if partner.country_id else '',
            "latitude": partner.partner_latitude,
            "longitude": partner.partner_longitude,
        }

    @staticmethod
    def _resolve_state_country(kwargs):
        """Resolve `state`/`country` name strings from the request into
        `state_id`/`country_id` vals — same ilike lookup used by signup()."""
        vals = {}
        if kwargs.get('state'):
            st = request.env['res.country.state'].sudo().search(
                [('name', 'ilike', kwargs['state'])], limit=1
            )
            if st:
                vals['state_id'] = st.id
        if kwargs.get('country'):
            co = request.env['res.country'].sudo().search(
                [('name', 'ilike', kwargs['country'])], limit=1
            )
            if co:
                vals['country_id'] = co.id
        return vals

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
            "amount_paid": order.amount_paid,
            "amount_due": order.amount_due,
            "payment_status": order.payment_status,
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
            "amount_due": pr.order_id.amount_due if pr.order_id else pr.total_amount,
            "payment_status": pr.order_id.payment_status if pr.order_id else 'not_paid',
            "address": {
                "street": pr.street or '',
                "street2": pr.street2 or '',
                "city": pr.city or '',
                "zip": pr.zip or '',
                "state": pr.state_id.name if pr.state_id else '',
                "country": pr.country_id.name if pr.country_id else '',
                "latitude": pr.partner_id.partner_latitude or None,
                "longitude": pr.partner_id.partner_longitude or None,
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

    def _format_contract_request(self, req):
        return {
            "id": req.id,
            "name": req.name,
            "business_name": req.business_name or '',
            "contact_name": req.contact_name or '',
            "email": req.email_from or '',
            "phone": req.phone or '',
            "business_type": req.company_type or 'other',
            "notes": req.description or '',
            "state": req.state,
            "date": self._fmt_dt(req.create_date),
        }

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

        env = api.Environment(request.env.cr, SUPERUSER_ID, {'no_reset_password': True})
        company = env['res.company'].search(
            [('active', '=', True)], order='id asc', limit=1
        )
        if not company:
            return {"status": False, "message": "System error: no company configured"}
        user = env['res.users'].create({
            'name': name,
            'login': login,
            'password': password,
            'company_id': company.id,
            'company_ids': [(4, company.id)],
        })

        laundry_group = env.ref('laundry_management.group_laundry_user')
        user.write({'group_ids': [(4, laundry_group.id)]})

        partner_vals = {}
        for field in ('phone', 'street', 'street2', 'city', 'zip'):
            if kwargs.get(field):
                partner_vals[field] = kwargs[field]
        if kwargs.get('latitude') is not None:
            partner_vals['partner_latitude'] = kwargs['latitude']
        if kwargs.get('longitude') is not None:
            partner_vals['partner_longitude'] = kwargs['longitude']
        if kwargs.get('state'):
            st = env['res.country.state'].search(
                [('name', 'ilike', kwargs['state'])], limit=1
            )
            if st:
                partner_vals['state_id'] = st.id
        if kwargs.get('country'):
            co = env['res.country'].search(
                [('name', 'ilike', kwargs['country'])], limit=1
            )
            if co:
                partner_vals['country_id'] = co.id
        if partner_vals:
            user.partner_id.write(partner_vals)

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
    # ADDRESS BOOK
    # ==========================================
    #
    # The customer's own res.partner record (user.partner_id) is always
    # address #1 — the first address a customer ever saves is written
    # directly onto it (matching every other endpoint that already reads
    # the customer's address straight off their partner, e.g.
    # laundry.pickup.request's related address fields and
    # action_open_map()'s use of partner_latitude/partner_longitude).
    # Every additional address becomes a `type='delivery'` child contact
    # (parent_id=partner.id) — Odoo's native multi-address pattern, visible
    # in Contacts as sub-addresses of the customer.
    #
    # Every create/update that touches street/city/zip/state/country calls
    # the customer's geo_localize() (from base_geolocalize) so
    # partner_latitude/partner_longitude are always kept in sync — that's
    # what the rider's "Navigate with Google Maps" action already reads.

    @staticmethod
    def _set_default_address(partner, target):
        """Ensure exactly one of partner + its delivery children is flagged default."""
        addresses = partner | request.env['res.partner'].sudo().search([
            ('parent_id', '=', partner.id), ('type', '=', 'delivery'),
        ])
        (addresses - target).sudo().write({'laundry_is_default_address': False})
        target.sudo().write({'laundry_is_default_address': True})

    @http.route('/api/v1/address/list', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def address_list(self, **kwargs):
        """List the customer's saved addresses — their own partner record
        (if its address has been filled in) plus any delivery child contacts."""
        user, error = self._authenticate()
        if error:
            return error

        partner = user.partner_id
        children = request.env['res.partner'].sudo().search([
            ('parent_id', '=', partner.id), ('type', '=', 'delivery'),
        ])
        data = []
        if partner.street:
            data.append(self._format_address(partner, partner))
        data += [self._format_address(c, partner) for c in children]
        return {"status": True, "data": data}

    @http.route('/api/v1/address/create', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def address_create(self, **kwargs):
        """
        Save a new address.

        Body:
          street: str            — required
          street2, city, zip: str — optional
          state, country: str     — optional, resolved by name
          label: str              — optional, e.g. "Home", "Office"
          set_default: bool       — optional
          latitude, longitude: float — optional. Pass these when the app
            obtained them directly from GPS or the map picker (via
            /api/v1/geocode/reverse) — they're trusted as-is and skip the
            forward-geocode, since a direct fix is more accurate than
            re-deriving coordinates from the typed address text.
        """
        user, error = self._authenticate()
        if error:
            return error

        street = kwargs.get('street')
        if not street:
            return {"status": False, "message": "Missing street"}

        partner = user.partner_id
        address_vals = {}
        for field in ('street', 'street2', 'city', 'zip'):
            if kwargs.get(field) is not None:
                address_vals[field] = kwargs[field]
        address_vals.update(self._resolve_state_country(kwargs))
        if kwargs.get('label'):
            address_vals['laundry_address_label'] = kwargs['label']

        has_coords = kwargs.get('latitude') is not None and kwargs.get('longitude') is not None
        if has_coords:
            # Must be written in the same call as the address fields — see
            # base_geolocalize's res.partner.write() override, which resets
            # partner_latitude/longitude to 0.0 whenever street/city/etc.
            # change unless both are included in that same write.
            address_vals['partner_latitude'] = float(kwargs['latitude'])
            address_vals['partner_longitude'] = float(kwargs['longitude'])

        if not partner.street:
            # First address this customer has ever saved — becomes their
            # own partner record, exactly what every other part of the
            # module already reads as "the customer's address".
            target = partner
            target.sudo().write(address_vals)
        else:
            target = request.env['res.partner'].sudo().create({
                **address_vals,
                'name': kwargs.get('label') or f'{partner.name} — Address',
                'parent_id': partner.id,
                'type': 'delivery',
                'company_type': 'person',
            })

        if not has_coords:
            target.sudo().geo_localize()

        has_default = partner.laundry_is_default_address or bool(
            request.env['res.partner'].sudo().search_count([
                ('parent_id', '=', partner.id), ('type', '=', 'delivery'),
                ('laundry_is_default_address', '=', True),
            ])
        )
        if kwargs.get('set_default') or not has_default:
            self._set_default_address(partner, target)

        return {
            "status": True,
            "message": "Address saved",
            "data": self._format_address(target, partner),
        }

    @http.route('/api/v1/address/update', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def address_update(self, **kwargs):
        """
        Update a saved address (the primary partner or one of its delivery
        children).

        Body:
          address_id: int          — required
          street, street2, city, zip, state, country, label: str — optional
          set_default: bool        — optional
          latitude, longitude: float — optional, see address/create — pass
            these when they came straight from GPS/the map picker to skip
            the forward-geocode and trust them as-is.
        """
        user, error = self._authenticate()
        if error:
            return error

        address_id = kwargs.get('address_id')
        if not address_id:
            return {"status": False, "message": "Missing address_id"}

        partner = user.partner_id
        target = request.env['res.partner'].sudo().browse(int(address_id))
        if not target.exists() or (target.id != partner.id and target.parent_id.id != partner.id):
            return {"status": False, "message": "Address not found"}

        address_vals = {}
        for field in ('street', 'street2', 'city', 'zip'):
            if kwargs.get(field) is not None:
                address_vals[field] = kwargs[field]
        address_vals.update(self._resolve_state_country(kwargs))
        if kwargs.get('label') is not None:
            address_vals['laundry_address_label'] = kwargs['label']

        has_coords = kwargs.get('latitude') is not None and kwargs.get('longitude') is not None
        if has_coords:
            address_vals['partner_latitude'] = float(kwargs['latitude'])
            address_vals['partner_longitude'] = float(kwargs['longitude'])

        if address_vals:
            target.sudo().write(address_vals)
            if not has_coords and any(f in address_vals for f in ('street', 'street2', 'city', 'zip', 'state_id', 'country_id')):
                target.sudo().geo_localize()

        if kwargs.get('set_default'):
            self._set_default_address(partner, target)

        return {
            "status": True,
            "message": "Address updated",
            "data": self._format_address(target, partner),
        }

    @http.route('/api/v1/address/delete', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def address_delete(self, **kwargs):
        """Delete a saved address. The primary address (the customer's own
        partner record) can never be deleted — only its delivery children."""
        user, error = self._authenticate()
        if error:
            return error

        address_id = kwargs.get('address_id')
        if not address_id:
            return {"status": False, "message": "Missing address_id"}

        partner = user.partner_id
        if int(address_id) == partner.id:
            return {"status": False, "message": "Cannot delete your primary address"}

        target = request.env['res.partner'].sudo().browse(int(address_id))
        if not target.exists() or target.parent_id.id != partner.id or target.type != 'delivery':
            return {"status": False, "message": "Address not found"}

        was_default = target.laundry_is_default_address
        target.sudo().unlink()

        if was_default:
            partner.sudo().write({'laundry_is_default_address': True})

        return {"status": True, "message": "Address deleted"}

    @http.route('/api/v1/address/set_default', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def address_set_default(self, **kwargs):
        """Mark one saved address as the default for new pickups."""
        user, error = self._authenticate()
        if error:
            return error

        address_id = kwargs.get('address_id')
        if not address_id:
            return {"status": False, "message": "Missing address_id"}

        partner = user.partner_id
        target = request.env['res.partner'].sudo().browse(int(address_id))
        if not target.exists() or (target.id != partner.id and target.parent_id.id != partner.id):
            return {"status": False, "message": "Address not found"}

        self._set_default_address(partner, target)
        return {"status": True, "data": self._format_address(target, partner)}

    @http.route('/api/v1/geocode/reverse', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def geocode_reverse(self, **kwargs):
        """
        Reverse-geocode a lat/lng pair into address fields — powers the
        app's "Use current location" button and its map picker's "Confirm
        location" step, via base_geolocalize's OpenStreetMap Nominatim call.

        Body:
          latitude, longitude: float — required

        The returned street/city/state/zip/country are best-effort — the
        app pre-fills the form with them but the customer can still edit
        before saving. The echoed latitude/longitude are exactly what was
        passed in, meant to be sent straight through to address/create or
        address/update so the saved coordinates match what the user picked.
        """
        user, error = self._authenticate()
        if error:
            return error

        latitude = kwargs.get('latitude')
        longitude = kwargs.get('longitude')
        if latitude is None or longitude is None:
            return {"status": False, "message": "Missing latitude or longitude"}

        try:
            latitude = float(latitude)
            longitude = float(longitude)
        except (TypeError, ValueError):
            return {"status": False, "message": "latitude/longitude must be numbers"}

        try:
            result = request.env['base.geocoder'].sudo()._call_openstreetmap_reverse(latitude, longitude)
        except Exception as e:
            return {"status": False, "message": str(e)}

        address = (result or {}).get('address') or {}
        if not address:
            return {"status": False, "message": "Could not resolve an address for this location"}

        street = ' '.join(p for p in (address.get('house_number'), address.get('road')) if p)
        city = (
            address.get('city') or address.get('town') or address.get('village')
            or address.get('suburb') or address.get('county') or ''
        )

        return {
            "status": True,
            "data": {
                "street": street or result.get('display_name', ''),
                "street2": address.get('suburb') or address.get('neighbourhood') or '',
                "city": city,
                "zip": address.get('postcode') or '',
                "state": address.get('state') or '',
                "country": address.get('country') or '',
                "latitude": latitude,
                "longitude": longitude,
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
        Initiate a Cashfree payment for a laundry order. Called either by the
        customer paying from their own Orders screen, or by the rider
        opening the checkout in person (e.g. handing the customer their
        phone to pay by UPI/card at the door) — the `method` field
        distinguishes the two so the payment counts toward the right place
        once the webhook confirms it.

        Returns payment_session_id and cashfree_order_id for the Flutter cashfree_pg SDK.

        Body:
          order_id: int  — laundry.order id to pay
          method: upi | card — required only when a rider (not the customer) is calling
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

        is_owner = order.partner_id == user.partner_id
        is_rider_for_order = self._is_rider(user) and (
            order.rider_id.id == user.id
            or any(pr.laundry_person_id.id == user.id for pr in order.pickup_request_ids)
        )
        if not self._is_admin(user) and not is_owner and not is_rider_for_order:
            return {"status": False, "message": "Access denied"}

        collect_method = None
        if is_rider_for_order and not is_owner:
            collect_method = kwargs.get('method')
            if collect_method not in ('upi', 'card'):
                return {"status": False, "message": "Missing/invalid method. Allowed: upi, card"}

        # An order being 'invoiced' (delivered COD-style) doesn't mean it's
        # been paid — only 'cancel' should actually block payment. Whether
        # there's anything left to pay is the payment_status/amount_due
        # check right below.
        if order.state == 'cancel':
            return {"status": False, "message": "Cannot pay a cancelled order"}
        if order.payment_status == 'paid' or order.amount_due <= 0:
            return {"status": False, "message": "This order is already fully paid"}

        provider = request.env['payment.provider'].sudo().search(
            [('code', '=', 'cashfree'), ('state', 'in', ('test', 'enabled'))], limit=1
        )
        if not provider:
            return {"status": False, "message": "Cashfree payment provider not configured"}
        # A provider can be flipped to Test/Enabled with the Client Id /
        # Client Secret fields still blank — that would otherwise surface as
        # a confusing raw Cashfree auth error deep inside
        # _cashfree_create_payment_order() instead of a clear message here.
        if not provider.cashfree_client_id or not provider.cashfree_client_secret:
            return {
                "status": False,
                "message": "Cashfree is enabled but its Client Id / Client Secret aren't set. "
                           "Add them under Accounting → Configuration → Payment Providers → CashFree.",
            }

        payment_method = request.env['payment.method'].sudo().search(
            [('code', 'in', ('upi', 'card', 'netbanking'))], limit=1
        )
        if not payment_method:
            return {"status": False, "message": "No payment method available"}

        try:
            reference = request.env['payment.transaction'].sudo()._compute_reference('cashfree')
            tx_vals = {
                'provider_id': provider.id,
                'payment_method_id': payment_method.id,
                'amount': order.amount_due,
                'currency_id': order.currency_id.id,
                'partner_id': order.partner_id.id,
                'reference': reference,
                'operation': 'online_direct',
                'laundry_order_id': order.id,
            }
            if collect_method:
                tx_vals['laundry_collected_by_id'] = user.id
                tx_vals['laundry_collect_method'] = collect_method
            # If the order's already invoiced (e.g. COD-delivered but not yet
            # paid), link the transaction to that invoice so account_payment's
            # own post-processing cron auto-creates AND reconciles the
            # account.payment against it — no manual reconciliation needed.
            invoice = request.env['account.move'].sudo().search(
                [('invoice_origin', '=', order.name), ('move_type', '=', 'out_invoice')], limit=1,
            )
            if invoice:
                tx_vals['invoice_ids'] = [(6, 0, [invoice.id])]
            tx = request.env['payment.transaction'].sudo().create(tx_vals)
            order_data = tx._cashfree_create_payment_order()
            return {
                "status": True,
                "data": {
                    "payment_session_id": order_data.get('payment_session_id'),
                    "cashfree_order_id": order_data.get('order_id'),
                    "txn_env": "sandbox" if provider.state == 'test' else "production",
                    "amount": order.amount_due,
                    "currency": order.currency_id.name,
                    "laundry_order_id": order.id,
                    "transaction_reference": tx.reference,
                }
            }
        except Exception as e:
            return {"status": False, "message": str(e)}

    @http.route('/api/v1/order/<int:order_id>/invoice/pdf', type='http', auth='none', methods=['GET'], csrf=False)
    def download_invoice_pdf(self, order_id, **kwargs):
        """
        Stream the order's tax invoice PDF — a plain `type='http'` route
        (not jsonrpc) since the response body is a binary file, not JSON.
        Auth still works the same way: pass `Authorization: Bearer <token>`
        as a header on the GET request (the app's HTTP client sets this,
        same as every other endpoint — a bare browser/webview open won't
        have it, so this is meant to be fetched in-app then saved/shared).
        """
        def _json_error(message, status):
            return request.make_response(
                json.dumps({"status": False, "message": message}),
                headers=[('Content-Type', 'application/json')],
                status=status,
            )

        user, error = self._authenticate()
        if error:
            return _json_error(error.get('message', 'Unauthorized'), 401)

        order = request.env['laundry.order'].with_user(user).browse(order_id)
        if not order.exists():
            return _json_error('Order not found', 404)
        if not self._is_admin(user) and order.partner_id != user.partner_id:
            return _json_error('Access denied', 403)

        invoice = request.env['account.move'].sudo().search(
            [('invoice_origin', '=', order.name), ('move_type', '=', 'out_invoice')], limit=1,
        )
        if not invoice:
            return _json_error('Invoice not generated yet', 404)

        # .with_user(user) — not plain .sudo() — the India-localization
        # invoice template calls self.env.user.has_group(...) internally,
        # which needs a real (singleton) uid, not just ACL bypass.
        pdf, _ = request.env['ir.actions.report'].with_user(user).sudo()._render_qweb_pdf(
            'account.account_invoices', invoice.id
        )
        filename = f"{invoice.name or order.name}.pdf".replace('/', '-')
        return request.make_response(
            pdf,
            headers=[
                ('Content-Type', 'application/pdf'),
                ('Content-Length', len(pdf)),
                ('Content-Disposition', f'attachment; filename="{filename}"'),
            ],
        )

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

    @http.route('/api/v1/rider/collect_payment', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def rider_collect_payment(self, **kwargs):
        """
        Rider: record a cash/UPI/card payment collected in person from the
        customer (typically at delivery). Goes through the same
        laundry.order._register_payment() funnel as online/wallet payments,
        so amount_due and payment_status stay correct everywhere — customer
        app, rider app, and Odoo — regardless of which channel paid.

        Body:
          pickup_id: int            — required
          amount: float             — required, > 0, <= the order's amount_due
          method: cash | upi | card — required
        """
        user, error = self._authenticate()
        if error:
            return error
        if not self._is_rider(user) and not self._is_admin(user):
            return {"status": False, "message": "Access denied: Rider role required"}

        pickup_id = kwargs.get('pickup_id')
        amount = kwargs.get('amount')
        method = kwargs.get('method')
        if not pickup_id or amount is None or not method:
            return {"status": False, "message": "Missing pickup_id, amount or method"}
        if method not in ('cash', 'upi', 'card'):
            return {"status": False, "message": "Invalid method. Allowed: cash, upi, card"}

        pr = request.env['laundry.pickup.request'].with_user(user).browse(int(pickup_id))
        if not pr.exists():
            return {"status": False, "message": "Pickup request not found"}
        if not self._is_admin(user) and pr.laundry_person_id.id != user.id:
            return {"status": False, "message": "Access denied: not your pickup"}
        if not pr.order_id:
            return {"status": False, "message": "This pickup has no order yet — mark it picked up first"}

        try:
            amount = float(amount)
        except (TypeError, ValueError):
            return {"status": False, "message": "Invalid amount"}
        if amount <= 0:
            return {"status": False, "message": "Amount must be greater than zero"}

        order = pr.order_id.with_user(user)
        if amount > order.amount_due + 0.01:
            return {"status": False, "message": f"Amount exceeds the remaining due (Rs.{order.amount_due:.2f})"}

        order.sudo()._register_payment(amount, method=method, source='rider_collected', collected_by=user)

        return {
            "status": True,
            "message": "Payment recorded",
            "data": self._format_order(order),
        }

    @http.route('/api/v1/rider/collection_summary', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def rider_collection_summary(self, **kwargs):
        """
        Rider: total collected in person (cash/UPI/card) over a period, for
        the "Collected" stat on the Today/History screens. Admin sees every
        rider's total; a rider sees only their own.

        Body:
          period: today | week  — optional, default 'today'
        """
        user, error = self._authenticate()
        if error:
            return error
        if not self._is_rider(user) and not self._is_admin(user):
            return {"status": False, "message": "Access denied: Rider role required"}

        period = kwargs.get('period') or 'today'
        now = fields.Datetime.now()
        if period == 'week':
            since = now - timedelta(days=7)
        else:
            since = now.replace(hour=0, minute=0, second=0, microsecond=0)

        domain = [
            ('source', '=', 'rider_collected'),
            ('create_date', '>=', since),
        ]
        if not self._is_admin(user):
            domain.append(('collected_by_id', '=', user.id))

        logs = request.env['laundry.payment.log'].sudo().search(domain)
        return {
            "status": True,
            "data": {
                "collected_amount": sum(logs.mapped('amount')),
                "collections_count": len(logs),
                "period": period,
            }
        }

    # ==========================================
    # ADMIN — RIDER ASSIGNMENT
    # ==========================================
    #
    # A pickup's `laundry_person_id` (labelled "Rider" on the model) is what
    # rider_pickups() above filters on — until an admin sets it, the pickup
    # is invisible to every rider's app and can never get picked up.

    @http.route('/api/v1/admin/riders', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def admin_list_riders(self, **kwargs):
        """Admin: list all riders, for the pickup assignment picker."""
        user, error = self._authenticate()
        if error:
            return error
        if not self._is_admin(user):
            return {"status": False, "message": "Access denied: Admin only"}

        rider_group = request.env.ref('laundry_management.group_laundry_rider')
        riders = request.env['res.users'].sudo().search([('group_ids', 'in', [rider_group.id])])
        Pickup = request.env['laundry.pickup.request'].sudo()
        return {
            "status": True,
            "data": [
                {
                    "id": r.id,
                    "name": r.name,
                    "active_pickups": Pickup.search_count([
                        ('laundry_person_id', '=', r.id), ('state', 'in', ('scheduled', 'picked')),
                    ]),
                }
                for r in riders
            ]
        }

    @http.route('/api/v1/admin/pickup/assign_rider', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def admin_assign_rider(self, **kwargs):
        """
        Admin: assign (or reassign) a rider to a pickup request. A pickup
        still in 'draft' automatically moves to 'scheduled' once assigned —
        matching what action_schedule() already does when a rider claims a
        pickup themselves — and notifies the customer + rider (see
        laundry.push.service's write() hooks).

        Body:
          pickup_id: int — required
          rider_id: int  — required
        """
        user, error = self._authenticate()
        if error:
            return error
        if not self._is_admin(user):
            return {"status": False, "message": "Access denied: Admin only"}

        pickup_id = kwargs.get('pickup_id')
        rider_id = kwargs.get('rider_id')
        if not pickup_id or not rider_id:
            return {"status": False, "message": "Missing pickup_id or rider_id"}

        # with_user(user), not sudo() — action_schedule() below posts a
        # chatter message via message_post(), which needs self.env.user to
        # resolve to a real (singleton) user. Plain sudo() keeps whatever
        # uid an auth='none' request started with (often none), so
        # self.env.user ends up empty and message_post() raises
        # "Expected singleton: res.users()". with_user(user) carries the
        # real authenticated admin through, same as rider_pickup_action().
        pr = request.env['laundry.pickup.request'].with_user(user).browse(int(pickup_id))
        if not pr.exists():
            return {"status": False, "message": "Pickup request not found"}
        if pr.state in ('delivered', 'cancel'):
            return {"status": False, "message": f"Cannot assign a rider to a pickup in state '{pr.state}'"}

        rider = request.env['res.users'].sudo().browse(int(rider_id))
        if not rider.exists() or not self._is_rider(rider):
            return {"status": False, "message": "Selected user is not a rider"}

        pr.write({'laundry_person_id': rider.id})
        if pr.state == 'draft':
            pr.action_schedule()

        return {
            "status": True,
            "message": "Rider assigned",
            "data": self._format_pickup(pr, include_lines=True),
        }

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
        if order.state == 'cancel':
            return {"status": False, "message": "Cannot pay a cancelled order"}
        if order.payment_status == 'paid' or order.amount_due <= 0:
            return {"status": False, "message": "This order is already fully paid"}
        if user.wallet_balance < order.amount_due:
            return {
                "status": False,
                "message": f"Insufficient wallet balance. "
                           f"Available: {user.wallet_balance:.2f}, Required: {order.amount_due:.2f}",
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
                "amount_paid": order.amount_paid,
                "amount_due": order.amount_due,
                "payment_status": order.payment_status,
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

    # ==========================================
    # CONTRACT REQUESTS (B2B)
    # ==========================================

    @http.route('/api/v1/contract-request/create', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def create_contract_request(self, **kwargs):
        """
        Customer: submit a B2B enquiry (hotel/restaurant/hostel volume
        pricing). Creates a `laundry.contract.request` linked to the
        customer's own partner_id, in 'submitted' state — an admin picks it
        up from there (see admin_contract_request_action below).

        Body:
          business_name: str   — required
          contact_person: str  — required
          business_type: str   — Hotel | Restaurant | Hostel | Other
          phone: str           — required
          notes: str           — optional
        """
        user, error = self._authenticate()
        if error:
            return error

        business_name = (kwargs.get('business_name') or '').strip()
        contact_person = (kwargs.get('contact_person') or '').strip()
        phone = (kwargs.get('phone') or '').strip()
        if not business_name or not contact_person or not phone:
            return {"status": False, "message": "Missing business_name, contact_person or phone"}

        business_type_map = {'hotel': 'hotel', 'restaurant': 'restaurant', 'hostel': 'hostel'}
        company_type = business_type_map.get((kwargs.get('business_type') or '').strip().lower(), 'other')

        req = request.env['laundry.contract.request'].sudo().create({
            'partner_id': user.partner_id.id,
            'business_name': business_name,
            'contact_name': contact_person,
            'email_from': user.partner_id.email or '',
            'phone': phone,
            'company_type': company_type,
            'description': kwargs.get('notes') or '',
        })
        req.action_submit_request()

        return {"status": True, "message": "Enquiry received", "data": self._format_contract_request(req)}

    @http.route('/api/v1/admin/contract-requests', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def admin_list_contract_requests(self, **kwargs):
        """Admin: list B2B contract requests. Optional `state` filter."""
        user, error = self._authenticate()
        if error:
            return error
        if not self._is_admin(user):
            return {"status": False, "message": "Access denied: Admin only"}

        domain = []
        state_filter = kwargs.get('state')
        if state_filter:
            domain.append(('state', '=', state_filter))

        requests = request.env['laundry.contract.request'].sudo().search(domain)
        return {"status": True, "data": [self._format_contract_request(r) for r in requests]}

    @http.route('/api/v1/admin/contract-request/action', type='jsonrpc', auth='none', methods=['POST'], csrf=False)
    def admin_contract_request_action(self, **kwargs):
        """
        Admin: advance a contract request's lifecycle.

        Body:
          request_id: int  — required
          action: negotiate | convert | cancel  — required
        """
        user, error = self._authenticate()
        if error:
            return error
        if not self._is_admin(user):
            return {"status": False, "message": "Access denied: Admin only"}

        request_id = kwargs.get('request_id')
        action = kwargs.get('action')
        if not request_id or not action:
            return {"status": False, "message": "Missing request_id or action"}

        req = request.env['laundry.contract.request'].with_user(user).browse(int(request_id))
        if not req.exists():
            return {"status": False, "message": "Contract request not found"}

        valid_actions_for_state = {
            'submitted': ['negotiate', 'cancel'],
            'in_negotiation': ['convert', 'cancel'],
        }
        allowed = valid_actions_for_state.get(req.state, [])
        if action not in allowed:
            return {
                "status": False,
                "message": f"Action '{action}' not allowed in state '{req.state}'. Allowed: {allowed}"
            }

        action_map = {
            'negotiate': req.action_start_negotiation,
            'convert': req.action_convert_to_contract,
            'cancel': req.action_cancel,
        }
        action_map[action]()

        return {
            "status": True,
            "message": f"Action '{action}' completed",
            "data": self._format_contract_request(req),
        }
