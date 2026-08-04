from odoo import api, fields, models
from odoo.exceptions import ValidationError


class LaundryPromoCode(models.Model):
    _name = 'laundry.promo.code'
    _description = 'Laundry Promo Code'
    _order = 'id desc'

    name = fields.Char(string='Promo Name', required=True)
    code = fields.Char(string='Code', required=True, index=True)
    discount_type = fields.Selection([
        ('percent', 'Percentage'),
        ('fixed', 'Fixed Amount'),
    ], string='Discount Type', required=True, default='percent')
    discount_value = fields.Float(string='Discount Value', required=True)
    valid_from = fields.Date(string='Valid From')
    valid_to = fields.Date(string='Valid To')
    max_uses = fields.Integer(string='Max Uses', default=0, help='0 = unlimited')
    used_count = fields.Integer(string='Used Count', readonly=True, default=0)
    active = fields.Boolean(default=True)
    min_order_amount = fields.Float(string='Minimum Order Amount', default=0)

    _sql_constraints = [
        ('unique_code', 'UNIQUE(code)', 'Promo code must be unique.'),
    ]

    def apply_discount(self, amount):
        """Return the discounted amount after applying this promo."""
        self.ensure_one()
        if self.discount_type == 'percent':
            discount = amount * (self.discount_value / 100.0)
        else:
            discount = self.discount_value
        return max(0.0, amount - discount)

    @api.model
    def validate_and_get(self, code, order_amount=0):
        """Find a valid promo code or raise ValidationError."""
        promo = self.search([('code', '=', code), ('active', '=', True)], limit=1)
        if not promo:
            raise ValidationError('Invalid or inactive promo code.')

        today = fields.Date.today()
        if promo.valid_from and promo.valid_from > today:
            raise ValidationError('Promo code is not yet active.')
        if promo.valid_to and promo.valid_to < today:
            raise ValidationError('Promo code has expired.')
        if promo.max_uses and promo.used_count >= promo.max_uses:
            raise ValidationError('Promo code has reached its usage limit.')
        if order_amount < promo.min_order_amount:
            raise ValidationError(
                f'Minimum order amount for this promo is {promo.min_order_amount}.'
            )
        return promo

    def _increment_used(self):
        self.sudo().write({'used_count': self.used_count + 1})
