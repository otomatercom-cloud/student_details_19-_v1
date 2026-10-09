import re

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .attendance_whatsapp import (
    DEFAULT_ABSENT_MSG, DEFAULT_LATE_MSG, DEFAULT_LOW_MSG, DEFAULT_MARKS_MSG, PARAM_PREFIX)

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

    # ── Daily attendance sheets ──────────────────────────────────────────────
    att_auto_generate = fields.Selection(
        [('on', 'Create sheets automatically every day'), ('off', 'Off (manual only)')],
        string="Daily Attendance Sheets", default='on', config_parameter='student_details.att_auto')
    att_weekly_off = fields.Char(
        string="Weekly Off Days", default='6', config_parameter='student_details.att_weekly_off',
        help="Comma separated weekday numbers: 0=Mon 1=Tue 2=Wed 3=Thu 4=Fri 5=Sat 6=Sun. "
             "Example: 6 (Sunday) or 5,6 (Sat+Sun). Holidays are added under Attendance > Holidays.")

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
        help="Variables: 1 student, 2 exam - subject, 3 marks (e.g. 45/50 (90.0%)), 4 result.")
    att_wa_late_template = fields.Char(
        string="Late template",
        help="Variables: 1 student, 2 exam - subject, 3 marks (e.g. 45/50 (90.0%)), 4 result.")
    att_wa_low_template = fields.Char(
        string="Low attendance template",
        help="Variables: 1 student, 2 exam - subject, 3 marks (e.g. 45/50 (90.0%)), 4 result.")
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
    att_wa_marks_template = fields.Char(
        string="Marks template", config_parameter=PARAM_PREFIX + 'marks_template',
        help="Variables: 1 student, 2 exam - subject, 3 marks (e.g. 45/50 (90.0%)), 4 result.")
    att_wa_marks_message = fields.Char(
        string="Marks Message", default=DEFAULT_MARKS_MSG,
        config_parameter=PARAM_PREFIX + 'marks_message')
    att_wa_marks_auto = fields.Boolean(
        string="Send Marks When Published", config_parameter=PARAM_PREFIX + 'marks_auto',
        help="Queue the mark message to every parent as soon as a mark sheet is published.")
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
            'marks_template': self.att_wa_marks_template or '',
            'country_code': self.att_wa_country_code or '91',
        })

    def action_att_wa_check_connection(self):
        """Ask Meta what this token can see (phone, business account, templates)."""
        self.ensure_one()
        cfg = self._att_wa_form_config()
        if not (cfg['meta_phone_id'] and cfg['meta_token']):
            raise UserError(_("Enter the Phone Number ID and Access token first."))
        base = 'https://graph.facebook.com/%s/' % cfg['meta_api_version']
        headers = {'Authorization': 'Bearer %s' % cfg['meta_token'].strip()}

        def fetch(path, params=None):
            try:
                resp = requests.get(base + path, params=params, headers=headers,
                                    timeout=15, allow_redirects=False)
                body = resp.json()
            except (requests.RequestException, ValueError) as exc:
                return None, str(exc)[:150]
            if resp.status_code != 200:
                return None, (body.get('error') or {}).get('message') or str(resp.status_code)
            return body, None

        lines, ok = [], True
        phone, err = fetch(cfg['meta_phone_id'], {'fields': 'display_phone_number,verified_name'})
        if err:
            ok = False
            lines.append(_("Phone Number ID is NOT usable with this token: %s", err))
        else:
            lines.append(_("Phone %(num)s (%(name)s) OK.", num=phone.get('display_phone_number'),
                           name=phone.get('verified_name')))
        waba = re.sub(r'\D', '', cfg['meta_waba_id'] or '')
        if waba:
            numbers, err = fetch(waba + '/phone_numbers', {'fields': 'id,display_phone_number'})
            if err:
                ok = False
                lines.append(_("Cannot read business account %(w)s: %(e)s", w=waba, e=err))
            else:
                ids = [n.get('id') for n in numbers.get('data', [])]
                if cfg['meta_phone_id'] in ids:
                    lines.append(_("Phone belongs to this business account."))
                else:
                    ok = False
                    lines.append(_("PROBLEM: this phone number is NOT in business account %s.", waba))
            tpls, err = fetch(waba + '/message_templates',
                              {'fields': 'name,language,status', 'limit': 200})
            if err:
                ok = False
                lines.append(_("Cannot read templates: %s", err))
            else:
                found = {(t['name'], t.get('language')): t.get('status') for t in tpls.get('data', [])}
                for name in (cfg['absent_template'], cfg['late_template'], cfg['low_template'],
                         cfg['marks_template']):
                    if not name:
                        continue
                    status = found.get((name, cfg['template_lang']))
                    if status != 'APPROVED':
                        ok = False
                        lines.append(_("Template %(n)s [%(l)s]: %(s)s", n=name, l=cfg['template_lang'],
                                       s=status or _("not found")))
                    else:
                        lines.append(_("Template %s approved.", name))
        else:
            lines.append(_("Enter the Business Account ID to also check templates."))
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': _("WhatsApp connection"), 'message': ' '.join(lines),
                           'type': 'success' if ok else 'warning', 'sticky': not ok}}

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
