import base64
import json as json_lib
import logging
import time

import requests as http_req

from odoo import models

_logger = logging.getLogger(__name__)

FCM_ENDPOINT = 'https://fcm.googleapis.com/v1/projects/{project_id}/messages:send'
GOOGLE_TOKEN_URL = 'https://oauth2.googleapis.com/token'
FCM_SCOPE = 'https://www.googleapis.com/auth/firebase.messaging'


class LaundryPushService(models.AbstractModel):
    """FCM v1 push notification sender. Singleton-style — call via self.env['laundry.push.service']."""
    _name = 'laundry.push.service'
    _description = 'Laundry FCM Push Notification Service'

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _get_fcm_creds(self):
        """Per-company credentials (Settings → Laundry Management →
        Push Notifications) — not a global ir.config_parameter, since a
        multi-company setup can run a different Firebase project per
        branch/company."""
        company = self.env.company
        return (
            company.laundry_fcm_project_id or '',
            company.laundry_fcm_service_account_json or '',
        )

    # ------------------------------------------------------------------
    # OAuth2 via service account (no external library needed)
    # ------------------------------------------------------------------

    def _get_fcm_access_token(self, sa_json_str):
        """Build a signed JWT and exchange it for a short-lived OAuth2 access token."""
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding as asym_padding

        sa = json_lib.loads(sa_json_str)
        now = int(time.time())

        header = base64.urlsafe_b64encode(
            json_lib.dumps({'alg': 'RS256', 'typ': 'JWT'}).encode()
        ).rstrip(b'=')
        payload = base64.urlsafe_b64encode(
            json_lib.dumps({
                'iss': sa['client_email'],
                'scope': FCM_SCOPE,
                'aud': GOOGLE_TOKEN_URL,
                'iat': now,
                'exp': now + 3600,
            }).encode()
        ).rstrip(b'=')

        signing_input = header + b'.' + payload
        private_key = serialization.load_pem_private_key(sa['private_key'].encode(), password=None)
        signature = private_key.sign(signing_input, asym_padding.PKCS1v15(), hashes.SHA256())
        jwt_token = signing_input + b'.' + base64.urlsafe_b64encode(signature).rstrip(b'=')

        resp = http_req.post(
            GOOGLE_TOKEN_URL,
            data={
                'grant_type': 'urn:ietf:params:oauth:grant-type:jwt-bearer',
                'assertion': jwt_token.decode(),
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()['access_token']

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def _send_push_notification(self, fcm_token, title, body, data=None):
        """Send a single FCM v1 notification. Returns True on success, False on skip/error."""
        project_id, sa_json = self._get_fcm_creds()
        if not project_id or not sa_json:
            _logger.debug('FCM not configured — skipping push. Set it in Settings → Laundry Management → Configuration → Settings.')
            return False

        try:
            access_token = self._get_fcm_access_token(sa_json)
        except Exception as exc:
            _logger.warning('FCM: failed to obtain access token: %s', exc)
            return False

        message = {
            'message': {
                'token': fcm_token,
                'notification': {'title': title, 'body': body},
                'data': {k: str(v) for k, v in (data or {}).items()},
                'android': {'priority': 'high'},
                'apns': {'headers': {'apns-priority': '10'}},
            }
        }
        try:
            resp = http_req.post(
                FCM_ENDPOINT.format(project_id=project_id),
                json=message,
                headers={
                    'Authorization': f'Bearer {access_token}',
                    'Content-Type': 'application/json',
                },
                timeout=10,
            )
            resp.raise_for_status()
            _logger.info('FCM: sent "%s" to token …%s', title, fcm_token[-6:])
            return True
        except Exception as exc:
            _logger.warning('FCM: send failed (token …%s): %s', fcm_token[-6:], exc)
            return False

    def _notify_users(self, users, title, body, data=None):
        """Send push to every user in the recordset that has a registered FCM token."""
        for user in users:
            if user.push_token:
                self._send_push_notification(user.push_token, title, body, data)


# ------------------------------------------------------------------
# Laundry Order — state-change hook
# ------------------------------------------------------------------

_ORDER_MESSAGES = {
    'order': (
        'Order Confirmed',
        'Your laundry order {name} has been confirmed and is being processed.',
    ),
    'invoiced': (
        'Invoice Ready',
        'Your invoice for order {name} is ready. Total: Rs.{total:.0f}',
    ),
    'cancel': (
        'Order Cancelled',
        'Your laundry order {name} has been cancelled.',
    ),
}


class LaundryOrder(models.Model):
    _inherit = 'laundry.order'

    def write(self, vals):
        if 'state' in vals:
            old_states = {rec.id: rec.state for rec in self}
        result = super().write(vals)
        if 'state' in vals:
            for rec in self:
                if old_states.get(rec.id) != rec.state:
                    rec._push_order_state_change()
        return result

    def _push_order_state_change(self):
        pair = _ORDER_MESSAGES.get(self.state)
        if not pair:
            return
        title, body_tmpl = pair
        body = body_tmpl.format(name=self.name or '', total=self.total_amount or 0)

        users = self.env['res.users'].sudo().search([
            ('partner_id', '=', self.partner_id.id),
            ('push_token', '!=', False),
        ])
        self.env['laundry.push.service']._notify_users(
            users, title, body,
            data={'type': 'order', 'order_id': str(self.id), 'state': self.state},
        )


# ------------------------------------------------------------------
# Laundry Pickup Request — state-change hook
# ------------------------------------------------------------------

class LaundryPickupRequest(models.Model):
    _inherit = 'laundry.pickup.request'

    def write(self, vals):
        if 'state' in vals:
            old_states = {rec.id: rec.state for rec in self}
        result = super().write(vals)
        if 'state' in vals:
            for rec in self:
                if old_states.get(rec.id) != rec.state:
                    rec._push_pickup_state_change()
        return result

    def _push_pickup_state_change(self):
        schedule_str = (
            self.schedule_date.strftime('%d %b, %I:%M %p') if self.schedule_date else ''
        )
        push_svc = self.env['laundry.push.service']
        data = {'type': 'pickup', 'pickup_id': str(self.id), 'state': self.state}

        # Messages for the customer
        customer_msgs = {
            'scheduled': (
                'Pickup Scheduled',
                f'Your laundry pickup is scheduled for {schedule_str}. Our rider will arrive soon.',
            ),
            'picked': (
                'Laundry Picked Up',
                "Your laundry has been collected by our rider. We'll notify you when it's ready.",
            ),
            'delivered': (
                'Laundry Delivered',
                'Your laundry has been delivered. Thank you for using our service!',
            ),
            'cancel': (
                'Pickup Cancelled',
                f'Your pickup request {self.name} has been cancelled.',
            ),
        }
        pair = customer_msgs.get(self.state)
        if pair:
            title, body = pair
            customers = self.env['res.users'].sudo().search([
                ('partner_id', '=', self.partner_id.id),
                ('push_token', '!=', False),
            ])
            push_svc._notify_users(customers, title, body, data)

        # Notify rider when a new pickup is assigned to them
        if (
            self.state == 'scheduled'
            and self.laundry_person_id
            and self.laundry_person_id.push_token
        ):
            push_svc._send_push_notification(
                self.laundry_person_id.push_token,
                'New Pickup Assigned',
                f'Pickup {self.name} is scheduled for {schedule_str}. Tap to view details.',
                data,
            )
