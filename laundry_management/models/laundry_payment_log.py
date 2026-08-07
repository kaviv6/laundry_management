from odoo import fields, models


class LaundryPaymentLog(models.Model):
    """One row per payment event against a laundry.order — online (Cashfree
    webhook), wallet debit, or a rider collecting cash/UPI/card in person.
    Single audit trail so amount_paid/amount_due/payment_status on the order
    stay correct no matter which channel paid, and so a rider's "collected"
    stat can be summed straight from here."""
    _name = 'laundry.payment.log'
    _description = 'Laundry Order Payment Log'
    _order = 'create_date desc'

    order_id = fields.Many2one(
        'laundry.order', string='Order', required=True, ondelete='cascade', index=True,
    )
    currency_id = fields.Many2one(related='order_id.currency_id', store=True, readonly=True)
    amount = fields.Monetary(string='Amount', required=True)
    method = fields.Selection([
        ('online', 'Online (Cashfree)'),
        ('wallet', 'Wallet'),
        ('cash', 'Cash'),
        ('upi', 'UPI'),
        ('card', 'Card'),
    ], string='Method', required=True)
    source = fields.Selection([
        ('customer_online', 'Customer — Online'),
        ('customer_wallet', 'Customer — Wallet'),
        ('rider_collected', 'Rider Collected'),
    ], string='Source', required=True)
    collected_by_id = fields.Many2one(
        'res.users', string='Collected By (Rider)',
        help='Set only when a rider collected this payment in person.',
    )
    transaction_id = fields.Many2one(
        'payment.transaction', string='Payment Transaction',
        help='Set only for online payments — links back to the Cashfree transaction.',
    )
    reference = fields.Char(string='Reference')
