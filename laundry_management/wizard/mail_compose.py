from odoo import models, fields
from odoo.exceptions import UserError
from odoo.tools import html2plaintext, plaintext2html
import re
from urllib.parse import quote
import base64


class MailComposeWizard(models.TransientModel):
    _inherit = 'mail.compose.message'

    def action_send_invoice(self):
        body_text = html2plaintext(self.body or "").strip()

        if not self.partner_ids or not self.partner_ids[0].phone:
            raise UserError('Partner Mobile Number Not Exist!')

        # Normalize phone number for WhatsApp (digits only, no +, spaces or punctuation)
        raw_phone = str(self.partner_ids[0].phone or "")
        phone = re.sub(r"[^0-9]", "", raw_phone)
        if not phone:
            raise UserError('Partner Mobile Number Not Exist!')

        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')

        # Build message with invoice PDF link (auto-generated) and other attachments
        lines = [body_text] if body_text else []
        if self.attachment_ids:
            lines.append("")
            lines.append("Attachments:")
            for attachment in self.attachment_ids:
                attachment.generate_access_token()
                # Public download URL that works for both web and mobile
                download_url = f"{base_url}/web/content/{attachment.id}?download=1&access_token={attachment.access_token}"
                lines.append(download_url)

        context = dict(self.env.context or {})
        active_id = context.get('active_id')
        active_model = context.get('active_model')

        # Ensure invoice PDF link is included for account.move
        if active_model == 'account.move' and active_id:
            try:
                move = self.env[active_model].browse(active_id)
                # Use core report xmlids known to exist, with fallback
                report_xmlid = 'account.account_invoices'
                try:
                    pdf_content, report_type = self.env['ir.actions.report']._render_qweb_pdf(report_xmlid, [move.id])
                except Exception:
                    pdf_content = None
                if not pdf_content:
                    try:
                        pdf_content, report_type = self.env['ir.actions.report']._render_qweb_pdf('account.account_invoices_without_payment', [move.id])
                    except Exception:
                        pdf_content = None
                if pdf_content:
                    attach_name = f"{move.name or 'Invoice'}.pdf"
                    invoice_attachment = self.env['ir.attachment'].create({
                        'name': attach_name,
                        'type': 'binary',
                        'datas': base64.b64encode(pdf_content),
                        'mimetype': 'application/pdf',
                        'res_model': active_model,
                        'res_id': move.id,
                    })
                    invoice_attachment.generate_access_token()
                    invoice_link = f"{base_url}/web/content/{invoice_attachment.id}?download=1&access_token={invoice_attachment.access_token}"
                    # Prepend the invoice link at the top for visibility
                    if lines:
                        lines = ["Invoice PDF:", invoice_link, ""] + lines
                    else:
                        lines = ["Invoice PDF:", invoice_link]
            except Exception:
                # Silently ignore report generation issues to not block WhatsApp flow
                pass

        # Store a readable message in chatter
        if lines and active_id and active_model:
            message_html = "<br/>".join([plaintext2html(line) if line else "<br/>" for line in lines])
            self.env['mail.message'].create({
                'partner_ids': [(6, 0, self.partner_ids.ids)],
                'model': active_model,
                'res_id': active_id,
                'author_id': self.env.user.partner_id.id,
                'body': message_html or False,
                'message_type': 'comment',
            })

        # Encode message for WhatsApp (new lines as %0A)
        message_for_wa = quote("\n".join(lines)) if lines else ""
        url = f"https://wa.me/{phone}?text={message_for_wa}"
        return {
            'type': 'ir.actions.act_url',
            'url': url,
            'target': 'new',
        }
