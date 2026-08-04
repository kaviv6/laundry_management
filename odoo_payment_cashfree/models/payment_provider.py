# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import base64
import hashlib
import hmac

from odoo import fields, models
from odoo.tools.urls import urljoin

from odoo.addons.odoo_payment_cashfree import const

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('cashfree', "CashFree")], ondelete={'cashfree': 'set default'}
    )

    cashfree_client_id = fields.Char(
        string="Cashfree Client Id",
        required_if_provider='cashfree',
        copy=False
    )

    cashfree_client_secret = fields.Char(
        string="CashFree Client Secret",
        required_if_provider='cashfree',
        groups='base.group_system',
        copy=False
    )

    # === COMPUTE METHODS === #

    def _compute_feature_support_fields(self):
        """ Override of `payment` to enable additional features. """
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == 'cashfree').update({
            'support_refund': 'partial',
        })

    # === BUSINESS METHODS - PAYMENT FLOW === #

    def _get_supported_currencies(self):
        """ Override of `payment` to return the supported currencies. """
        supported_currencies = super()._get_supported_currencies()
        if self.code == 'cashfree':
            supported_currencies = supported_currencies.filtered(
                lambda c: c.name in const.SUPPORTED_CURRENCIES
            )
        return supported_currencies

    def _get_default_payment_method_codes(self):
        """ Override of `payment` to return the default payment method codes. """
        if self.code != 'cashfree':
            return super()._get_default_payment_method_codes()
        return const.DEFAULT_PAYMENT_METHOD_CODES

    # === REQUEST HELPERS === #

    def _build_request_url(self, endpoint, **kwargs):
        """ Override of `payment` to build the request URl. """
        if self.code != 'cashfree':
            return super()._build_request_url(endpoint, **kwargs)
        if self.state == 'enabled':
            api_url = 'https://api.cashfree.com/pg'
        else:
            api_url = 'https://sandbox.cashfree.com/pg'

        return urljoin(api_url, endpoint)

    def _build_request_headers(self, *args, **kwargs):
        """Override of `payment` to build the request headers."""
        if self.code != 'cashfree':
            return super()._build_request_headers(*args, **kwargs)
        return {
            'x-client-id': self.cashfree_client_id,
            'x-client-secret': self.cashfree_client_secret,
            'x-api-version': const.API_VERSION,  # SetupIntent requires a specific version.
            'Content-Type': 'application/json'
        }

    def _parse_response_error(self, response):
        """Override of `payment` to parse the error message."""
        if self.code != 'cashfree':
            return super()._parse_response_error(response)
        return response.json().get('message', '')

    def _cf_generate_digital_sign(self, raw_payload, timestamp):
        """ Generate the shasign for incoming or outgoing communications.

        :param dict raw_payload: The payload used to generate the signature
        :param str timestamp: The timestamp provided by Cashfree.
        :return: The shasign
        :rtype: str
        """
        if not timestamp or not raw_payload:
            _logger.error("Missing required webhook components.")
            return "Missing components", 400
        data = f"{timestamp}{raw_payload}"
        message = bytes(data, 'utf-8')
        secretkey = bytes(self.cashfree_client_secret, 'utf-8')
        expected_signature = base64.b64encode(
            hmac.new(secretkey, message, digestmod=hashlib.sha256).digest()
        ).decode("utf-8")

        if expected_signature:
            return expected_signature
