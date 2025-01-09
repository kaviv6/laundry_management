from odoo import api, fields, models, _


class LaundryOrder(models.Model):
    """laundry orders generating model"""
    _name = 'laundry.order'
    _inherit = 'mail.thread'
    _description = "Laundry Order"
    _order = 'order_date desc, id desc'

    name = fields.Char(string="Label", copy=False, help="Name of the record")
    invoice_count = fields.Integer(compute='_compute_invoice_count',
                                   string='#Invoice',
                                   help="Number of invoice count")
    work_count = fields.Integer(compute='_compute_work_count', string='# Works',
                                help="Number of work count")
    partner_id = fields.Many2one('res.partner', string='Customer',
                                 readonly=True,
                                 required=True,
                                 change_default=True, index=True,
                                 help="Name of customer"
                                 )
    order_date = fields.Datetime(string='Date', readonly=True, index=True,
                                 copy=False, default=fields.Datetime.now,
                                 help="Date of order")
    laundry_person_id = fields.Many2one('res.users', string='Laundry Person',
                                        required=True,
                                        help="Name of laundry person",default=lambda self:self.env.user)
    order_line_ids = fields.One2many('laundry.order.line', 'laundry_id',
                                     required=True, ondelete='cascade',
                                     help="Order lines of laundry orders")
    total_amount = fields.Float(compute='_compute_total_amount', string='Total',
                                store=True,
                                help="To get the Total amount")
    currency_id = fields.Many2one("res.currency", string="Currency",
                                  help="Name of currency",default=lambda self:self.env.company.currency_id.id)
    note = fields.Text(string='Terms and conditions',
                       help='Add terms and conditions')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('order', 'Laundry Order'),
        ('invoiced', 'Invoiced'),
        ('cancel', 'Cancelled'),
    ], string='Status', readonly=True, copy=False, index=True,
        track_visibility='onchange', default='draft', help="State of the Order")

    @api.model_create_multi
    def create(self, vals_list):
        """Creating the record of Laundry order."""
        for vals in vals_list:
            vals['name'] = self.env['ir.sequence'].next_by_code('laundry.order')
        return super().create(vals_list)


    @api.depends('order_line_ids')
    def _compute_total_amount(self):
        """Computing the total of total_amount in order lines."""
        total = 0
        for order in self:
            for line in order.order_line_ids:
                total += line.amount
            order.total_amount = total

    def close_order(self):
        """Confirming the order and after confirming order,it will create the
             washing model"""
        self.state = 'order'

    def action_create_invoice(self):
        """Creating a new invoice for the laundry orders."""
        invoice = self.env['account.move'].create({
            'partner_id': self.partner_id.id,
            'move_type': 'out_invoice',
            'invoice_date': fields.Date.today(),
            'invoice_origin' : self.name
        })

        product = self.env.ref('laundry_management.product_product_laundry_service')
        account = self.env.ref('laundry_management.laundry_journal')
        # Add invoice line(s)
        for line in self.order_line_ids:
            self.env['account.move.line'].create({
                'move_id': invoice.id,
                'product_id': product.id,
                'quantity': line.qty,
                'price_unit': line.price_unit,
                'account_id': account.id
            })


        invoice.action_post()
        self.state = "invoiced"


        return invoice



    def action_cancel_order(self):
        """Cancel the laundry order"""
        self.state = 'cancel'

    def _compute_invoice_count(self):
        """Compute the invoice count."""
        for order in self:
            order.invoice_count = len(order.env['account.move'].search(
                [('invoice_origin', '=', order.name)]))


    def action_view_invoice(self):
        """Function for viewing Laundry orders invoices."""
        self.ensure_one()
        inv_ids = []
        for each in self.env['account.move'].search(
                [('invoice_origin', '=', self.name)]):
            inv_ids.append(each.id)
        if inv_ids:
            if len(inv_ids) <= 1:
                value = {
                    'view_type': 'form',
                    'view_mode': 'form',
                    'res_model': 'account.move',
                    'view_id': self.env.ref('account.view_move_form').id,
                    'type': 'ir.actions.act_window',
                    'name': _('Invoice'),
                    'res_id': inv_ids and inv_ids[0]
                }
            else:
                value = {
                    'domain': str([('id', 'in', inv_ids)]),
                    'view_type': 'form',
                    'view_mode': 'list,form',
                    'res_model': 'account.move',
                    'view_id': False,
                    'type': 'ir.actions.act_window',
                    'name': _('Invoice'),
                }
            return value


class LaundryOrderLine(models.Model):
    """Laundry order lines generating model"""
    _name = 'laundry.order.line'
    _description = "Laundry Order Line"

    product_id = fields.Many2one('product.product', string='service',
                                 required=True, help="Name of the product", default=lambda self :self.env.ref('laundry_management.product_product_laundry_service'))
    qty = fields.Integer(string='No of items', required=True,
                         help="Number of quantity")
    description = fields.Text(string='Description',
                              help='Description of the line.')
    washing_type_id = fields.Many2one('washing.type', string='Washing Type',
                                      required=True,
                                      help='Select the type of wash')
    amount = fields.Float(compute='_compute_amount', string='Amount',
                          help='Total amount of the line.')
    laundry_id = fields.Many2one('laundry.order', string='Laundry Order',
                                 help='Corresponding laundry order')
    price_unit = fields.Float(string='Unit Price',compute='compute_price_unit')


    @api.depends('washing_type_id')
    def compute_price_unit(self):
        """compute unit price"""
        for line in self:
            unit_price = line.washing_type_id.amount
            line.price_unit = unit_price

    @api.depends('washing_type_id', 'qty')
    def _compute_amount(self):
        """Compute the total amount"""
        for line in self:
            total = line.washing_type_id.amount * line.qty
            line.amount = total

