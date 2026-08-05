import logging
import time

import requests
from requests.auth import HTTPBasicAuth

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

RAZORPAY_API_BASE = 'https://api.razorpay.com/v1'

KEY_ID_PARAM = 'student_details.razorpay.key_id'
KEY_SECRET_PARAM = 'student_details.razorpay.key_secret'
WEBHOOK_SECRET_PARAM = 'student_details.razorpay.webhook_secret'

# Razorpay payment_link status -> our internal status
RAZORPAY_STATUS_MAP = {
    'created': 'created',
    'partially_paid': 'partial',
    'paid': 'paid',
    'cancelled': 'cancelled',
    'expired': 'expired',
}


class ResConfigSettingsRazorpay(models.TransientModel):
    _inherit = 'res.config.settings'

    razorpay_key_id = fields.Char(
        string='Razorpay Key ID', config_parameter=KEY_ID_PARAM,
    )
    razorpay_key_secret = fields.Char(
        string='Razorpay Key Secret', config_parameter=KEY_SECRET_PARAM,
    )
    razorpay_webhook_secret = fields.Char(
        string='Razorpay Webhook Secret', config_parameter=WEBHOOK_SECRET_PARAM,
        help="Set the same value as the 'Secret' when creating the webhook in the "
             "Razorpay Dashboard (Settings > Webhooks), pointed at "
             "<your-odoo-url>/razorpay/webhook, subscribed to the "
             "payment_link.paid and payment_link.partially_paid events.",
    )


