import json
import logging
import re

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.modules import module

_logger = logging.getLogger(__name__)

PARAM_PREFIX = 'student_details.att_wa.'
MAX_RETRIES = 3

DEFAULT_ABSENT_MSG = (
    "Dear Parent, {student} (Reg: {reg_no}) was marked ABSENT on {date} "
    "({session}) in {batch}. If this is incorrect, please contact the office. "
    "- {institute}"
)
DEFAULT_LATE_MSG = (
    "Dear Parent, {student} (Reg: {reg_no}) arrived LATE on {date} "
    "({session}) in {batch}. - {institute}"
)
DEFAULT_LOW_MSG = (
    "Dear Parent, the attendance of {student} (Reg: {reg_no}) in {batch} is "
    "{percentage}% from {date_from} to {date_to}, below the required "
    "{threshold}%. Kindly ensure regular attendance. - {institute}"
)

CONFIG_DEFAULTS = {
    'enabled': 'False',
    'provider': 'gateway',
    'gateway_url': '',
    'gateway_token': '',
    'meta_phone_id': '',
    'meta_token': '',
    'meta_api_version': 'v21.0',
    'use_template': 'False',
    'template_lang': 'en',
    'absent_template': '',
    'late_template': '',
    'low_template': '',
    'notify_scope': 'absent',
    'low_threshold': '75',
    'country_code': '91',
    'institute_name': '',
    'absent_message': DEFAULT_ABSENT_MSG,
    'late_message': DEFAULT_LATE_MSG,
    'low_message': DEFAULT_LOW_MSG,
}


def render_message(text, values):
    """Safe {placeholder} substitution (no str.format attribute access)."""
    return re.sub(
        r'\{(\w+)\}', lambda m: str(values.get(m.group(1), m.group(0))), text or '')


