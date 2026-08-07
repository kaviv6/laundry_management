from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # related='company_id...., readonly=False — the standard Odoo pattern
    # for a per-company settings field (see the docstring example in
    # odoo/addons/base/models/res_config.py). Not config_parameter=, since
    # that's a single global value shared across every company.
    laundry_fcm_project_id = fields.Char(
        related='company_id.laundry_fcm_project_id',
        readonly=False,
        string="Firebase Project ID",
        help="From your Firebase project settings — the same project ID used by the mobile app's firebase_options.dart.",
    )
    laundry_fcm_service_account_json = fields.Char(
        related='company_id.laundry_fcm_service_account_json',
        readonly=False,
        string="Firebase Service Account JSON",
        help="Firebase console → Project Settings → Service Accounts → Generate new private key. "
             "Paste the entire downloaded JSON file's contents here.",
    )
