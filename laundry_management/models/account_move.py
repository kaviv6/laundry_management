from odoo import models, fields, api, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = "account.move"

    def action_send_invoice_by_whatsapp(self):
            # Get the partner's mobile number
            partner = self.partner_id
            self.ensure_one()
            if not partner.phone:
                raise UserError(_("Partner Mobile Number Not Exist !"))

            template = self.env.ref(
                "account.email_template_edi_invoice"
            )

            ctx = {
                "default_model": "account.move",
                "default_res_ids": self.ids,
                "default_use_template": bool(template.id),
                "default_template_id": template.id,
                "default_composition_mode": "comment",
                "force_email": True,
            }
            return {
                "type": "ir.actions.act_window",
                "view_mode": "form",
                "res_model": "mail.compose.message",
                "views": [(False, "form")],
                "view_id": False,
                "target": "new",
                "context": ctx,
            }

