from odoo import models, fields

class ResUsers(models.Model):
    _inherit = 'res.users'

    api_token = fields.Char("API Token", copy=False)
