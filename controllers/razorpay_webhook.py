import hashlib
import hmac
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

WEBHOOK_SECRET_PARAM = 'student_details.razorpay.webhook_secret'

HANDLED_EVENTS = ('payment_link.paid', 'payment_link.partially_paid')


class RazorpayWebhookController(http.Controller):

    @http.route('/razorpay/webhook', type='http', auth='public',
                csrf=False, methods=['POST'], save_session=False)
    def razorpay_webhook(self, **kw):
        raw_body = request.httprequest.get_data()
        signature = request.httprequest.headers.get('X-Razorpay-Signature', '')

        env = request.env
        secret = env['ir.config_parameter'].sudo().get_param(WEBHOOK_SECRET_PARAM)
        if not secret:
            _logger.warning("Razorpay webhook received but no webhook secret configured.")
            return request.make_response('Webhook secret not configured', status=400)

        expected = hmac.new(
            secret.encode('utf-8'), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(expected, signature or ''):
            _logger.warning("Razorpay webhook signature mismatch.")
            return request.make_response('Invalid signature', status=400)

        try:
            body = json.loads(raw_body.decode('utf-8'))
        except ValueError:
            _logger.warning("Razorpay webhook: could not parse JSON body.")
            return request.make_response('Bad payload', status=400)

        event = body.get('event')
        if event not in HANDLED_EVENTS:
            # Acknowledge anything we don't act on so Razorpay stops retrying it.
            return request.make_response('OK', status=200)

        try:
            payload = body.get('payload', {})
            link_entity = (payload.get('payment_link') or {}).get('entity') or {}
            payment_entity = (payload.get('payment') or {}).get('entity') or {}
            link_id = link_entity.get('id')

            if not link_id:
                _logger.warning("Razorpay webhook: no payment_link id in payload.")
                return request.make_response('OK', status=200)

            Payment = env['student.fee.payment'].sudo()
            payment = Payment.search([
                ('razorpay_payment_link_id', '=', link_id),
            ], limit=1)
            if not payment:
                _logger.warning("Razorpay webhook: no fee.payment found for link %s", link_id)
                return request.make_response('OK', status=200)

            # link_entity has status/amount_paid; merge in the single payment
            # object from the event too, in case the link fetch elsewhere
            # hasn't picked it up yet.
            payments_list = list(link_entity.get('payments') or [])
            if payment_entity.get('id'):
                payments_list.append({
                    'payment_id': payment_entity.get('id'),
                    'status': payment_entity.get('status'),
                })
            link_entity['payments'] = payments_list

            payment._apply_razorpay_link_data(link_entity)
        except Exception:
            _logger.exception("Error processing Razorpay webhook")
            # Still return 200 — we've logged it; a 5xx would just cause
            # Razorpay to hammer retries for something a human needs to look at.
            return request.make_response('OK', status=200)

        return request.make_response('OK', status=200)
