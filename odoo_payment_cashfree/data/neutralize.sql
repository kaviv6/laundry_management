-- disable CashFree payment provider
UPDATE payment_provider
   SET cashfree_client_id = NULL,
       cashfree_client_secret = NULL;
