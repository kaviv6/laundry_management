/** @odoo-module **/
/* global Cashfree */

import { loadJS } from '@web/core/assets';
import { PaymentForm } from '@payment/interactions/payment_form';
import { patch } from '@web/core/utils/patch';

patch(PaymentForm.prototype, {

    // #=== DOM MANIPULATION ===#

    /**
     * Update the payment context to set the flow to 'direct'.
     *
     * @override method from @payment/js/payment_form
     * @private
     * @param {number} providerId - The id of the selected payment option's provider.
     * @param {string} providerCode - The code of the selected payment option's provider.
     * @param {number} paymentOptionId - The id of the selected payment option
     * @param {string} paymentMethodCode - The code of the selected payment method, if any.
     * @param {string} flow - The online payment flow of the selected payment option.
     * @return {void}
     */
    async _prepareInlineForm(providerId, providerCode, paymentOptionId, paymentMethodCode, flow) {
        if (providerCode !== 'cashfree') {
            await super._prepareInlineForm(...arguments);
            return;
        }

        // Overwrite the flow of the select payment method.
        this._setPaymentFlow('direct');
    },

    // #=== PAYMENT FLOW ===#

    async _processDirectFlow(providerCode, paymentOptionId, paymentMethodCode, processingValues) {
        if (providerCode !== 'cashfree') {
            await super._processDirectFlow(...arguments);
            return;
        }
        await loadJS('https://sdk.cashfree.com/js/v3/cashfree.js');
        const cashfree = Cashfree({ mode: processingValues.txn_env });
        const cashfreeOptions = this._prepareCashFreeOptions(processingValues);
        cashfree.checkout(cashfreeOptions).then((result) => {
            if(result.paymentDetails){
                window.location = window.location.origin + '/payment/status';
            }
        });
    },
    /**
     * Prepare the options to init the Cashfree SDK Object.
     *
     * @param {object} processingValues - The processing values.
     * @return {object}
     */
    _prepareCashFreeOptions(processingValues) {
        return {
            paymentSessionId: processingValues.payment_session_Id,
            redirectTarget: "_modal",
        }
    },
});