class AttendanceWhatsappLog(models.Model):
    _name = 'otm.attendance.whatsapp.log'
    _description = 'Attendance WhatsApp Message'
    _order = 'id desc'
    _rec_name = 'number'

    student_id = fields.Many2one('student.details', string="Student", index=True,
                                 ondelete='set null')
    batch_id = fields.Many2one('student.batch', string="Batch", index=True,
                               ondelete='set null')
    attendance_id = fields.Many2one('st.attendance', string="Attendance", index=True,
                                    ondelete='set null')
    line_id = fields.Many2one('st.attendance.line', string="Attendance Line",
                              ondelete='set null')
    message_type = fields.Selection([
        ('absent', 'Absent Alert'),
        ('late', 'Late Alert'),
        ('low_attendance', 'Low Attendance'),
        ('test', 'Test'),
    ], string="Type", required=True, index=True)
    number = fields.Char(string="WhatsApp Number")
    message = fields.Text(string="Message")
    template_params = fields.Text(string="Template Parameters",
                                  help="JSON list used when a Meta template is configured.")
    template_name = fields.Char(string="Template")
    state = fields.Selection([
        ('queued', 'Queued'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
        ('skipped', 'Skipped'),
    ], string="Status", default='queued', required=True, index=True)
    error = fields.Text(string="Error / Response", readonly=True)
    retries = fields.Integer(string="Attempts", readonly=True)
    sent_on = fields.Datetime(string="Sent On", readonly=True)
    dedup_key = fields.Char(index=True, copy=False)

    # ------------------------------------------------------------- config
    @api.model
    def _get_config(self, overrides=None):
        icp = self.env['ir.config_parameter'].sudo()
        cfg = {k: icp.get_param(PARAM_PREFIX + k, d) for k, d in CONFIG_DEFAULTS.items()}
        for key in ('enabled', 'use_template'):
            cfg[key] = str(cfg[key]) == 'True'
        try:
            cfg['low_threshold'] = float(cfg['low_threshold'])
        except (TypeError, ValueError):
            cfg['low_threshold'] = 75.0
        if overrides:
            cfg.update(overrides)
        if not cfg.get('institute_name'):
            cfg['institute_name'] = self.env.company.name or ''
        return cfg

    @api.model
    def _normalize_number(self, raw, country_code='91'):
        digits = re.sub(r'\D', '', raw or '')
        if digits.startswith('00'):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith('0'):
            digits = digits[1:]
        if len(digits) == 10:
            digits = (country_code or '91') + digits
        return digits if 11 <= len(digits) <= 15 else ''

    @api.model
    def _guardian_number(self, student, country_code='91'):
        for raw in (student.whatsapp_number, student.father_phone,
                    student.mother_phone, student.phone):
            number = self._normalize_number(raw, country_code)
            if number:
                return number
        return ''

    # ------------------------------------------------------------- queueing
    @api.model
    def _student_values(self, student, batch, cfg):
        return {
            'student': student.name or '',
            'reg_no': student.registration_no or student.roll_no or '',
            'batch': batch.name or '',
            'institute': cfg['institute_name'],
        }

    @api.model
    def _queue_for_attendance(self, attendance):
        """Create queued guardian alerts for a locked attendance sheet."""
        cfg = self._get_config()
        if not cfg['enabled']:
            return self.browse()
        wanted = {'absent': 'absent'}
        if cfg['notify_scope'] == 'absent_late':
            wanted['late'] = 'late'
        session_label = dict(attendance._fields['session'].selection).get(attendance.session, '')
        vals_list, keys = [], []
        for line in attendance.attendance_line_ids.filtered(lambda l: l.status in wanted):
            student = line.student_id
            if student.att_wa_opt_out:
                continue
            mtype = wanted[line.status]
            key = 'line:%s:%s' % (line.id, mtype)
            keys.append(key)
            number = self._guardian_number(student, cfg['country_code'])
            values = self._student_values(student, attendance.batch_id, cfg)
            values.update({'date': fields.Date.to_string(attendance.date),
                           'session': session_label})
            template_name = cfg['%s_template' % mtype] if cfg['use_template'] else ''
            vals_list.append({
                'student_id': student.id,
                'batch_id': attendance.batch_id.id,
                'attendance_id': attendance.id,
                'line_id': line.id,
                'message_type': mtype,
                'number': number,
                'message': render_message(cfg['%s_message' % mtype], values),
                'template_name': template_name,
                'template_params': json.dumps([
                    values['student'], values['date'], values['batch'], values['session']]),
                'state': 'queued' if number else 'skipped',
                'error': False if number else _("No valid WhatsApp / phone number on the student."),
                'dedup_key': key,
            })
        return self._create_new(vals_list, keys)

    @api.model
    def _queue_low_attendance(self, rows, date_from, date_to, threshold):
        """rows: list of (student, batch, percentage). Returns created logs."""
        cfg = self._get_config()
        if not cfg['enabled']:
            raise UserError(_("WhatsApp attendance alerts are disabled. "
                              "Enable them in Registration Settings first."))
        vals_list, keys = [], []
        for student, batch, percentage in rows:
            if student.att_wa_opt_out:
                continue
            key = 'low:%s:%s:%s' % (student.id, date_from, date_to)
            keys.append(key)
            number = self._guardian_number(student, cfg['country_code'])
            values = self._student_values(student, batch, cfg)
            values.update({
                'percentage': '%.1f' % percentage,
                'threshold': '%g' % threshold,
                'date_from': fields.Date.to_string(date_from),
                'date_to': fields.Date.to_string(date_to),
            })
            template_name = cfg['low_template'] if cfg['use_template'] else ''
            vals_list.append({
                'student_id': student.id,
                'batch_id': batch.id,
                'message_type': 'low_attendance',
                'number': number,
                'message': render_message(cfg['low_message'], values),
                'template_name': template_name,
                'template_params': json.dumps([
                    values['student'], values['batch'], values['percentage'], values['threshold']]),
                'state': 'queued' if number else 'skipped',
                'error': False if number else _("No valid WhatsApp / phone number on the student."),
                'dedup_key': key,
            })
        return self._create_new(vals_list, keys)

    @api.model
    def _create_new(self, vals_list, keys):
        if not vals_list:
            return self.browse()
        existing = set(self.sudo().search([('dedup_key', 'in', keys)]).mapped('dedup_key'))
        fresh = [v for v in vals_list if v['dedup_key'] not in existing]
        logs = self.sudo().create(fresh)
        if logs.filtered(lambda l: l.state == 'queued'):
            self._trigger_queue_cron()
        return logs

    @api.model
    def _trigger_queue_cron(self):
        cron = self.env.ref('student_details_19.ir_cron_attendance_whatsapp_queue',
                            raise_if_not_found=False)
        if cron:
            cron.sudo()._trigger()

    # ------------------------------------------------------------- sending
    def _dispatch(self, cfg):
        """Send ONE message through the configured provider.

        Returns a short provider reference. Raises UserError on failure. This is
        the single integration point: point it at another WhatsApp service by
        replacing/overriding this method.
        """
        self.ensure_one()
        if not self.number:
            raise UserError(_("No valid WhatsApp number."))
        if cfg['provider'] == 'meta':
            return self._dispatch_meta(cfg)
        return self._dispatch_gateway(cfg)

    def _dispatch_gateway(self, cfg):
        url = (cfg['gateway_url'] or '').strip()
        if not url.lower().startswith(('http://', 'https://')):
            raise UserError(_("Gateway URL must start with http:// or https://"))
        headers = {'Content-Type': 'application/json'}
        if cfg['gateway_token']:
            headers['Authorization'] = 'Bearer %s' % cfg['gateway_token']
        payload = {'number': self.number, 'phone': self.number, 'message': self.message}
        resp = requests.post(url, json=payload, headers=headers, timeout=20,
                             allow_redirects=False)
        if not resp.ok:
            raise UserError(_("Gateway HTTP %(code)s: %(body)s",
                              code=resp.status_code, body=resp.text[:300]))
        try:
            data = resp.json()
        except ValueError:
            return resp.text[:100]
        if isinstance(data, dict) and (data.get('success') is False or data.get('error')):
            raise UserError(_("Gateway error: %s", str(data.get('error') or data)[:300]))
        return str((data.get('id') or data.get('message_id') or 'ok') if isinstance(data, dict) else 'ok')[:100]

    def _dispatch_meta(self, cfg):
        if not (cfg['meta_phone_id'] and cfg['meta_token']):
            raise UserError(_("Meta Phone Number ID and access token are required."))
        url = 'https://graph.facebook.com/%s/%s/messages' % (
            cfg['meta_api_version'] or 'v21.0', cfg['meta_phone_id'])
        body = {'messaging_product': 'whatsapp', 'to': self.number}
        if self.template_name:
            params = json.loads(self.template_params or '[]')
            body['type'] = 'template'
            body['template'] = {
                'name': self.template_name,
                'language': {'code': cfg['template_lang'] or 'en'},
                'components': [{
                    'type': 'body',
                    'parameters': [{'type': 'text', 'text': str(p)} for p in params],
                }],
            }
        else:
            body['type'] = 'text'
            body['text'] = {'preview_url': False, 'body': self.message}
        resp = requests.post(
            url, json=body, timeout=20, allow_redirects=False,
            headers={'Authorization': 'Bearer %s' % cfg['meta_token']})
        data = {}
        try:
            data = resp.json()
        except ValueError:
            pass
        if not resp.ok:
            err = (data.get('error') or {}).get('message') if isinstance(data, dict) else ''
            raise UserError(_("Meta API %(code)s: %(msg)s",
                              code=resp.status_code, msg=(err or resp.text)[:300]))
        msgs = data.get('messages') or [{}]
        return msgs[0].get('id', 'ok')

    def _process_queue(self, cfg=None):
        """Send queued messages. Commits after each so a crash never double-sends."""
        cfg = cfg or self._get_config()
        todo = self.sudo().filtered(lambda l: l.state == 'queued')
        if not todo:
            return 0
        if not cfg['enabled']:
            return 0
        self.env['otm.attendance.whatsapp.log'].flush_model()
        self.env.cr.execute(
            "SELECT id FROM otm_attendance_whatsapp_log "
            "WHERE id IN %s AND state = 'queued' FOR UPDATE SKIP LOCKED",
            [tuple(todo.ids)])
        locked = {r[0] for r in self.env.cr.fetchall()}
        sent = 0
        for log in todo.filtered(lambda l: l.id in locked):
            try:
                ref = log._dispatch(cfg)
                log.write({'state': 'sent', 'sent_on': fields.Datetime.now(),
                           'error': ref, 'retries': log.retries + 1})
                sent += 1
            except Exception as exc:  # noqa: BLE001 - provider/network errors
                retries = log.retries + 1
                _logger.warning("Attendance WhatsApp %s failed: %s", log.id, exc)
                log.write({
                    'retries': retries,
                    'error': str(exc)[:500],
                    'state': 'failed' if retries >= MAX_RETRIES else 'queued',
                })
            if not module.current_test:
                # commit per message so a later crash can never re-send it
                self.env['ir.cron']._commit_progress(1)
        return sent

    @api.model
    def _cron_process_queue(self):
        cfg = self._get_config()
        if not cfg['enabled']:
            return
        logs = self.search([('state', '=', 'queued')], limit=100, order='id')
        logs._process_queue(cfg)

    # ------------------------------------------------------------- actions
    def action_retry(self, *args, **kwargs):
        logs = self.sudo().filtered(lambda l: l.state in ('failed', 'skipped'))
        for log in logs:
            if not log.number and log.student_id:
                log.number = self._guardian_number(
                    log.student_id, self._get_config()['country_code'])
        logs = logs.filtered('number')
        logs.write({'state': 'queued', 'retries': 0, 'error': False})
        sent = logs._process_queue()
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _("WhatsApp"), 'type': 'success' if sent else 'warning',
                       'message': _("%(sent)s of %(total)s message(s) sent.",
                                    sent=sent, total=len(logs))},
        }

    def action_send_now(self, *args, **kwargs):
        sent = self.filtered(lambda l: l.state == 'queued')._process_queue()
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _("WhatsApp"), 'type': 'success' if sent else 'warning',
                       'message': _("%s message(s) sent.", sent)},
        }
