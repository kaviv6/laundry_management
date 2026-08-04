import random
import string

from odoo import api, fields, models, _


class LaundryGarment(models.Model):
    _name = 'laundry.garment'
    _description = 'Laundry Garment'
    _order = 'order_id desc, id desc'
    _inherit = ['mail.thread']

    name = fields.Char(string='Garment Label', copy=False, readonly=True)
    barcode = fields.Char(string='Barcode', copy=False, readonly=True, index=True)

    order_id = fields.Many2one('laundry.order', string='Order', ondelete='cascade', required=True)
    partner_id = fields.Many2one(related='order_id.partner_id', store=True, string='Customer', readonly=True)
    service_type_id = fields.Many2one('service.type', string='Service Type', required=True)
    qty = fields.Integer(string='Pieces', default=1)
    notes = fields.Text(string='Notes')

    state = fields.Selection([
        ('received', 'Received'),
        ('cleaning', 'In Cleaning'),
        ('ready', 'Ready'),
        ('delivered', 'Delivered'),
    ], string='Status', default='received', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('barcode'):
                vals['barcode'] = self._generate_barcode()
            if not vals.get('name'):
                vals['name'] = f"GRM-{vals['barcode']}"
        return super().create(vals_list)

    @staticmethod
    def _generate_barcode():
        prefix = 'LG'
        suffix = ''.join(random.choices(string.digits, k=8))
        return f"{prefix}{suffix}"

    def action_cleaning(self):
        self.write({'state': 'cleaning'})

    def action_ready(self):
        self.write({'state': 'ready'})

    def action_delivered(self):
        self.write({'state': 'delivered'})

    def action_print_label(self):
        return self.env.ref('laundry_management.action_report_garment_label').report_action(self)
