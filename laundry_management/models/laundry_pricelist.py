from odoo import fields, models


class LaundryPricelist(models.Model):
    _name = 'laundry.pricelist'
    _description = 'Laundry Pricelist'
    _order = 'name'

    name = fields.Char(string='Pricelist Name', required=True)
    pricelist_item_ids = fields.One2many(
        'laundry.pricelist.item', 'pricelist_id', string='Items'
    )
    active = fields.Boolean(default=True)


class LaundryPricelistItem(models.Model):
    _name = 'laundry.pricelist.item'
    _description = 'Laundry Pricelist Item'
    _order = 'pricelist_id, service_type_id, min_qty'

    pricelist_id = fields.Many2one(
        'laundry.pricelist', string='Pricelist', required=True, ondelete='cascade'
    )
    product_id = fields.Many2one('product.product', string='Product')
    service_type_id = fields.Many2one('service.type', string='Service Type', required=True)
    min_qty = fields.Integer(string='Min Qty', default=1,
                             help='Minimum quantity for this tier to apply')
    price = fields.Float(string='Price', required=True)
    discount_percent = fields.Float(string='Discount %', default=0.0,
                                    help='Extra percentage discount on top of the price')
