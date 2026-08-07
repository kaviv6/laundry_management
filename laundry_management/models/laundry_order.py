import base64
import logging

from markupsafe import Markup

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class LaundryOrder(models.Model):
    _name = 'laundry.order'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = "Laundry Order"
    _order = 'order_date desc, id desc'

    name = fields.Char(string="Order Ref", copy=False, readonly=True)
    company_id = fields.Many2one(
        'res.company', string='Company',
        required=True, index=True, default=lambda self: self.env.company,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id', store=True, readonly=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Customer',
        readonly=True, required=True, change_default=True, index=True,
        tracking=True,
    )
    order_date = fields.Datetime(
        string='Date', readonly=True, index=True,
        copy=False, default=fields.Datetime.now,
    )
    laundry_person_id = fields.Many2one(
        'res.users', string='Laundry Person', required=True,
        default=lambda self: self.env.user,
        tracking=True,
    )
    rider_id = fields.Many2one(
        'res.users', string='Rider', tracking=True,
        domain=lambda self: [
            ('group_ids', 'in', [self.env.ref('laundry_management.group_laundry_rider').id])
        ],
    )
    order_line_ids = fields.One2many(
        'laundry.order.line', 'laundry_id', string='Order Lines', required=True,
    )
    total_amount = fields.Float(
        compute='_compute_total_amount', string='Total', store=True,
    )
    note = fields.Text(string='Terms and Conditions')
    promo_id = fields.Many2one(
        'laundry.promo.code', string='Promo Applied',
        readonly=True, copy=False, ondelete='set null',
    )
    promo_discount = fields.Float(
        string='Promo Discount', readonly=True, copy=False, default=0.0,
    )
    payment_method = fields.Selection([
        ('cod', 'Cash on Delivery'),
        ('online', 'Online Payment'),
        ('wallet', 'Wallet'),
    ], string='Payment Method', default='cod', tracking=True)
    payment_log_ids = fields.One2many(
        'laundry.payment.log', 'order_id', string='Payments',
    )
    amount_paid = fields.Float(
        compute='_compute_payment_status', store=True, string='Amount Paid',
    )
    amount_due = fields.Float(
        compute='_compute_payment_status', store=True, string='Amount Due',
    )
    payment_status = fields.Selection([
        ('not_paid', 'Not Paid'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
    ], compute='_compute_payment_status', store=True, default='not_paid', string='Payment Status')
    pickup_request_ids = fields.One2many(
        'laundry.pickup.request', 'order_id', string='Pickup Requests', readonly=True,
    )
    contract_id = fields.Many2one(
        'laundry.contract', string='B2B Contract',
        help='Pricelist from the contract overrides default service type prices',
        tracking=True,
    )
    is_express = fields.Boolean(
        string='Express Service', default=False,
        help='Priority processing — applies a 20% surcharge',
        tracking=True,
    )
    eta = fields.Datetime(string='ETA', help='Estimated delivery/completion time', tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('order', 'Confirmed'),
        ('invoiced', 'Invoiced'),
        ('cancel', 'Cancelled'),
    ], string='Status', readonly=True, copy=False, index=True,
        tracking=True, default='draft',
    )

    # ------------------------------------------------------------------
    # Rating fields (simple per-order rating, no rating.mixin dependency)
    # ------------------------------------------------------------------
    customer_rating = fields.Float(
        string='Rating', digits=(2, 1), default=0.0,
        readonly=True, copy=False,
    )
    customer_review = fields.Text(string='Customer Review', readonly=True, copy=False)

    @api.depends('customer_rating')
    def _compute_rating_stats(self):
        for order in self:
            if order.customer_rating > 0:
                order.rating_avg = order.customer_rating
                order.rating_count = 1
            else:
                order.rating_avg = 0.0
                order.rating_count = 0

    rating_avg = fields.Float(
        string='Average Rating', compute='_compute_rating_stats', store=True,
    )
    rating_count = fields.Integer(
        string='Rating Count', compute='_compute_rating_stats', store=True,
    )

    # ------------------------------------------------------------------
    # invoice stat (search by origin avoids a stored FK)
    # ------------------------------------------------------------------
    invoice_count = fields.Integer(compute='_compute_invoice_count', string='Invoices')
    garment_count = fields.Integer(compute='_compute_garment_count', string='Garments')

    # ------------------------------------------------------------------
    # Auto-subscribe customer as follower so tracking posts email them
    # ------------------------------------------------------------------
    def _mail_get_partner_fields(self, introspect_fields=False):
        return ['partner_id']

    # ------------------------------------------------------------------
    # Compute
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals['name'] = self.env['ir.sequence'].next_by_code('laundry.order')
        return super().create(vals_list)

    @api.depends('order_line_ids.amount', 'promo_discount')
    def _compute_total_amount(self):
        for order in self:
            subtotal = sum(order.order_line_ids.mapped('amount'))
            order.total_amount = max(0.0, subtotal - order.promo_discount)

    @api.depends('payment_log_ids.amount', 'total_amount')
    def _compute_payment_status(self):
        for order in self:
            paid = sum(order.payment_log_ids.mapped('amount'))
            order.amount_paid = paid
            order.amount_due = max(0.0, order.total_amount - paid)
            if paid <= 0:
                order.payment_status = 'not_paid'
            elif order.amount_due <= 0.01:
                order.payment_status = 'paid'
            else:
                order.payment_status = 'partial'

    def _compute_invoice_count(self):
        for order in self:
            order.invoice_count = self.env['account.move'].search_count(
                [('invoice_origin', '=', order.name), ('move_type', '=', 'out_invoice')]
            )

    def _compute_garment_count(self):
        for order in self:
            order.garment_count = self.env['laundry.garment'].search_count(
                [('order_id', '=', order.id)]
            )

    # ------------------------------------------------------------------
    # Chatter notification helper — uses message_post() so the message
    # is stored in chatter AND emails followers (including the customer)
    # ------------------------------------------------------------------
    def _notify_customer(self, template_ref):
        """Render a mail.template and post it to chatter (emails followers)."""
        template = self.env.ref(template_ref, raise_if_not_found=False)
        if not template:
            return
        msg = template.sudo()._generate_template(
            [self.id], ['subject', 'body_html']
        )[self.id]
        self.message_post(
            body=Markup(msg.get('body_html') or ''),
            subject=msg.get('subject') or '',
            subtype_xmlid='mail.mt_comment',
            partner_ids=[self.partner_id.id] if self.partner_id else [],
        )

    # ------------------------------------------------------------------
    # Business actions
    # ------------------------------------------------------------------
    def action_apply_promo(self, promo_code):
        """Apply a promo code to the order. Returns the applied discount amount."""
        self.ensure_one()
        if self.state != 'draft':
            raise Exception("Promo codes can only be applied to draft orders.")
        if self.promo_id:
            raise Exception("A promo code has already been applied to this order.")
        subtotal = sum(self.order_line_ids.mapped('amount'))
        promo = self.env['laundry.promo.code'].sudo().validate_and_get(promo_code, subtotal)
        discounted_total = promo.apply_discount(subtotal)
        discount_amount = subtotal - discounted_total
        self.sudo().write({'promo_id': promo.id, 'promo_discount': discount_amount})
        promo._increment_used()
        return discount_amount

    def action_wallet_pay(self):
        """Pay the order's remaining balance from the customer's wallet."""
        self.ensure_one()
        if self.state == 'cancel':
            raise Exception("Cannot pay a cancelled order.")
        if self.payment_status == 'paid':
            raise Exception("This order is already fully paid.")
        user = self.env['res.users'].sudo().search(
            [('partner_id', '=', self.partner_id.id)], limit=1
        )
        if not user:
            raise Exception("No user account found for this customer.")
        amount = self.amount_due if self.amount_due > 0 else self.total_amount
        if amount <= 0:
            raise Exception("Order has no amount to pay.")
        user.wallet_deduct(amount)
        self.sudo().write({'payment_method': 'wallet'})
        self._register_payment(amount, method='wallet', source='customer_wallet')
        return True

    def _register_payment(self, amount, method, source, collected_by=None, transaction=None, reference=None):
        """Single funnel for every way an order can get paid — online
        (Cashfree webhook), wallet debit, or a rider collecting cash/UPI/card
        in person. Keeps amount_paid/amount_due/payment_status correct
        regardless of channel, and notifies the customer of the update."""
        self.ensure_one()
        if amount <= 0:
            return
        self.env['laundry.payment.log'].sudo().create({
            'order_id': self.id,
            'amount': amount,
            'method': method,
            'source': source,
            'collected_by_id': collected_by.id if collected_by else False,
            'transaction_id': transaction.id if transaction else False,
            'reference': reference or '',
        })
        self.invalidate_recordset(['amount_paid', 'amount_due', 'payment_status'])

        fully_paid = self.payment_status == 'paid'
        title = 'Payment Received' if fully_paid else 'Partial Payment Received'
        body = f'We received Rs.{amount:.0f} for order {self.name}. '
        body += 'Fully paid — thank you!' if fully_paid else f'Remaining due: Rs.{self.amount_due:.0f}'

        users = self.env['res.users'].sudo().search([
            ('partner_id', '=', self.partner_id.id), ('push_token', '!=', False),
        ])
        self.env['laundry.push.service']._notify_users(
            users, title, body,
            data={
                'type': 'order', 'order_id': str(self.id),
                'state': self.state, 'payment_status': self.payment_status,
            },
        )

    def close_order(self):
        self.state = 'order'
        self._notify_customer('laundry_management.email_template_order_confirmed')

    def action_cancel_order(self):
        self.state = 'cancel'
        self._notify_customer('laundry_management.email_template_order_cancelled')

    def _build_invoice(self, use_sudo=False):
        """Create, populate and post an invoice for this order. Returns the move."""
        # Environment has no .sudo() (that's a recordset method) — the
        # correct way to get a superuser copy of an environment itself is
        # calling it with su=True.
        env = self.env if not use_sudo else self.env(su=True)
        product = self.env.ref('laundry_management.product_product_laundry_service')
        invoice = env['account.move'].create({
            'partner_id': self.partner_id.id,
            'move_type': 'out_invoice',
            'invoice_date': fields.Date.today(),
            'invoice_origin': self.name,
            'invoice_line_ids': [
                (0, 0, {
                    'product_id': product.id,
                    'quantity': line.qty,
                    'price_unit': line.price_unit,
                    'name': line.service_type_id.name or product.name,
                })
                for line in self.order_line_ids
            ],
        })
        invoice.sudo().action_post()
        return invoice

    def action_create_invoice(self):
        """Admin UI button — create invoice and mark invoiced."""
        self.ensure_one()
        invoice = self._build_invoice()
        self.state = 'invoiced'
        self._notify_customer('laundry_management.email_template_order_invoiced')
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': invoice.id,
        }

    def action_view_invoice(self):
        self.ensure_one()
        invoices = self.env['account.move'].search(
            [('invoice_origin', '=', self.name), ('move_type', '=', 'out_invoice')]
        )
        if not invoices:
            return False
        action = {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'name': _('Invoices'),
        }
        if len(invoices) == 1:
            action.update({'view_mode': 'form', 'res_id': invoices.id})
        else:
            action.update({'view_mode': 'list,form', 'domain': [('id', 'in', invoices.ids)]})
        return action

    def action_view_pickups(self):
        self.ensure_one()
        pickups = self.env['laundry.pickup.request'].search([('order_id', '=', self.id)])
        if not pickups:
            return False
        action = {
            'type': 'ir.actions.act_window',
            'res_model': 'laundry.pickup.request',
            'name': _('Pickup Requests'),
        }
        if len(pickups) == 1:
            action.update({'view_mode': 'form', 'res_id': pickups.id})
        else:
            action.update({'view_mode': 'list,form', 'domain': [('id', 'in', pickups.ids)]})
        return action

    def action_view_garments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'laundry.garment',
            'name': _('Garments'),
            'view_mode': 'list,form',
            'domain': [('order_id', '=', self.id)],
            'context': {'default_order_id': self.id},
        }

    def process_close_invoice_and_email(self):
        """Close the order, invoice, and email the PDF to the customer.

        Called from the Rider Deliver button and the monthly cron.
        Uses sudo() ONLY for accounting operations — the Rider group has no
        accounting permissions. Entry point (action_deliver) validates Rider
        access via normal ACLs before reaching here.
        """
        self.ensure_one()
        self.close_order()

        invoice = self._build_invoice(use_sudo=True)
        self.state = 'invoiced'
        self._notify_customer('laundry_management.email_template_order_invoiced')

        # Email invoice PDF using the standard account invoice email template
        pdf, _ = self.env['ir.actions.report'].sudo()._render_qweb_pdf(
            'account.account_invoices', invoice.id
        )
        attachment = self.env['ir.attachment'].sudo().create({
            'name': f"{invoice.name or 'Invoice'}.pdf",
            'type': 'binary',
            'datas': base64.b64encode(pdf),
            'res_model': 'account.move',
            'res_id': invoice.id,
            'mimetype': 'application/pdf',
        })
        inv_template = self.env.ref('account.email_template_edi_invoice', raise_if_not_found=False)
        if inv_template and self.partner_id.email:
            inv_template.sudo().send_mail(
                invoice.id, force_send=True,
                email_values={'email_to': self.partner_id.email, 'attachment_ids': [attachment.id]},
            )
        return invoice

    @api.model
    def cron_close_and_invoice_draft_orders(self):
        """Monthly cron: close all draft orders, create invoices, email PDFs."""
        draft_orders = self.search([('state', '=', 'draft')])
        for order in draft_orders:
            try:
                order.process_close_invoice_and_email()
            except Exception as e:
                _logger.error("Error processing laundry order %s: %s", order.name, e)
        return True


