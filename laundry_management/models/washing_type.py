from odoo import fields, models


class WashingType(models.Model):
    """Washing types generating model"""
    _name = 'washing.type'
    _description = "Washing TYpe"

    name = fields.Char(string='Name', required=True,
                       help='Name of Washing type.')
    assigned_person_id = fields.Many2one('res.users',
                                         string='Assigned Person',
                                         required=True,
                                         help="Name of assigned person")
    amount = fields.Float(string='Service Charge', required=True,
                          help='Service charge of this type')
