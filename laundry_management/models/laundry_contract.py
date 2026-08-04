import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

class LaundryContract(models.Model):
    _name = 'laundry.contract'
    _description = 'Laundry Contract'
    _order = 'name'

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
    pricelist_id = fields.Many2one(
        'laundry.pricelist', string='Pricelist',
        help='Pricelist applied to all orders for this contract customer'
    )
    description = fields.Text(string='Description')

    # Recurring order settings
    recurring_enabled = fields.Boolean(string='Recurring Orders', default=False)
    recurring_interval = fields.Selection([
        ('weekly', 'Weekly'),
        ('biweekly', 'Every 2 Weeks'),
        ('monthly', 'Monthly'),
    ], string='Frequency', default='monthly')
    recurring_next_date = fields.Date(string='Next Order Date')
    recurring_service_ids = fields.One2many(
        'laundry.contract.recurring.line', 'contract_id', string='Default Services'
    )

    order_ids = fields.One2many('laundry.order', 'contract_id', string='Orders', readonly=True)
    order_count = fields.Integer(compute='_compute_order_count', string='Orders')

    def _compute_order_count(self):
        for rec in self:
            rec.order_count = len(rec.order_ids)

    def action_view_orders(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Orders',
            'res_model': 'laundry.order',
            'view_mode': 'list,form',
            'domain': [('contract_id', '=', self.id)],
        }

    @api.model
    def cron_create_recurring_orders(self):
        """Daily cron: create a laundry order for each active B2B contract due today."""
        from datetime import timedelta
        today = fields.Date.today()
        due_contracts = self.search([
            ('recurring_enabled', '=', True),
            ('recurring_next_date', '<=', today),
            ('partner_id', '!=', False),
        ])
        admin = self.env.ref('base.user_admin')
        for contract in due_contracts:
            try:
                lines = []
                for svc_line in contract.recurring_service_ids:
                    lines.append((0, 0, {
                        'service_type_id': svc_line.service_type_id.id,
                        'qty': svc_line.qty,
                    }))
                if not lines:
                    continue
                self.env['laundry.order'].create({
                    'partner_id': contract.partner_id.id,
                    'laundry_person_id': admin.id,
                    'contract_id': contract.id,
                    'payment_method': 'cod',
                    'note': f'Auto-generated from contract {contract.name}',
                    'order_line_ids': lines,
                })
                # Advance next date
                if contract.recurring_interval == 'weekly':
                    next_date = today + timedelta(weeks=1)
                elif contract.recurring_interval == 'biweekly':
                    next_date = today + timedelta(weeks=2)
                else:
                    from dateutil.relativedelta import relativedelta
                    next_date = today + relativedelta(months=1)
                contract.recurring_next_date = next_date
            except Exception as e:
                _logger.error('Recurring order failed for contract %s: %s', contract.name, e)


class LaundryContractRecurringLine(models.Model):
    _name = 'laundry.contract.recurring.line'
    _description = 'Recurring Service Line'

    contract_id = fields.Many2one('laundry.contract', required=True, ondelete='cascade')
    service_type_id = fields.Many2one('service.type', string='Service Type', required=True)
    qty = fields.Integer(string='Qty', default=1)