class StudentFeePaymentRazorpay(models.Model):
    _inherit = 'student.fee.payment'

    payment_source = fields.Selection([
        ('manual', 'Manual'),
        ('razorpay', 'Razorpay Link'),
    ], string='Source', default='manual', required=True)

    razorpay_allow_partial = fields.Boolean(
        string='Allow Partial Payment',
        help="If enabled, the student can pay the link in more than one instalment.",
    )
    razorpay_payment_link_id = fields.Char(readonly=True, copy=False)
    razorpay_short_url = fields.Char(string='Payment Link', readonly=True, copy=False)
    razorpay_reference_id = fields.Char(readonly=True, copy=False)
    razorpay_status = fields.Selection([
        ('created', 'Link Created'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
    ], readonly=True, copy=False)
    razorpay_last_payment_id = fields.Char(readonly=True, copy=False)
    amount_received = fields.Float(
        string='Received via Razorpay ₹', digits=(10, 2),
        default=0.0, copy=False, readonly=True,
    )

    # ── config / http helpers ───────────────────────────────────────────
    @api.model
    def _get_razorpay_auth(self):
        icp = self.env['ir.config_parameter'].sudo()
        key_id = icp.get_param(KEY_ID_PARAM)
        key_secret = icp.get_param(KEY_SECRET_PARAM)
        if not key_id or not key_secret:
            raise UserError(_(
                "Razorpay Key ID / Key Secret are not configured "
                "(Students > Configuration > Registration Settings)."
            ))
        return HTTPBasicAuth(key_id, key_secret)

    def _razorpay_request(self, method, path, **kwargs):
        auth = self._get_razorpay_auth()
        try:
            resp = requests.request(
                method, f"{RAZORPAY_API_BASE}{path}", auth=auth, timeout=20, **kwargs)
        except requests.RequestException as exc:
            raise UserError(_("Could not reach Razorpay: %s") % exc)
        try:
            data = resp.json()
        except ValueError:
            resp.raise_for_status()
            raise UserError(_("Unexpected response from Razorpay."))
        if resp.status_code >= 400:
            err = (data.get('error') or {}).get('description') or data
            raise UserError(_("Razorpay error: %s") % err)
        return data

    def _normalize_contact(self):
        self.ensure_one()
        phone = (self.student_id.phone or '').strip()
        digits = ''.join(ch for ch in phone if ch.isdigit())
        if not digits:
            return False
        if len(digits) == 10:
            return f"+91{digits}"
        if digits.startswith('91') and len(digits) == 12:
            return f"+{digits}"
        return f"+{digits}"

    # ── create / refresh a payment link ─────────────────────────────────
    def action_generate_razorpay_link(self):
        self.ensure_one()
        if self.amount <= 0:
            raise UserError(_("Enter an amount before generating a payment link."))
        if self.razorpay_status in ('created', 'partial'):
            raise UserError(_(
                "A Razorpay link is already active for this payment. "
                "Cancel/expire it in Razorpay first, or refresh its status."
            ))

        contact = self._normalize_contact()
        email = self.student_id.email or False
        reference_id = f"ODOO-FP-{self.id}-{int(time.time())}"

        payload = {
            'amount': int(round(self.amount * 100)),
            'currency': 'INR',
            'accept_partial': bool(self.razorpay_allow_partial),
            'description': f"Fee payment - {self.enrollment_id.display_name or self.student_id.name}",
            'customer': {
                'name': self.student_id.name or '',
                'contact': contact or '',
                'email': email or '',
            },
            'notify': {
                'sms': bool(contact),
                'email': bool(email),
            },
            'reminder_enable': True,
            'reference_id': reference_id,
            'notes': {
                'odoo_payment_id': str(self.id),
                'odoo_enrollment_id': str(self.enrollment_id.id),
                'odoo_student_id': str(self.student_id.id),
            },
        }
        result = self._razorpay_request('POST', '/payment_links', json=payload)

        self.write({
            'payment_source': 'razorpay',
            'razorpay_payment_link_id': result.get('id'),
            'razorpay_short_url': result.get('short_url'),
            'razorpay_reference_id': reference_id,
            'razorpay_status': RAZORPAY_STATUS_MAP.get(result.get('status'), 'created'),
        })

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Payment Link Ready"),
                'message': result.get('short_url'),
                'sticky': True,
                'type': 'success',
            },
        }

    def action_refresh_razorpay_status(self):
        self.ensure_one()
        if not self.razorpay_payment_link_id:
            raise UserError(_("No Razorpay link has been generated for this payment yet."))
        result = self._razorpay_request(
            'GET', f"/payment_links/{self.razorpay_payment_link_id}")
        self._apply_razorpay_link_data(result)

    def _apply_razorpay_link_data(self, data):
        """Apply a Razorpay payment_link entity payload (from API or webhook)."""
        self.ensure_one()
        status = RAZORPAY_STATUS_MAP.get(data.get('status'), self.razorpay_status)
        amount_paid = (data.get('amount_paid') or 0) / 100.0
        vals = {
            'razorpay_status': status,
            'amount_received': amount_paid,
        }
        payments = data.get('payments') or []
        captured = [p for p in payments if p.get('status') == 'captured']
        if captured:
            vals['razorpay_last_payment_id'] = captured[-1].get('payment_id')
        if status == 'paid' and not self.payment_date:
            vals['payment_date'] = fields.Date.today()
        self.write(vals)

    # ── manual fallback ──────────────────────────────────────────────────
    def action_mark_paid_manually(self):
        self.ensure_one()
        if self.payment_source != 'razorpay':
            raise UserError(_("This is only for Razorpay-linked payments."))
        vals = {
            'razorpay_status': 'paid',
            'amount_received': self.amount,
        }
        if not self.payment_date:
            vals['payment_date'] = fields.Date.today()
        note = _("Manually confirmed paid (checked in Razorpay dashboard).")
        vals['remarks'] = f"{self.remarks} — {note}" if self.remarks else note
        self.write(vals)


class StudentEnrollmentRazorpay(models.Model):
    _inherit = 'student.enrollment'

    def action_generate_payment_link(self):
        self.ensure_one()
        if self.due_amount <= 0:
            raise UserError(_("There is nothing due on this enrollment."))
        payment = self.env['student.fee.payment'].create({
            'enrollment_id': self.id,
            'amount': self.due_amount,
            'payment_source': 'razorpay',
        })
        return payment.action_generate_razorpay_link()

    @api.depends(
        'payment_ids.amount', 'payment_ids.amount_received',
        'payment_ids.payment_source', 'payment_ids.razorpay_status',
        'total_fee',
    )
    def _compute_due(self):
        for rec in self:
            paid = sum(
                p.amount if p.payment_source == 'manual' else p.amount_received
                for p in rec.payment_ids
            )
            rec.paid_amount = round(paid, 2)
            rec.due_amount = round(rec.total_fee - paid, 2)
            if paid <= 0:
                rec.payment_status = 'unpaid'
            elif paid >= rec.total_fee:
                rec.payment_status = 'paid'
            else:
                rec.payment_status = 'partial'
