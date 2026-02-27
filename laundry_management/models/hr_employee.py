from odoo import api, fields, models


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    is_rider = fields.Boolean(string='Is Rider', default=False,
                              help='Mark this employee as a Rider for laundry pickup requests.')
