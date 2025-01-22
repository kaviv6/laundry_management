from odoo import models, fields
from odoo.exceptions import UserError
from odoo.tools import html2plaintext


class MailComposeWizard(models.TransientModel):
    _inherit = 'mail.compose.message'

    def action_send_invoice(self):
        text = html2plaintext(self.body or "")

        # Ensure the partner has a mobile number
        if not self.partner_ids[0].mobile:
            raise UserError('Partner Mobile Number Not Exist!')

        phone = str(self.partner_ids[0].mobile)
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')

        # Check if there are attachments and generate the links
        if self.attachment_ids:
            text += '%0A%0A Other Attachments :'
            for attachment in self.attachment_ids:
                attachment.generate_access_token()
                text += '%0A%0A'
                text += base_url + '/web/content/ir.attachment/' + \
                        str(attachment.id) + '/datas?access_token=' + \
                        attachment.access_token

        context = dict(self._context or {})
        active_id = context.get('active_id', False)
        active_model = context.get('active_model', False)

        if text and active_id and active_model:
            # Clean and format the text for the message
            message = str(text).replace('*', '').replace('_', '').replace('%0A', '<br/>').replace('%20', ' ').replace(
                '%26', '&')

            self.env['mail.message'].create({
                'partner_ids': [(6, 0, self.partner_ids.ids)],
                'model': 'account.move',
                'res_id': active_id,
                'author_id': self.env.user.partner_id.id,
                'body': message or False,
                'message_type': 'comment',
            })

    # Generate the WhatsApp URL with the message
        url = f"https://api.whatsapp.com/send?phone={phone}&text={text}"

    # Return the URL action to open WhatsApp
        return {
        'type': 'ir.actions.act_url',
        'url': url,
        'target': 'new',
    }