class LaundryOrderLine(models.Model):
    _name = 'laundry.order.line'
    _description = "Laundry Order Line"

    date = fields.Date(string='Service Date', default=fields.Date.today)
    product_id = fields.Many2one(
        'product.product', string='Product', required=True,
        default=lambda self: self.env.ref(
            'laundry_management.product_product_laundry_service', raise_if_not_found=False
        ),
    )
    qty = fields.Integer(string='Qty', required=True, default=1)
    description = fields.Text(string='Description')
    service_type_id = fields.Many2one('service.type', string='Service Type', required=True)
    price_unit = fields.Float(string='Unit Price', compute='_compute_price_unit', store=True)
    amount = fields.Float(string='Subtotal', compute='_compute_amount', store=True)
    laundry_id = fields.Many2one('laundry.order', string='Order', ondelete='cascade')

    @api.depends('service_type_id', 'qty', 'laundry_id.contract_id', 'laundry_id.is_express')
    def _compute_price_unit(self):
        for line in self:
            base = line.service_type_id.amount or 0.0
            contract = line.laundry_id.contract_id
            if contract and contract.pricelist_id:
                # Best volume tier: highest min_qty that still applies for this qty
                items = contract.pricelist_id.pricelist_item_ids.filtered(
                    lambda i: i.service_type_id == line.service_type_id
                              and i.min_qty <= (line.qty or 1)
                ).sorted('min_qty', reverse=True)
                if items:
                    best = items[0]
                    base = best.price * (1 - best.discount_percent / 100.0)
            if line.laundry_id.is_express:
                base = base * 1.20
            line.price_unit = base

    @api.depends('price_unit', 'qty')
    def _compute_amount(self):
        for line in self:
            line.amount = line.price_unit * line.qty

    # Keep old name as alias so existing code calling compute_price_unit still works
    compute_price_unit = _compute_price_unit
