from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ResUsers(models.Model):
    _inherit = 'res.users'

    api_token = fields.Char("API Token", copy=False)
    api_token_expiry = fields.Datetime("API Token Expiry", copy=False)
    push_token = fields.Char("FCM Push Token", copy=False)
    wallet_balance = fields.Float("Wallet Balance", default=0.0, digits=(10, 2))

    def wallet_topup(self, amount):
        """Add amount to wallet. amount must be positive."""
        self.ensure_one()
        if amount <= 0:
            raise ValidationError('Top-up amount must be positive.')
        self.sudo().wallet_balance += amount

    def wallet_deduct(self, amount):
        """Deduct amount from wallet. Raises if insufficient balance."""
        self.ensure_one()
        if amount <= 0:
            raise ValidationError('Deduction amount must be positive.')
        if self.wallet_balance < amount:
            raise ValidationError(
                f'Insufficient wallet balance. Available: {self.wallet_balance}, Required: {amount}'
            )
        self.sudo().wallet_balance -= amount
