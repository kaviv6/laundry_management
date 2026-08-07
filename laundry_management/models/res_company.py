from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Per-company, not a global ir.config_parameter — a multi-company setup
    # (e.g. a franchise, see ROADMAP.md H6) can have a different Firebase
    # project per branch. Read by laundry.push.service._get_fcm_creds()
    # via self.env.company.
    laundry_fcm_project_id = fields.Char(string="Firebase Project ID")
    laundry_fcm_service_account_json = fields.Char(string="Firebase Service Account JSON")
