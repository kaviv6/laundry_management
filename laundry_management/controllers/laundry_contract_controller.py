from odoo import http
from odoo.http import request

class LaundryContractController(http.Controller):

    @http.route('/laundry/contract', type='http', auth='public', website=True)
    def laundry_contract_form(self, **kwargs):
        return request.render('laundry_management.laundry_contract_form_template', {})

    @http.route('/laundry/contract/submit', type='http', auth='public', website=True, methods=['POST'])
    def laundry_contract_submit(self, **post):
        vals = {
            'name': post.get('name'),
            'mobile': post.get('mobile'),
            'email': post.get('email'),
            'business_type': post.get('business_type'),
            'description': post.get('description'),
        }
        if not request.env.user._is_public():
             vals['partner_id'] = request.env.user.partner_id.id
             
        request.env['laundry.contract'].sudo().create(vals)
        return request.render('laundry_management.laundry_contract_success_template', {})
