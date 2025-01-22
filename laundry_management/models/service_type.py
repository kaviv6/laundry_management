from odoo import fields, models


class ServiceType(models.Model):
    """Washing types generating model"""
    _name = 'service.type'
    _description = "Service Type"

    name = fields.Char(string='Name', required=True,
                       help='Name of Service type.')
    assigned_person_id = fields.Many2one('res.users',
                                         string='Assigned Person',
                                         required=True,
                                         help="Name of assigned person")
    amount = fields.Float(string='Service Charge', required=True,
                          help='Service charge of this type')
