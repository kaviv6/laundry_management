from odoo import models, fields, api, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    def action_send_invoice_by_whatsapp(self):
            # Get the partner's mobile number
            partner = self.partner_id
            self.ensure_one()
            if not self.mobile:
                raise UserError(_("Partner Mobile Number Not Exist !"))
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
            # invoice_url = f"{base_url}/web/content/{self.active_id}?download=true"

            phone = str(partner.mobile)
            message = f"Hello {partner.name},\nHere is your invoice:\n"


            whatsapp_url = "https://web.whatsapp.com/send?l=&phone="+phone+"&text=" + message
            return {
                'type': 'ir.actions.act_url',
                'url': whatsapp_url,
                'target': 'new',
            }