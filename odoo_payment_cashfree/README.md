# CashFree

## Technical Details

API: [CashFree Create Payment API](https://www.cashfree.com/docs/api-reference/payments/latest/orders/createt)
Payment Checkout: [CashFree Payment Checkout](https://www.cashfree.com/docs/payments/online/web/redirect)

## Supported Features

- Direct Payment Flow
- Refund Flow
- Webhook Notification

## Testing Instructions

Testing Credentials: [https://www.cashfree.com/docs/partners/embedded/integration/gateway-sandbox-environment#sandbox-environment-for-embedded-payments-partners](https://www.cashfree.com/docs/partners/embedded/integration/gateway-sandbox-environment#sandbox-environment-for-embedded-payments-partners)

### Visa Debit Card

**Card Number**: `4706 1312 1121 2123`

**Card Expiry**: `03/2028`

**Card CVV**: `123`

**Verification OTP**: `111000`

### UPI

Scan the QR with any QR scanner and a link will appear open the link any browser and choose the status `SUCCESS`, `USER_DROPPED`, `FAILED` or `PENDING`.

OR

**UPI ID**: `testsuccess@gocash`
