from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .attendance_whatsapp import (
    DEFAULT_ABSENT_MSG, DEFAULT_LATE_MSG, DEFAULT_LOW_MSG, PARAM_PREFIX)

REG_PREFIX_KEY = 'student_details.registration.prefix'


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    student_registration_prefix = fields.Char(
        string='Registration Prefix Letters',
        config_parameter=REG_PREFIX_KEY,
        default='ANJ',
    )
    student_registration_next_number = fields.Integer(
        string='Next Serial Number',
        compute='_compute_student_registration_next_number',
        inverse='_inverse_student_registration_next_number',
        help='Serial counter continues across financial years. '
             'Only the year segment in the number changes each April.',
    )

    # ── Attendance WhatsApp alerts ───────────────────────────────────────────
    att_wa_enabled = fields.Boolean(
        string="Enable Attendance WhatsApp Alerts", config_parameter=PARAM_PREFIX + 'enabled')
    att_wa_provider = fields.Selection(
        [('gateway', 'WhatsApp Gateway (HTTP API)'), ('meta', 'Meta WhatsApp Cloud API')],
        string="Provider", default='gateway', config_parameter=PARAM_PREFIX + 'provider')
    att_wa_gateway_url = fields.Char(
        string="Gateway URL", config_parameter=PARAM_PREFIX + 'gateway_url',
        help="POST endpoint. Receives JSON {number, phone, message}.")
    att_wa_gateway_token = fields.Char(
        string="Gateway Token", config_parameter=PARAM_PREFIX + 'gateway_token')
    att_wa_meta_phone_id = fields.Char(
        string="Phone Number ID", config_parameter=PARAM_PREFIX + 'meta_phone_id')
    att_wa_meta_token = fields.Char(
        string="Access Token", config_parameter=PARAM_PREFIX + 'meta_token')
    att_wa_meta_api_version = fields.Char(
        string="Graph API Version", default='v21.0',
        config_parameter=PARAM_PREFIX + 'meta_api_version')
    att_wa_use_template = fields.Boolean(
        string="Use Approved Templates (Meta)", config_parameter=PARAM_PREFIX + 'use_template',
        help="Required by Meta to message parents outside the 24-hour window. "
             "Absent/Late template parameters: {{1}} student, {{2}} date, {{3}} batch, "
             "{{4}} session. Low attendance: {{1}} student, {{2}} batch, {{3}} %, {{4}} required %.")
    att_wa_template_lang = fields.Char(
        string="Template Language", default='en',
        config_parameter=PARAM_PREFIX + 'template_lang')
    att_wa_absent_template = fields.Char(
        string="Absent Template Name", config_parameter=PARAM_PREFIX + 'absent_template')
    att_wa_late_template = fields.Char(
        string="Late Template Name", config_parameter=PARAM_PREFIX + 'late_template')
    att_wa_low_template = fields.Char(
        string="Low Attendance Template Name", config_parameter=PARAM_PREFIX + 'low_template')
    att_wa_notify_scope = fields.Selection(
        [('absent', 'Absentees only'), ('absent_late', 'Absentees and latecomers')],
        string="Send Alerts For", default='absent',
        config_parameter=PARAM_PREFIX + 'notify_scope')
    att_wa_low_threshold = fields.Float(
        string="Minimum Attendance %", default=75.0,
        config_parameter=PARAM_PREFIX + 'low_threshold')
    att_wa_country_code = fields.Char(
        string="Default Country Code", default='91',
        config_parameter=PARAM_PREFIX + 'country_code')
    att_wa_institute_name = fields.Char(
        string="Name Shown in Messages", config_parameter=PARAM_PREFIX + 'institute_name',
        help="Defaults to the company name.")
    att_wa_absent_message = fields.Text(
        string="Absent Message", default=DEFAULT_ABSENT_MSG,
        config_parameter=PARAM_PREFIX + 'absent_message')
    att_wa_late_message = fields.Text(
        string="Late Message", default=DEFAULT_LATE_MSG,
        config_parameter=PARAM_PREFIX + 'late_message')
    att_wa_low_message = fields.Text(
        string="Low Attendance Message", default=DEFAULT_LOW_MSG,
        config_parameter=PARAM_PREFIX + 'low_message')
    att_wa_test_number = fields.Char(string="Test Number")

    def action_att_wa_test(self):
        """Send a test message using the values currently in the form (unsaved)."""
        self.ensure_one()
        Log = self.env['otm.attendance.whatsapp.log']
        cfg = Log._get_config({
            'enabled': True,
            'provider': self.att_wa_provider or 'gateway',
            'gateway_url': self.att_wa_gateway_url or '',
            'gateway_token': self.att_wa_gateway_token or '',
            'meta_phone_id': self.att_wa_meta_phone_id or '',
            'meta_token': self.att_wa_meta_token or '',
            'meta_api_version': self.att_wa_meta_api_version or 'v21.0',
            'country_code': self.att_wa_country_code or '91',
        })
        number = Log._normalize_number(self.att_wa_test_number, cfg['country_code'])
        if not number:
            raise UserError(_("Enter a valid test WhatsApp number first."))
        log = Log.sudo().create({
            'message_type': 'test', 'number': number, 'state': 'queued',
            'message': _("Test message from %s attendance system.", cfg['institute_name']),
        })
        try:
            log._dispatch(cfg)
            log.write({'state': 'sent', 'sent_on': fields.Datetime.now(), 'retries': 1})
            msg, kind = _("Test message sent to %s.", number), 'success'
        except Exception as exc:  # noqa: BLE001
            log.write({'state': 'failed', 'error': str(exc)[:500], 'retries': 1})
            msg, kind = _("Test failed: %s", str(exc)[:200]), 'danger'
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _("WhatsApp test"), 'message': msg,
                           'type': kind, 'sticky': kind == 'danger'}}

    def _get_registration_sequence(self):
        return self.env['ir.sequence'].sudo().search([
            ('code', '=', 'student.registration.serial'),
            '|', ('company_id', '=', False), ('company_id', '=', self.env.company.id),
        ], order='company_id desc', limit=1)

    @api.depends('company_id')
    def _compute_student_registration_next_number(self):
        for settings in self:
            sequence = settings._get_registration_sequence()
            settings.student_registration_next_number = (
                getattr(sequence, 'number_next_actual', None) or sequence.number_next
            ) if sequence else 1

    def _inverse_student_registration_next_number(self):
        for settings in self:
            sequence = settings._get_registration_sequence()
            if sequence and settings.student_registration_next_number:
                sequence.sudo().number_next = settings.student_registration_next_number

    def action_load_demo_data(self):
        self.env['student.demo.data'].load()
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': 'Demo data loaded', 'type': 'success', 'sticky': True,
            'message': 'Login: demo.<role>@demo.otomater.com / Demo@1234 (see the demo guide).'}}

    def action_remove_demo_data(self):
        archived = self.env['student.demo.data'].remove()
        msg = 'All demo records removed.'
        if archived:
            msg += ' Archived (have history): ' + ', '.join(archived[:6])
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': 'Demo data removed', 'message': msg, 'type': 'warning', 'sticky': True}}
