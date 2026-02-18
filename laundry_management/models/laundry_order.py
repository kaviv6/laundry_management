import base64
import logging

from odoo import api, fields, models, _
_logger = logging.getLogger(__name__)

class LaundryOrder(models.Model):
    """laundry orders generating model"""
    _name = 'laundry.order'
    _inherit = ['mail.thread', 'portal.mixin']
    _description = "Laundry Order"
    _order = 'order_date desc, id desc'

    name = fields.Char(string="Label", copy=False, help="Name of the record")
    invoice_count = fields.Integer(compute='_compute_invoice_count',
                                   string='#Invoice',
                                   help="Number of invoice count")
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
                                        help="Name of laundry person", default=lambda self: self.env.user)
    order_line_ids = fields.One2many('laundry.order.line', 'laundry_id',
                                     required=True, ondelete='cascade',
                                     help="Order lines of laundry orders")
    total_amount = fields.Float(compute='_compute_total_amount', string='Total',
                                store=True,
                                help="To get the Total amount")
    currency_id = fields.Many2one("res.currency", string="Currency",
                                  help="Name of currency", default=lambda self: self.env.company.currency_id.id)
    note = fields.Text(string='Terms and conditions',
                       help='Add terms and conditions')
    pickup_request_ids = fields.One2many('laundry.pickup.request', 'order_id', string='Pickup Requests', readonly=True)
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
            'invoice_origin': self.name,
        })

        product = self.env.ref('laundry_management.product_product_laundry_service')

        for line in self.order_line_ids:
            self.env['account.move.line'].create({
                'move_id': invoice.id,
                'product_id': product.id,
                'quantity': line.qty,
                'price_unit': line.price_unit,
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

    def action_view_pickups(self):
        self.ensure_one()
        # Find related pickup requests via reverse M2O
        pickups = self.env['laundry.pickup.request'].search([('order_id', '=', self.id)])
        if not pickups:
            return False
        if len(pickups) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Pickup Request'),
                'res_model': 'laundry.pickup.request',
                'view_mode': 'form',
                'res_id': pickups.id,
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Pickup Requests'),
            'res_model': 'laundry.pickup.request',
            'view_mode': 'list,form',
            'domain': [('id', 'in', pickups.ids)],
            'target': 'current',
        }

    def process_close_invoice_and_email(self):
        """Close the order, create and post invoice, email PDF to customer.

        This reuses the same logic the cron uses but for a single order.
        """
        self.ensure_one()

        # Close order
        self.close_order()

        # Create and post invoice
        invoice = self.action_create_invoice()
        if not invoice:
            return False

        # Generate invoice PDF
        pdf, _ = self.env['ir.actions.report']._render_qweb_pdf(
            'account.account_invoices', invoice.id
        )
        pdf_name = f"{invoice.name or 'Invoice'}.pdf"

        attachment = self.env['ir.attachment'].create({
            'name': pdf_name,
            'type': 'binary',
            'datas': base64.b64encode(pdf),
            'res_model': 'account.move',
            'res_id': invoice.id,
            'mimetype': 'application/pdf',
        })

        # Try to use standard account invoice email template
        template = self.env.ref('account.email_template_edi_invoice', raise_if_not_found=False)
        partner_email = self.partner_id.email
        if template and partner_email:
            template.send_mail(invoice.id, force_send=True, email_values={
                'email_to': partner_email,
                'attachment_ids': [attachment.id],
            })

        return invoice

    @api.model
    def cron_close_and_invoice_draft_orders(self):
        """Scheduled job: On 1st of each month, close all draft laundry orders,
        create and post invoices, and email the invoice PDF to the customer."""

        # Only execute if there are draft orders
        draft_orders = self.search([('state', '=', 'draft')])
        if not draft_orders:
            return True

        for order in draft_orders:
            try:
                order.process_close_invoice_and_email()
            except Exception as e:
                _logger.error("Error processing laundry order %s: %s", order.name, e)
        return True


    def _compute_access_url(self):
        super(LaundryOrder, self)._compute_access_url()
        for order in self:
            order.access_url = '/my/laundry/orders'

class LaundryOrderLine(models.Model):
    """Laundry order lines generating model"""
    _name = 'laundry.order.line'
    _description = "Laundry Order Line"

    date = fields.Date(string='Service Date', default=fields.Date.today())
    product_id = fields.Many2one('product.product', string='service',
                                 required=True, help="Name of the product", default=lambda self: self.env.ref(
            'laundry_management.product_product_laundry_service'))
    qty = fields.Integer(string='No of items', required=True,
                         help="Number of quantity")
    description = fields.Text(string='Description',
                              help='Description of the line.')
    service_type_id = fields.Many2one('service.type', string='Service Type',
                                      required=True,
                                      help='Select the type of service')
    amount = fields.Float(compute='_compute_amount', string='Amount',
                          help='Total amount of the line.')
    laundry_id = fields.Many2one('laundry.order', string='Laundry Order',
                                 help='Corresponding laundry order')
    price_unit = fields.Float(string='Unit Price', compute='compute_price_unit')

    @api.depends('service_type_id')
    def compute_price_unit(self):
        """compute unit price"""
        for line in self:
            unit_price = line.service_type_id.amount
            line.price_unit = unit_price

    @api.depends('service_type_id', 'qty')
    def _compute_amount(self):
        """Compute the total amount"""
        for line in self:
            total = line.service_type_id.amount * line.qty
            line.amount = total
