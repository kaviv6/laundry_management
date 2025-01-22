from odoo import fields, models


class PosConfig(models.Model):
    _inherit = 'pos.config'

    laundry_services = fields.Boolean(string="Laundry Business")