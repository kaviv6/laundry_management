from odoo import models, fields, api

class LaundryContract(models.Model):
    _name = 'laundry.contract'
    _description = 'Laundry Contract'

    name = fields.Char(string='Customer Name', required=True)
    partner_id = fields.Many2one('res.partner', string='Customer')
    mobile = fields.Char(string='Mobile No', required=True)
    email = fields.Char(string='Email')
    business_type = fields.Selection([
        ('hotel', 'Hotel'),
        ('restaurant', 'Restaurant'),
        ('hostel', 'Hostel'),
        ('other', 'Other')
    ], string='Business Type', required=True)
    description = fields.Text(string='Description')
