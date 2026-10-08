import requests

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
        [('meta', 'Meta WhatsApp Cloud API'), ('gateway', 'WhatsApp Gateway (HTTP API)')],
        string="Provider", default='meta', config_parameter=PARAM_PREFIX + 'provider')
    att_wa_gateway_url = fields.Char(
        string="Gateway URL", config_parameter=PARAM_PREFIX + 'gateway_url',
        help="POST endpoint. Receives JSON {number, phone, message}.")
    att_wa_gateway_token = fields.Char(
        string="Gateway Token", config_parameter=PARAM_PREFIX + 'gateway_token')
    att_wa_meta_phone_id = fields.Char(
        string="Phone Number ID", config_parameter=PARAM_PREFIX + 'meta_phone_id')
    att_wa_meta_token = fields.Char(
        string="Access Token", config_parameter=PARAM_PREFIX + 'meta_token')
    att_wa_meta_waba_id = fields.Char(
        string="WhatsApp Business Account ID", config_parameter=PARAM_PREFIX + 'meta_waba_id',
        help="Shown on Meta's WhatsApp > API Setup page. Needed only for the connection check.")
    att_wa_meta_api_version = fields.Char(
        string="Graph API Version", default='v21.0',
        config_parameter=PARAM_PREFIX + 'meta_api_version')
    att_wa_template_lang = fields.Char(
        string="Template language code", default='en',
        help="Must match the language of your templates in WhatsApp Manager (en, en_US, en_GB...).",
        config_parameter=PARAM_PREFIX + 'template_lang')
    att_wa_absent_template = fields.Char(
        string="Absent template",
        help="Variables: 1 student, 2 date, 3 batch, 4 session.", config_parameter=PARAM_PREFIX + 'absent_template')
    att_wa_late_template = fields.Char(
        string="Late template",
        help="Variables: 1 student, 2 date, 3 batch, 4 session.", config_parameter=PARAM_PREFIX + 'late_template')
    att_wa_low_template = fields.Char(
        string="Low attendance template",
        help="Variables: 1 student, 2 batch, 3 attendance %, 4 required %.", config_parameter=PARAM_PREFIX + 'low_template')
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
    att_wa_absent_message = fields.Char(
        string="Absent Message", default=DEFAULT_ABSENT_MSG,
        config_parameter=PARAM_PREFIX + 'absent_message')
    att_wa_late_message = fields.Char(
        string="Late Message", default=DEFAULT_LATE_MSG,
        config_parameter=PARAM_PREFIX + 'late_message')
    att_wa_low_message = fields.Char(
        string="Low Attendance Message", default=DEFAULT_LOW_MSG,
        config_parameter=PARAM_PREFIX + 'low_message')
    att_wa_test_number = fields.Char(string="Test Number")

    def _att_wa_form_config(self):
        Log = self.env['otm.attendance.whatsapp.log']
        return Log._get_config({
            'enabled': True,
            'provider': self.att_wa_provider or 'meta',
            'gateway_url': self.att_wa_gateway_url or '',
            'gateway_token': self.att_wa_gateway_token or '',
            'meta_phone_id': self.att_wa_meta_phone_id or '',
            'meta_token': self.att_wa_meta_token or '',
            'meta_waba_id': self.att_wa_meta_waba_id or '',
            'meta_api_version': self.att_wa_meta_api_version or 'v21.0',
            'template_lang': self.att_wa_template_lang or 'en',
            'absent_template': self.att_wa_absent_template or '',
            'late_template': self.att_wa_late_template or '',
            'low_template': self.att_wa_low_template or '',
            'country_code': self.att_wa_country_code or '91',
        })

    def action_att_wa_check_connection(self):
        """Verify token/phone ID and (with a Business Account ID) the template names."""
        self.ensure_one()
        cfg = self._att_wa_form_config()
        if not (cfg['meta_phone_id'] and cfg['meta_token']):
            raise UserError(_("Enter the Phone Number ID and Access token first."))
        base = 'https://graph.facebook.com/%s' % cfg['meta_api_version']
        headers = {'Authorization': 'Bearer %s' % cfg['meta_token']}
        try:
            resp = requests.get('%s/%s' % (base, cfg['meta_phone_id']), headers=headers, timeout=15,
                                params={'fields': 'display_phone_number,verified_name'},
                                allow_redirects=False)
            data = resp.json()
            if not resp.ok:
                raise UserError(_("Meta: %s", (data.get('error') or {}).get('message', resp.text)[:250]))
            msg = _("Connected: %(name)s (%(num)s).", name=data.get('verified_name', ''),
                    num=data.get('display_phone_number', ''))
            kind = 'success'
            names = [n for n in (cfg['absent_template'], cfg['late_template'], cfg['low_template']) if n]
            if cfg['meta_waba_id'] and names:
                tr = requests.get('%s/%s/message_templates' % (base, cfg['meta_waba_id']),
                                  headers=headers, timeout=15, allow_redirects=False,
                                  params={'fields': 'name,status,language', 'limit': 200})
                td = tr.json()
                if not tr.ok:
                    err = td.get('error') or {}
                    if err.get('code') == 100:
                        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                                'params': {'title': _("WhatsApp"), 'type': 'warning', 'sticky': True,
                                           'message': msg + ' ' + _(
                                               "But the Business Account ID is not a WhatsApp Business "
                                               "Account (WABA) ID, so templates could not be checked. "
                                               "Use the WABA ID shown in WhatsApp Manager / API Setup.")}}
                    raise UserError(_("Meta: %s", err.get('message', tr.text)[:250]))
                found = {(t['name'], t.get('language')): t.get('status') for t in td.get('data', [])}
                problems = []
                for name in names:
                    st = found.get((name, cfg['template_lang']))
                    if st != 'APPROVED':
                        problems.append('%s (%s)' % (name, st or 'not found in %s' % cfg['template_lang']))
                if problems:
                    msg += ' ' + _("Template problem: %s", ', '.join(problems))
                    kind = 'warning'
                else:
                    msg += ' ' + _("All templates approved.")
        except requests.RequestException as exc:
            raise UserError(_("Could not reach Meta: %s", str(exc)[:200])) from exc
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _("WhatsApp"), 'message': msg, 'type': kind,
                           'sticky': kind != 'success'}}

    def action_att_wa_test(self):
        """Send a test message using the values currently in the form (unsaved)."""
        self.ensure_one()
        Log = self.env['otm.attendance.whatsapp.log']
        cfg = self._att_wa_form_config()
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
