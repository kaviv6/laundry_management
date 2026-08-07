from odoo import api, fields, models, _


class LaundryContractRequest(models.Model):
    _name = 'laundry.contract.request'
    _description = 'Laundry Contract Request'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Request', copy=False, readonly=True, default=lambda self: _('New'))
    partner_id = fields.Many2one('res.partner', string='Company / Customer', tracking=True)
    business_name = fields.Char(string='Business Name', tracking=True)
    contact_name = fields.Char(string='Contact Name')
    email_from = fields.Char(string='Email')
    phone = fields.Char(string='Phone')
    company_type = fields.Selection([
        ('hotel', 'Hotel'),
        ('restaurant', 'Restaurant'),
        ('hostel', 'Hostel'),
        ('other', 'Other'),
    ], string='Business Type', tracking=True)
    pricelist_id = fields.Many2one('laundry.pricelist', string='Pricelist', tracking=True)
    collection_time = fields.Float(string='Collection Time')
    description = fields.Html(string='Description')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('in_negotiation', 'In Negotiation'),
        ('converted', 'Converted'),
        ('cancel', 'Cancelled'),
    ], default='draft', string='Status', tracking=True, copy=False)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('laundry.contract.request')
        return super().create(vals_list)

    def action_submit_request(self):
        self.write({'state': 'submitted'})

    def action_start_negotiation(self):
        self.write({'state': 'in_negotiation'})

    def action_convert_to_contract(self):
        for req in self:
            self.env['laundry.contract'].create({
                'name': req.business_name or req.contact_name or req.partner_id.name or req.name,
                'partner_id': req.partner_id.id,
                'mobile': req.phone or '',
                'email': req.email_from or '',
                'business_type': req.company_type or 'other',
                'description': req.description or '',
            })
            req.write({'state': 'converted'})

    def action_cancel(self):
        self.write({'state': 'cancel'})
