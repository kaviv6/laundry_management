# Part of Odoo. See LICENSE file for full copyright and licensing details.

import json
import logging
import pprint
import re

from odoo import _, api, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.payment import utils as payment_utils
from odoo.addons.odoo_payment_cashfree import const

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    @api.model
    def _compute_reference(self, provider_code, prefix=None, separator='-', **kwargs):
        """ Override of `payment` to ensure that cashfree' requirements for references are satisfied.

        cashfree' requirements for transaction are as follows:
        - References can only be made of alphanumeric characters and/or '-' and '_'.
          The prefix is generated with 'tx' as default. This prevents the prefix from being
          generated based on document names that may contain non-allowed characters
          (eg: INV/2020/...).

        :param str provider_code: The code of the provider handling the transaction.
        :param str prefix: The custom prefix used to compute the full reference.
        :param str separator: The custom separator used to separate the prefix from the suffix.
        :return: The unique reference for the transaction.
        :rtype: str
        """
        if provider_code == 'cashfree':
            prefix = payment_utils.singularize_reference_prefix()
        return super()._compute_reference(provider_code, prefix=prefix, separator=separator, **kwargs)

    def _get_specific_processing_values(self, processing_values):
        if self.provider_code != 'cashfree':
            return super()._get_specific_processing_values(processing_values)
        order_data = self._cashfree_create_payment_order()
        return {
            'order_id': order_data.get('order_id'),
            'payment_session_Id': order_data.get('payment_session_id'),
            'txn_env': 'sandbox' if self.provider_id.state == 'test' else 'production'
        }

    def _cashfree_create_payment_order(self):
        """ Create and return an Order object to initiate the payment.

        :return: The created Order.
        :rtype: dict
        """
        payload = self._cashfree_prepare_order_payload()
        _logger.info(
            "Sending request for transaction with reference %s:\n%s",
            self.reference, pprint.pformat(payload)
        )
        order_data = self.provider_id._send_api_request('POST', '/orders', data=json.dumps(payload))
        if not order_data:
            raise UserError(_("Something went wrong while creating the Cashfree order. Please try again."))
        _logger.info(
            "Response of request for transaction with reference %s:\n%s",
            self.reference, pprint.pformat(order_data)
        )
        return order_data

    def _cashfree_prepare_order_payload(self):
        """ Prepare the payload for the order request based on the transaction values.

        :return: The request payload.
        :rtype: dict
        """
        pm_code = (self.payment_method_id.primary_payment_method_id or self.payment_method_id).code
        cashfree_pm_code = const.PAYMENT_METHOD_CODES_MAPPING[pm_code]
        formatted_phone_number = re.sub(r'[^0-9+]', '', self.partner_phone) if self.partner_phone else ''
        payload = {
            'order_id': self.reference,
            'order_amount': str(self.amount),
            'order_currency': self.currency_id.name,
            'customer_details': {
                'customer_id': 'cf' + str(self.partner_id.id),  # Prefix 'cf' to ensure customer_id contains at least 3 alphanumeric characters as required by Cashfree
                'customer_email': self.partner_email or '',
                'customer_phone': formatted_phone_number
            },
            'order_meta': {
                'payment_methods': cashfree_pm_code,
            }
        }
        return payload

    def _search_by_reference(self, provider_code, payment_data):
        """ Override of `payment` to find the transaction based on cashfree data.

        :param str provider_code: The code of the provider that handled the transaction
        :param dict payment_data: The normalized notification data sent by the provider
        :return: The transaction if found
        :rtype: recordset of `payment.transaction`
        :raise: ValidationError if the data match no transaction
        """
        if provider_code != 'cashfree':
            return super()._search_by_reference(provider_code, payment_data)
        entity_type = payment_data.get('entity_type', 'payment')
        data = payment_data.get('data', {})

        if entity_type == 'payment':
            order = data.get('order', {})
            reference = order.get('order_id', '')
            if not reference:
                raise ValidationError(_("CashFree: Received data with missing reference."))
            tx = self.search([('reference', '=', reference), ('provider_code', '=', 'cashfree')], limit=1)
        elif entity_type == 'refund':
            refund = data.get('refund', {})
            refund_id = refund.get('refund_id')
            if not refund_id:
                _logger.error("Cashfree: Missing refund_id in refund data: %s", payment_data)
                raise ValidationError(_("Cashfree: Missing refund_id in refund data."))
            tx = self.search([('reference', '=', refund_id), ('provider_code', '=', 'cashfree')], limit=1)
        else:
            _logger.warning("Received data with missing merchant reference")
            tx = self

        if not tx:
            raise ValidationError(_("Cashfree: No transaction found matching reference %s.", reference))
        return tx

    def _extract_amount_data(self, payment_data):
        """Override of payment to extract the amount and currency from the payment data."""
        if self.provider_code != 'cashfree':
            return super()._extract_amount_data(payment_data)

        data = payment_data.get('data', {})
        webhook_type = payment_data.get('type', '')

        order = data.get('order', {}) if webhook_type == 'PAYMENT_SUCCESS_WEBHOOK' else data.get('refund', {})
        if webhook_type == 'PAYMENT_SUCCESS_WEBHOOK':
            order = data.get('order', {})
            return {
                'amount': order.get('order_amount', None),
                'currency_code': order.get('order_currency', ''),
            }
        elif webhook_type == 'REFUND_STATUS_WEBHOOK':
            refund = data.get('refund', {})
            return {
                'amount': refund.get('refund_amount', None),
                'currency_code': refund.get('refund_currency', ''),
            }

    def _apply_updates(self, payment_data):
        if self.provider_code != 'cashfree':
            return super()._apply_updates(payment_data)
        entity_type = payment_data.get('entity_type', 'payment')
        data = payment_data.get('data', {})

        # Update the provider reference.
        entity_id = data.get(entity_type, {}).get('cf_payment_id', '') if entity_type == 'payment' else data.get(entity_type, {}).get('cf_refund_id', '')

        allowed_to_modify = self.state not in ('done', 'authorized')
        if allowed_to_modify:
            self.provider_reference = entity_id

        # Update the payment method.
        payment_method_type = data.get('payment', {}).get('payment_group', '')
        payment_method = self.env['payment.method']._get_from_code(
            payment_method_type, mapping=const.PAYMENT_METHODS_MAPPING
        )
        if allowed_to_modify and payment_method:
            self.payment_method_id = payment_method

        # Update the payment state.
        entity_status = data.get('payment', {}).get('payment_status', '') if entity_type == "payment" else data.get('refund', {}).get('refund_status', '')

        if not entity_status:
            self._set_error(_("Received data with missing status."))

        if entity_status in const.PAYMENT_STATUS_MAPPING['done']:
            self._set_done()
            if self.operation == 'refund':
                self.env.ref('payment.cron_post_process_payment_tx')._trigger()
        elif entity_status in const.PAYMENT_STATUS_MAPPING['cancel']:
            self._set_canceled()
        elif entity_status in const.RESULT_CODES_MAPPING['pending']:
            self._set_pending()
        elif entity_status in const.PAYMENT_STATUS_MAPPING['error']:
            self._set_error(_("The transaction could not be processed due to an error. Please try again later."))
        else:
            _logger.warning(
                "Received data for transaction with reference %s with invalid payment status: %s",
                self.reference, entity_status
            )
            self._set_error(
                "CashFree: " + _("Received data with invalid status: %s", entity_status)
            )

    def _send_refund_request(self):
        """ Override of `payment` to send a refund request to cashfree.

        Note: self.ensure_one()

        :param float amount_to_refund: The amount to refund.
        :return: The refund transaction created to process the refund request.
        :rtype: recordset of `payment.transaction`
        """
        if self.provider_code != 'cashfree':
            return super()._send_refund_request()

        payload = {
            "refund_amount": -self.amount,
            "refund_id": self.reference,
        }
        _logger.info(
            "Payload of request for transaction with reference %s:\n%s",
            self.reference, pprint.pformat(payload)
        )
        end_point = f"/orders/{self.source_transaction_id.reference}/refunds"
        response_content = self.provider_id._send_api_request('POST', end_point, data=json.dumps(payload))
        _logger.info(
            "Response of '/payments/v2/refund' request for transaction with reference %s:\n%s",
            self.reference, pprint.pformat(response_content)
        )
        response_content.update(entity_type='refund')
