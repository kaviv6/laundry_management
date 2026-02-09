from odoo import api, fields, models, _


class LaundryPickupRequest(models.Model):
    _name = 'laundry.pickup.request'
    _description = 'Laundry Pickup Request'
    _inherit = 'mail.thread'
    _order = 'schedule_date asc, id desc'

    name = fields.Char(string='Request', copy=False, default=lambda self: _('New'))
    partner_id = fields.Many2one('res.partner', string='Customer', required=True, tracking=True)
    street = fields.Char(related='partner_id.street', string='Street', store=True, readonly=True)
    street2 = fields.Char(related='partner_id.street2', string='Street2', store=True, readonly=True)
    city = fields.Char(related='partner_id.city', string='City', store=True, readonly=True)
    zip = fields.Char(related='partner_id.zip', string='ZIP', store=True, readonly=True)
    state_id = fields.Many2one(related='partner_id.state_id', comodel_name='res.country.state', string='State', store=True, readonly=True)
    country_id = fields.Many2one(related='partner_id.country_id', comodel_name='res.country', string='Country', store=True, readonly=True)

    schedule_date = fields.Datetime(string='Scheduled Pickup', tracking=True)
    pickup_date = fields.Datetime(string='Pickup Date', readonly=True, tracking=True)

    line_ids = fields.One2many('laundry.pickup.request.line', 'request_id', string='Lines')
    total_amount = fields.Float(string='Total', compute='_compute_total_amount', store=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id.id)

    order_id = fields.Many2one('laundry.order', string='Laundry Order', readonly=True, copy=False)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('scheduled', 'Scheduled'),
        ('picked', 'Picked Up'),
        ('delivered', 'Delivered'),
        ('cancel', 'Cancelled'),
    ], default='draft', tracking=True)

    @api.depends('line_ids.amount')
    def _compute_total_amount(self):
        for request in self:
            request.total_amount = sum(request.line_ids.mapped('amount'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('laundry.pickup.request')
        return super().create(vals_list)

    def action_schedule(self):
        self.write({'state': 'scheduled'})

    def action_deliver(self):
        for request in self:
            # If an order exists, close, invoice, and email using reusable method
            if request.order_id:
                request.order_id.process_close_invoice_and_email()
            request.write({'state': 'delivered'})

    def action_cancel(self):
        self.write({'state': 'cancel'})

    def action_pickup(self):
        for request in self:
            if not request.order_id:
                # Create Laundry Order with lines from pickup request
                order_vals = {
                    'partner_id': request.partner_id.id,
                    'laundry_person_id': self.env.user.id,
                    'order_line_ids': [],
                }
                line_vals_list = []
                for line in request.line_ids:
                    line_vals_list.append((0, 0, {
                        'service_type_id': line.service_type_id.id,
                        'qty': line.qty,
                        'description': '',
                    }))
                order_vals['order_line_ids'] = line_vals_list
                order = self.env['laundry.order'].create(order_vals)
                request.order_id = order.id
            request.write({'state': 'picked', 'pickup_date': fields.Datetime.now()})

    def action_open_map(self):
        """Open Google Maps directions to the customer's address.

        Uses the partner's postal address as the destination and relies on the
        device's current location as the origin (handled by Google Maps).
        """
        self.ensure_one()

        # Build the Google Maps Directions URL
        # doc: https://developers.google.com/maps/documentation/urls/get-started
        from urllib.parse import urlencode

        query_params = {
            'api': 1,
            'travelmode': 'driving',
        }

        if self.partner_id.partner_latitude and self.partner_id.partner_longitude:
            query_params['destination'] = f"{self.partner_id.partner_latitude},{self.partner_id.partner_longitude}"
        else:
            def _format_address(partner):
                address_parts = [
                    partner.street or '',
                    partner.street2 or '',
                    partner.city or '',
                    (partner.state_id and partner.state_id.name) or '',
                    partner.zip or '',
                    (partner.country_id and partner.country_id.name) or '',
                ]
                # Keep only non-empty, trimmed parts
                return ', '.join([p.strip() for p in address_parts if p and p.strip()])

            destination = _format_address(self.partner_id)
            # If no destination can be built, fallback to partner display name
            if not destination:
                destination = self.partner_id.display_name
            query_params['destination'] = destination

        url = 'https://www.google.com/maps/dir/?' + urlencode(query_params)

        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }

    def action_view_order(self):
        self.ensure_one()
        if not self.order_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Laundry Order'),
            'res_model': 'laundry.order',
            'view_mode': 'form',
            'res_id': self.order_id.id,
            'target': 'current',
        }


class LaundryPickupRequestLine(models.Model):
    _name = 'laundry.pickup.request.line'
    _description = 'Laundry Pickup Request Line'

    request_id = fields.Many2one('laundry.pickup.request', string='Request', ondelete='cascade')
    date = fields.Date(string='Service Date', default=fields.Date.today())
    product_id = fields.Many2one('product.product', string='Service', required=True, default=lambda self: self.env.ref('laundry_management.product_product_laundry_service'))
    service_type_id = fields.Many2one('service.type', string='Service Type', required=True)
    qty = fields.Integer(string='Qty', required=True, default=1)
    price_unit = fields.Float(string='Unit Price', compute='_compute_price_unit', store=True)
    amount = fields.Float(string='Amount', compute='_compute_amount', store=True)

    @api.depends('service_type_id')
    def _compute_price_unit(self):
        for line in self:
            line.price_unit = line.service_type_id.amount

    @api.depends('qty', 'price_unit')
    def _compute_amount(self):
        for line in self:
            line.amount = (line.price_unit or 0.0) * (line.qty or 0)
