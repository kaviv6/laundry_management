# -*- coding: utf-8 -*-

import base64
from odoo import models, fields, api

class MailComposeMessage(models.TransientModel):
    _inherit = 'mail.compose.message'

    @api.model
    def default_get(self, fields):
        res = super(MailComposeMessage, self).default_get(fields)
        if self.env.context.get('active_model') == 'laundry.contract.request' and self.env.context.get('active_id'):
            request = self.env['laundry.contract.request'].browse(self.env.context.get('active_id'))
            if request.pricelist_id:
                report = self.env.ref('laundry_management.action_report_laundry_pricelist')
                report_data = report._render_qweb_pdf(request.pricelist_id.id)
                attachment = self.env['ir.attachment'].create({
                    'name': f'{request.pricelist_id.name}.pdf',
                    'type': 'binary',
                    'datas': base64.b64encode(report_data[0]),
                    'res_model': 'mail.compose.message',
                    'res_id': 0,
                    'mimetype': 'application/pdf'
                })
                res['attachment_ids'] = [(6, 0, [attachment.id])]
        return res
