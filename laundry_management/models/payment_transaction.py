from odoo import fields, models


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    laundry_order_id = fields.Many2one(
        'laundry.order', string='Laundry Order', index=True,
        help="Set when this transaction was created from the mobile app's Pay Online flow.",
    )
    laundry_collected_by_id = fields.Many2one(
        'res.users', string='Collected By (Rider)', index=True,
        help="Set when a rider opened this Cashfree checkout in person at "
             "pickup/delivery (as opposed to the customer paying from their "
             "own Orders screen) — counts toward that rider's collection stat.",
    )
    laundry_collect_method = fields.Selection([
        ('upi', 'UPI'),
        ('card', 'Card'),
    ], string='Collection Method', help="The method the rider tapped in-app; only set alongside laundry_collected_by_id.")

    def _cashfree_prepare_order_payload(self):
        # odoo_payment_cashfree's own payload never sets order_meta.return_url
        # (fine for pure UPI-intent/no-redirect flows), but card payments go
        # through the issuing bank's OTP page, which does a real browser
        # redirect back afterwards — with no return_url to land on, that
        # redirect has nowhere to go and shows a 404 inside the SDK's
        # WebView. Cashfree's own Flutter SDK example sets exactly this
        # generic landing page for the same reason, so re-use it here.
        payload = super()._cashfree_prepare_order_payload()
        if self.provider_code == 'cashfree':
            payload.setdefault('order_meta', {})['return_url'] = (
                'https://www.cashfree.com/devstudio/preview/pg/web/checkout?order_id={order_id}'
            )
        return payload

    def _set_done(self, **kwargs):
        # _set_done() is Odoo's own confirmation funnel — every provider's
        # webhook/return handler (Cashfree's _process() included) ends up
        # here. It returns only the subset of `self` that actually just
        # transitioned into 'done' (already-done transactions are filtered
        # out by _update_state), so this is naturally idempotent against a
        # webhook firing twice.
        txs_done = super()._set_done(**kwargs)
        for tx in txs_done.filtered('laundry_order_id'):
            if tx.laundry_collected_by_id:
                # Rider opened the Cashfree checkout in person (e.g. handed
                # the customer their phone to pay by UPI/card at the door) —
                # a real online transaction, but it should count as this
                # rider's collection, not a generic "customer paid online".
                tx.laundry_order_id._register_payment(
                    tx.amount, method=tx.laundry_collect_method or 'online',
                    source='rider_collected', collected_by=tx.laundry_collected_by_id,
                    transaction=tx, reference=tx.reference,
                )
            else:
                tx.laundry_order_id._register_payment(
                    tx.amount, method='online', source='customer_online',
                    transaction=tx, reference=tx.reference,
                )
        return txs_done
