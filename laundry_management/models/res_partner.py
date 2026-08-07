from odoo import models, fields


class ResPartner(models.Model):
    _inherit = 'res.partner'

    laundry_address_label = fields.Char(
        string="Address Label",
        help="Customer-facing label for this saved address, e.g. Home, Office.",
    )
    laundry_is_default_address = fields.Boolean(
        string="Default Laundry Address",
        default=False,
        help="Marks which address (the partner itself or one of its delivery "
             "child contacts) the mobile app should pre-select for new pickups.",
    )
