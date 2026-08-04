import re

from odoo import api, fields, models


class LaundryServiceZone(models.Model):
    _name = 'laundry.service.zone'
    _description = 'Service Zone'
    _order = 'name'

    name = fields.Char(string='Zone Name', required=True)
    city = fields.Char(string='City', required=True, default='Rajkot')
    zip_codes = fields.Text(
        string='Serviceable Pin Codes',
        help='Enter one pin code per line, or comma-separated. e.g.\n360001\n360002\n360003',
    )
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes')

    pickup_count = fields.Integer(compute='_compute_pickup_count', string='Pickups')

    def _get_zip_list(self):
        self.ensure_one()
        if not self.zip_codes:
            return []
        return [z.strip() for z in re.split(r'[,\n\r]+', self.zip_codes) if z.strip()]

    def _compute_pickup_count(self):
        for zone in self:
            zips = zone._get_zip_list()
            zone.pickup_count = self.env['laundry.pickup.request'].search_count(
                [('zip', 'in', zips)]
            ) if zips else 0

    @api.model
    def find_zone_for_zip(self, zip_code):
        """Return the active zone matching this pin code, or False."""
        if not zip_code:
            return False
        zip_code = zip_code.strip()
        for zone in self.search([('active', '=', True)]):
            if zip_code in zone._get_zip_list():
                return zone
        return False

    @api.model
    def is_serviceable(self, zip_code, city=None):
        """
        Return True if we can serve this location.
        Checks zip first; if zip is missing, falls back to city name match.
        """
        if zip_code and zip_code.strip():
            return bool(self.find_zone_for_zip(zip_code.strip()))
        if city:
            active_cities = self.search([('active', '=', True)]).mapped('city')
            return any(city.strip().lower() == c.lower() for c in active_cities)
        return False
