from odoo import http, _
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.http import request

class LaundryCustomerPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if 'contract_count' in counters:
            partner = request.env.user.partner_id
            values['contract_count'] = request.env['laundry.contract'].search_count([
                ('partner_id', '=', partner.id)
            ])
        return values

    @http.route(['/my/contracts', '/my/contracts/page/<int:page>'], type='http', auth="user", website=True)
    def portal_my_contracts(self, page=1, date_begin=None, date_end=None, sortby=None, **kw):
        values = self._prepare_portal_layout_values()
        partner = request.env.user.partner_id
        LaundryContract = request.env['laundry.contract']

        domain = [('partner_id', '=', partner.id)]

        contract_count = LaundryContract.search_count(domain)
        pager = portal_pager(
            url="/my/contracts",
            url_args={'date_begin': date_begin, 'date_end': date_end, 'sortby': sortby},
            total=contract_count,
            page=page,
            step=self._items_per_page
        )

        contracts = LaundryContract.search(domain, limit=self._items_per_page, offset=pager['offset'])
        values.update({
            'contracts': contracts,
            'page_name': 'contract',
            'pager': pager,
            'default_url': '/my/contracts',
        })
        return request.render("laundry_management.portal_my_contracts", values)
