"""JSON REST API used by the Next.js (BFF) frontend.

Authentication is the normal Odoo session (the Next.js server holds the
session_id cookie, the browser never talks to Odoo). Every call therefore runs
with the real user's access rights and record rules.
"""
import base64
import functools
import json
import logging
import re

from odoo import fields, http, _
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.http import request

from ..models.student_attendance1 import ATT_SESSIONS, ATT_STATUSES

_logger = logging.getLogger(__name__)
P = '/api/sdm'
MAX_PHOTO_BYTES = 3 * 1024 * 1024


def _resp(data, status=200):
    return request.make_json_response(data, status=status)


def _err(message, status=400):
    return _resp({'ok': False, 'error': message}, status)


def api(route, methods=('GET',), auth='user'):
    """Route decorator: JSON in/out, uniform error handling."""
    def deco(fn):
        @http.route(P + route, type='http', auth=auth, methods=list(methods) + ['OPTIONS'],
                    csrf=False, readonly=False)
        @functools.wraps(fn)
        def wrapper(self, *args, **kw):
            try:
                body = {}
                if request.httprequest.method in ('POST', 'PUT'):
                    body = request.httprequest.get_json(silent=True, force=True) or {}
                result = fn(self, *args, body=body, **kw)
                return _resp({'ok': True, 'data': result})
            except (AccessError,):
                request.env.cr.rollback()
                return _err(_("You do not have permission for this action."), 403)
            except MissingError:
                request.env.cr.rollback()
                return _err(_("Record not found."), 404)
            except (UserError, ValidationError) as e:
                request.env.cr.rollback()   # never keep partial writes of a failed call
                return _err(str(e.args[0]) if e.args else str(e), 400)
            except (ValueError, TypeError, KeyError) as e:
                request.env.cr.rollback()
                _logger.info("API bad request on %s: %r", route, e)
                return _err(_("Invalid request data."), 400)
            except Exception:  # noqa
                _logger.exception("API error on %s", route)
                request.env.cr.rollback()
                return _err(_("Server error."), 500)
        return wrapper
    return deco


def _can_finance():
    """Fees / enrollment / payment data is for managers and the admission team only."""
    u = request.env.user
    return bool(request.env.is_superuser() or u.has_group('base.group_system')
                or u.has_group('student_details_19.group_student_manager')
                or u.has_group('student_details_19.group_tl_admission')
                or u.has_group('student_details_19.group_admission_officer'))


def _need_finance():
    from odoo.exceptions import AccessError
    if not _can_finance():
        raise AccessError(_("You do not have access to fee and payment data."))


def _is_manager():
    u = request.env.user
    return bool(request.env.is_superuser() or u.has_group('base.group_system')
                or u.has_group('student_details_19.group_student_manager'))


def _need_attendance():
    """Attendance is for admins/managers and academic coordinators (not course coordinators)."""
    from odoo.exceptions import AccessError
    u = request.env.user
    if not (_is_manager() or u.has_group('student_details_19.group_academic_coordinator')):
        raise AccessError(_("Attendance is available to administrators and academic coordinators only."))


def _valid_whatsapp(value):
    return 10 <= len(re.sub(r'\D', '', value or '')) <= 15


def _decode_photo(raw):
    if not raw:
        return False
    raw = re.sub(r'^data:[^;]+;base64,', '', raw)
    data = base64.b64decode(raw, validate=False)
    if len(data) > MAX_PHOTO_BYTES:
        raise ValidationError(_("Photo is too large (max 3 MB)."))
    return base64.b64encode(data)


def _sel(model, field):
    return [{'value': k, 'label': v} for k, v in request.env[model]._fields[field].selection]


def _student_dict(s, full=False):
    d = {
        'id': s.id, 'name': s.name, 'registration_no': s.registration_no or '',
        'roll_no': s.roll_no or '', 'phone': s.phone or '', 'email': s.email or '',
        'batch': {'id': s.batch_id.id, 'name': s.batch_id.name} if s.batch_id else None,
        'courses': [{'id': c.id, 'name': c.name} for c in s.course_ids],
        'branch': s.branch or '', 'whatsapp_number': s.whatsapp_number or '',
        'active': s.active,
    }
    if full:
        d.update({
            'date_of_birth': fields.Date.to_string(s.date_of_birth) if s.date_of_birth else '',
            'gender': s.gender or '', 'address': s.address or '', 'district': s.district or '',
            'city': s.city or '', 'qualification': s.qualification or '', 'school': s.school or '',
            'college': s.college or '', 'father_name': s.father_name or '',
            'father_phone': s.father_phone or '', 'mother_name': s.mother_name or '',
            'mother_phone': s.mother_phone or '', 'guardian_occupation': s.guardian_occupation or '',
            'insta_id': s.insta_id or '', 'joining_status': s.joining_status or '',
            'reference_code': s.reference_code or '',
            'admission_officer_text': s.admission_officer_text or '',
            'overall_attendance': round(s.overall_attendance, 1),
            'att_wa_opt_out': s.att_wa_opt_out,
            'has_photo': bool(s.photo),
            'logic_join': s.logic_join or '', 'follow_social': s.follow_social,
            'see_social': s.see_social, 'lead_reference_no': s.lead_reference_no or '',
            'admission_officer_id': s.admission_officer_id.id or '',
        })
    return d


STUDENT_WRITE = [
    'name', 'phone', 'email', 'gender', 'address', 'district', 'city', 'qualification',
    'school', 'college', 'father_name', 'father_phone', 'mother_name', 'mother_phone',
    'whatsapp_number', 'guardian_occupation', 'insta_id', 'joining_status', 'branch',
    'reference_code', 'admission_officer_text', 'roll_no', 'att_wa_opt_out',
    'logic_join', 'follow_social', 'see_social', 'active',
]

# Mandatory fields (same as the public registration form)
REQUIRED = [
    ('name', 'Full name'), ('date_of_birth', 'Date of birth'), ('branch', 'Branch'),
    ('joining_status', 'Joining status'), ('email', 'Email'), ('phone', 'Student phone'),
    ('district', 'District'), ('qualification', 'Highest qualification'),
    ('school', 'Previous school'), ('college', 'Previous college'),
    ('father_name', "Father's name"), ('father_phone', "Father's phone"),
    ('mother_name', "Mother's name"), ('mother_phone', "Mother's phone"),
    ('whatsapp_number', "Parent's WhatsApp number"),
]


def _student_vals(body):
    vals = {k: body[k] for k in STUDENT_WRITE if k in body}
    if body.get('date_of_birth') is not None:
        vals['date_of_birth'] = body['date_of_birth'] or False
    if 'batch_id' in body:
        vals['batch_id'] = int(body['batch_id']) if body['batch_id'] else False
    if 'admission_officer_id' in body:
        vals['admission_officer_id'] = int(body['admission_officer_id']) if body['admission_officer_id'] else False
    if 'course_ids' in body:
        vals['course_ids'] = [(6, 0, [int(c) for c in body['course_ids'] or []])]
    return vals


class SdmApi(http.Controller):

    # ------------------------------------------------------------------ auth/me
    @api('/me')
    def me(self, body=None):
        u = request.env.user
        g = u.has_group
        return {
            'id': u.id, 'name': u.name, 'login': u.login,
            'can_finance': _can_finance(), 'can_attendance': _is_manager() or g('student_details_19.group_academic_coordinator'), 'is_manager': _is_manager(), 'has_timetable': 'otm.timetable' in request.env,
            'roles': {
                'manager': g('student_details_19.group_student_manager') or g('base.group_system'),
                'academic': g('student_details_19.group_academic_coordinator'),
                'course': g('student_details_19.group_course_coordinator'),
                'tl_admission': g('student_details_19.group_tl_admission'),
                'admission': g('student_details_19.group_admission_officer'),
            },
        }

    @api('/meta')
    def meta(self, body=None):
        env = request.env
        return {
            'branches': _sel('student.details', 'branch'),
            'districts': _sel('student.details', 'district'),
            'genders': _sel('student.details', 'gender'),
            'logic_join': _sel('student.details', 'logic_join'),
            'joining_statuses': _sel('student.details', 'joining_status'),
            'required': [k for k, _l in REQUIRED] + ['photo'],
            'att_statuses': [{'value': k, 'label': v} for k, v in ATT_STATUSES],
            'att_sessions': [{'value': k, 'label': v} for k, v in ATT_SESSIONS],
            'exam_types': _sel('otm.exam', 'exam_type'),
            'subjects': [{'id': s.id, 'name': s.name} for s in env['otm.exam.subject'].search([])],
            'courses': [{'id': c.id, 'name': c.name} for c in env['course.master'].search([])],
            'batches': [{'id': b.id, 'name': b.name} for b in env['student.batch'].search([])],
            'coordinators': [{'id': u.id, 'name': u.name} for u in env['res.users'].search(
                [('share', '=', False)], limit=300)],
        }

    # ---------------------------------------------------------------- dashboard
    @api('/dashboard')
    def dashboard(self, body=None):
        env = request.env
        today = fields.Date.context_today(env['st.attendance'])
        Att = env['st.attendance']
        can_att = _is_manager() or env.user.has_group('student_details_19.group_academic_coordinator')
        if can_att:
            Att._auto_generate(today)
        absent = env['st.attendance.line'].search(
            [('date', '=', today), ('status', '=', 'absent')], order='batch_id, student_id', limit=300) if can_att else env['st.attendance.line']
        return {
            'today': fields.Date.to_string(today),
            'absent_today': [{'id': l.id, 'student_id': l.student_id.id, 'name': l.student_id.name,
                              'batch': l.batch_id.name or '', 'session': l.session or ''} for l in absent],
            'students': env['student.details'].search_count([]),
            'batches': env['student.batch'].search_count([]),
            'courses': env['course.master'].search_count([]),
            'exams': env['otm.exam'].search_count([]),
            'attendance_today': Att.search_count([('date', '=', today), ('state', '=', 'locked')]) if can_att else 0,
            'can_attendance': bool(can_att),
            'draft_attendance': Att.search_count([('state', '=', 'draft'), ('date', '=', today)]) if can_att else 0,
            'draft_exams': env['otm.exam'].search_count([('state', '=', 'draft')]),
            'wa_failed': env['otm.attendance.whatsapp.log'].search_count([('state', '=', 'failed')]) if can_att else 0,
            'wa_sent': env['otm.attendance.whatsapp.log'].search_count([('state', '=', 'sent')]) if can_att else 0,
        }

    # ------------------------------------------------------------------ courses
    @api('/courses')
    def courses(self, body=None):
        rows = request.env['course.master'].with_context(active_test=False).search([])
        return [{'id': c.id, 'name': c.name, 'code': c.code or '', 'active': c.active,
                 'batches': [{'id': b.id, 'name': b.name} for b in c.batch_ids]} for c in rows]

    @api('/courses/save', methods=('POST',))
    def course_save(self, body=None):
        Course = request.env['course.master'].with_context(active_test=False)
        vals = {k: body[k] for k in ('name', 'code', 'active') if k in body}
        if not (body.get('id') or (vals.get('name') or '').strip()):
            raise ValidationError(_("Course name is required."))
        if body.get('id'):
            rec = Course.browse(int(body['id']))
            rec.write(vals)
        else:
            rec = Course.create(vals)
        return {'id': rec.id}

    # ------------------------------------------------------------------ batches
    def _batch_dict(self, b, full=False):
        d = {'id': b.id, 'name': b.name, 'active': b.active,
             'start_date': fields.Date.to_string(b.start_date) if b.start_date else '',
             'end_date': fields.Date.to_string(b.end_date) if b.end_date else '',
             'student_count': b.student_count,
             'courses': [{'id': c.id, 'name': c.name} for c in b.course_ids],
             'coordinators': [{'id': u.id, 'name': u.name} for u in b.coordinator_ids]}
        if full:
            d['students'] = [_student_dict(s) for s in b.student_ids]
        return d

    @api('/batches')
    def batches(self, body=None):
        rows = request.env['student.batch'].with_context(active_test=False).search([])
        return [self._batch_dict(b) for b in rows]

    @api('/batches/<int:batch_id>')
    def batch_get(self, batch_id, body=None, **kw):
        b = request.env['student.batch'].with_context(active_test=False).browse(batch_id)
        b.check_access('read')
        return self._batch_dict(b, full=True)

    @api('/batches/save', methods=('POST',))
    def batch_save(self, body=None):
        Batch = request.env['student.batch'].with_context(active_test=False)
        vals = {k: body[k] for k in ('name', 'active') if k in body}
        for k in ('start_date', 'end_date'):
            if k in body:
                vals[k] = body[k] or False
        if 'course_ids' in body:
            vals['course_ids'] = [(6, 0, [int(i) for i in body['course_ids'] or []])]
        if 'coordinator_ids' in body:
            vals['coordinator_ids'] = [(6, 0, [int(i) for i in body['coordinator_ids'] or []])]
        if body.get('id'):
            rec = Batch.browse(int(body['id']))
            rec.write(vals)
        else:
            if not (vals.get('name') or '').strip():
                raise ValidationError(_("Batch name is required."))
            rec = Batch.create(vals)
        return {'id': rec.id}

    @api('/batches/<int:batch_id>/students', methods=('POST',))
    def batch_students(self, batch_id, body=None, **kw):
        """Add / remove students: {add: [ids], remove: [ids]}."""
        batch = request.env['student.batch'].browse(batch_id)
        Student = request.env['student.details']
        if body.get('add'):
            Student.browse([int(i) for i in body['add']]).write({'batch_id': batch.id})
        if body.get('remove'):
            Student.browse([int(i) for i in body['remove']]).filtered(
                lambda s: s.batch_id == batch).write({'batch_id': False})
        return {'student_count': batch.student_count}

    # ----------------------------------------------------------------- students
    @api('/students')
    def students(self, body=None, search='', batch_id=None, page='1', limit='25', **kw):
        Student = request.env['student.details']
        domain = []
        if search:
            domain += ['|', '|', '|', ('name', 'ilike', search), ('phone', 'ilike', search),
                       ('registration_no', 'ilike', search), ('roll_no', 'ilike', search)]
        if batch_id:
            domain.append(('batch_id', '=', int(batch_id)))
        limit, page = min(int(limit), 100), max(int(page), 1)
        total = Student.search_count(domain)
        rows = Student.search(domain, limit=limit, offset=(page - 1) * limit, order='id desc')
        return {'total': total, 'page': page, 'limit': limit,
                'items': [_student_dict(s) for s in rows]}

    @api('/students/<int:student_id>')
    def student_get(self, student_id, body=None, **kw):
        s = request.env['student.details'].browse(student_id)
        s.check_access('read')
        return _student_dict(s, full=True)

    @api('/students/<int:student_id>/photo', auth='user')
    def student_photo(self, student_id, body=None, **kw):
        s = request.env['student.details'].browse(student_id)
        s.check_access('read')
        return {'photo': s.photo.decode() if s.photo else ''}

    @api('/students/save', methods=('POST',))
    def student_save(self, body=None):
        Student = request.env['student.details']
        vals = _student_vals(body)
        existing = Student.browse(int(body['id'])) if body.get('id') else None
        missing = []
        for key, label in REQUIRED:
            val = vals[key] if key in vals else (existing[key] if existing else None)
            if not (val and str(val).strip()):
                missing.append(label)
        if not (body.get('photo') or (existing and existing.photo)):
            missing.append('Passport photo')
        if missing:
            raise ValidationError(_("Please fill the mandatory fields: %s.", ', '.join(missing)))
        if 'whatsapp_number' in vals and not _valid_whatsapp(vals['whatsapp_number']):
            raise ValidationError(_("Parent's WhatsApp number is mandatory (10-15 digits)."))
        if body.get('photo'):
            vals['photo'] = _decode_photo(body['photo'])
        if body.get('id'):
            rec = Student.browse(int(body['id']))
            rec.write(vals)
        else:
            if not _valid_whatsapp(vals.get('whatsapp_number')):
                raise ValidationError(_("Parent's WhatsApp number is mandatory (10-15 digits)."))
            vals.setdefault('branch', body.get('branch') or 'kochi')
            rec = Student.create(vals)
        return {'id': rec.id}

    # --------------------------------------------------------------- attendance
    @api('/attendance/batches')
    def att_batches(self, body=None):
        _need_attendance()
        env = request.env
        user = env.user
        domain = [('active', '=', True)]
        if not (user.has_group('student_details_19.group_student_manager')
                or user.has_group('base.group_system')):
            domain.append(('coordinator_ids', 'in', user.id))
        today = fields.Date.context_today(env['st.attendance'])
        env['st.attendance']._auto_generate(today)   # no-op when the daily job already ran
        out = []
        for b in env['student.batch'].search(domain):
            off = env['st.attendance.holiday']._off_reason(b, today)
            sheets = env['st.attendance'].search([('batch_id', '=', b.id), ('date', '=', today)])
            out.append({'id': b.id, 'name': b.name, 'student_count': b.student_count, 'off': off,
                        'today': [{'id': s.id, 'session': s.session, 'state': s.state,
                                   'rate': round(s.attendance_rate, 1), 'slot_no': s.slot_no,
                                   'subject': s.subject_id.name or '', 'extra': s._api_extra()}
                                  for s in sheets.sorted(lambda x: (x._api_extra().get('start', 0), x.id))]})
        return out

    def _sheet_dict(self, sheet):
        return {
            'id': sheet.id, 'name': sheet.name, 'state': sheet.state,
            'batch': {'id': sheet.batch_id.id, 'name': sheet.batch_id.name},
            'date': fields.Date.to_string(sheet.date), 'session': sheet.session,
            'topic': sheet.topic or '', 'remarks': sheet.remarks or '',
            'subject': {'id': sheet.subject_id.id, 'name': sheet.subject_id.name} if sheet.subject_id else None,
            'extra': sheet._api_extra(),
            'counts': {'total': sheet.total_students, 'present': sheet.present_count,
                       'late': sheet.late_count, 'half_day': sheet.half_day_count,
                       'absent': sheet.absent_count, 'leave': sheet.leave_count,
                       'rate': round(sheet.attendance_rate, 1)},
            'lines': [{'id': l.id, 'student_id': l.student_id.id, 'name': l.student_id.name,
                       'roll_no': l.roll_no or '', 'status': l.status, 'remarks': l.remarks or ''}
                      for l in sheet.attendance_line_ids.sorted(lambda x: x.student_id.name or '')],
        }

    @api('/attendance/open', methods=('POST',))
    def att_open(self, body=None):
        _need_attendance()
        env = request.env
        batch = env['student.batch'].browse(int(body['batch_id']))
        batch.check_access('read')
        session = body.get('session') or 'full_day'
        if session not in dict(ATT_SESSIONS):
            session = 'full_day'
        day = fields.Date.to_date(body.get('date')) if body.get('date') else fields.Date.context_today(env['st.attendance'])
        Att = env['st.attendance']
        sheet = Att.search([('batch_id', '=', batch.id), ('date', '=', day), ('session', '=', session),
                            ('slot_no', '=', int(body.get('slot_no') or 0))], limit=1)
        off = env['st.attendance.holiday']._off_reason(batch, day)
        subj = int(body['subject_id']) if body.get('subject_id') else False
        if not sheet and off and not _is_manager():
            raise UserError(_("No attendance needed on %s: %s.", day, off))
        if not sheet:
            sheet = Att.create({'batch_id': batch.id, 'date': day, 'session': session, 'subject_id': subj})
        elif sheet.state == 'draft':
            sheet.action_refresh_students()
        return self._sheet_dict(sheet)

    @api('/attendance/<int:sheet_id>')
    def att_get(self, sheet_id, body=None, **kw):
        _need_attendance()
        sheet = request.env['st.attendance'].browse(sheet_id)
        sheet.check_access('read')
        return self._sheet_dict(sheet)

    @api('/attendance/<int:sheet_id>/save', methods=('POST',))
    def att_save(self, sheet_id, body=None, **kw):
        _need_attendance()
        sheet = request.env['st.attendance'].browse(sheet_id)
        sheet.check_access('write')
        if sheet.state == 'locked':
            raise UserError(_("This attendance is locked."))
        valid = dict(ATT_STATUSES)
        by_id = {l.id: l for l in sheet.attendance_line_ids}
        for row in body.get('lines', []):
            line = by_id.get(int(row['id']))
            if line and row.get('status') in valid:
                line.write({'status': row['status'], 'remarks': (row.get('remarks') or '')[:200]})
        sheet.write({'topic': (body.get('topic') or '')[:150], 'remarks': body.get('remarks') or False})
        if body.get('action') == 'lock':
            sheet.action_lock()
        return self._sheet_dict(sheet)

    @api('/attendance/history')
    def att_history(self, body=None, batch_id=None, **kw):
        _need_attendance()
        domain = [('batch_id', '=', int(batch_id))] if batch_id else []
        rows = request.env['st.attendance'].search(domain, limit=60)
        return [{'id': s.id, 'name': s.name, 'date': fields.Date.to_string(s.date),
                 'session': s.session, 'state': s.state, 'batch': s.batch_id.name,
                 'rate': round(s.attendance_rate, 1), 'absent': s.absent_count,
                 'total': s.total_students} for s in rows]

    # ----------------------------------------------------------------- holidays
    @api('/holidays')
    def holidays(self, body=None, **kw):
        _need_attendance()
        rows = request.env['st.attendance.holiday'].search([])
        ICP = request.env['ir.config_parameter'].sudo()
        return {
            'items': [{'id': h.id, 'name': h.name, 'date_from': fields.Date.to_string(h.date_from),
                       'date_to': fields.Date.to_string(h.date_to),
                       'batches': [{'id': b.id, 'name': b.name} for b in h.batch_ids]} for h in rows],
            'weekly_off': [int(x) for x in request.env['st.attendance.holiday']._weekly_off_days()],
            'auto': ICP.get_param('student_details.att_auto', 'on'),
        }

    @api('/holidays/save', methods=('POST',))
    def holiday_save(self, body=None):
        if not _is_manager():
            from odoo.exceptions import AccessError
            raise AccessError(_("Only administrators can change holidays."))
        H = request.env['st.attendance.holiday']
        vals = {'name': (body.get('name') or '').strip(), 'date_from': body.get('date_from') or False,
                'date_to': body.get('date_to') or body.get('date_from') or False,
                'batch_ids': [(6, 0, [int(i) for i in body.get('batch_ids') or []])]}
        if not vals['name'] or not vals['date_from']:
            raise ValidationError(_("Holiday name and date are required."))
        rec = H.browse(int(body['id'])) if body.get('id') else H.create(vals)
        if body.get('id'):
            rec.write(vals)
        # a sheet for that day may already have been generated: drop untouched drafts
        for sh in request.env['st.attendance'].search([('date', '>=', rec.date_from), ('date', '<=', rec.date_to),
                                                       ('state', '=', 'draft')]):
            if H._off_reason(sh.batch_id, sh.date).startswith('Holiday') and not sh.topic:
                sh.unlink()
        return {'id': rec.id}

    @api('/holidays/<int:hid>/delete', methods=('POST',))
    def holiday_delete(self, hid, body=None, **kw):
        if not _is_manager():
            from odoo.exceptions import AccessError
            raise AccessError(_("Only administrators can change holidays."))
        request.env['st.attendance.holiday'].browse(hid).unlink()
        return {'ok': True}

    @api('/holidays/weekly-off', methods=('POST',))
    def weekly_off_save(self, body=None):
        if not _is_manager():
            from odoo.exceptions import AccessError
            raise AccessError(_("Only administrators can change this."))
        days = sorted({int(d) for d in body.get('days') or [] if 0 <= int(d) <= 6})
        ICP = request.env['ir.config_parameter'].sudo()
        ICP.set_param('student_details.att_weekly_off', ','.join(str(d) for d in days) or '')
        if body.get('auto') in ('on', 'off'):
            ICP.set_param('student_details.att_auto', body['auto'])
        return {'days': days}

    # -------------------------------------------------------------------- marks
    def _exam_dict(self, e, lines=False):
        d = {'id': e.id, 'name': e.name, 'title': e.title, 'subject': e.subject,
             'subject_id': e.subject_id.id or False, 'exam_type': e.exam_type,
             'batch': {'id': e.batch_id.id, 'name': e.batch_id.name},
             'exam_date': fields.Date.to_string(e.exam_date), 'max_marks': e.max_marks,
             'pass_marks': e.pass_marks, 'state': e.state,
             'stats': {'total': e.total_students, 'appeared': e.appeared_count,
                       'absent': e.absent_count, 'pass': e.pass_count, 'fail': e.fail_count,
                       'average': round(e.average_marks, 1), 'highest': e.highest_marks,
                       'lowest': e.lowest_marks, 'pass_percentage': round(e.pass_percentage, 1)},
             'wa_sent': e.wa_sent_count}
        if lines:
            d['lines'] = [{'id': l.id, 'student_id': l.student_id.id, 'name': l.student_id.name,
                           'roll_no': l.student_id.roll_no or '', 'status': l.status,
                           'marks': l.marks, 'remarks': l.remarks or '', 'percentage': round(l.percentage, 1),
                           'result': l.result, 'rank': l.rank}
                          for l in e.line_ids.sorted(lambda x: x.student_id.name or '')]
        return d

    @api('/exams')
    def exams(self, body=None, batch_id=None, **kw):
        domain = [('batch_id', '=', int(batch_id))] if batch_id else []
        return [self._exam_dict(e) for e in request.env['otm.exam'].search(domain, limit=100)]

    @api('/exams/create', methods=('POST',))
    def exam_create(self, body=None):
        env = request.env
        subject_name = (body.get('subject') or '').strip()[:100]
        title = (body.get('title') or '').strip()[:100]
        if not (body.get('batch_id') and title and subject_name and body.get('exam_date')):
            raise ValidationError(_("Batch, title, subject and date are required."))
        Subject = env['otm.exam.subject']
        subj = Subject.search([('name', '=ilike', subject_name)], limit=1) or Subject.create({'name': subject_name})
        exam = env['otm.exam'].create({
            'title': title, 'subject_id': subj.id, 'subject': subj.name,
            'batch_id': int(body['batch_id']), 'exam_date': body['exam_date'],
            'exam_type': body.get('exam_type') or 'other',
            'max_marks': float(body.get('max_marks') or 100),
            'pass_marks': float(body.get('pass_marks') or 40),
            'coordinator_id': env.user.id})
        return {'id': exam.id}

    @api('/exams/<int:exam_id>')
    def exam_get(self, exam_id, body=None, **kw):
        e = request.env['otm.exam'].browse(exam_id)
        e.check_access('read')
        return self._exam_dict(e, lines=True)

    @api('/exams/<int:exam_id>/save', methods=('POST',))
    def exam_save(self, exam_id, body=None, **kw):
        exam = request.env['otm.exam'].browse(exam_id)
        exam.check_access('write')
        if exam.state == 'published':
            raise UserError(_("Marks are published. Unlock to edit."))
        by_id = {l.id: l for l in exam.line_ids}
        for row in body.get('lines', []):
            line = by_id.get(int(row['id']))
            if not line:
                continue
            if row.get('status') == 'absent':
                line.write({'status': 'absent', 'marks': 0.0, 'remarks': (row.get('remarks') or '')[:200]})
            elif row.get('marks') not in (None, ''):
                line.write({'status': 'appeared', 'marks': float(row['marks']),
                            'remarks': (row.get('remarks') or '')[:200]})
            else:
                line.write({'status': 'pending', 'marks': 0.0, 'remarks': (row.get('remarks') or '')[:200]})
        if body.get('action') == 'publish':
            exam.action_publish()
        return self._exam_dict(exam, lines=True)

    @api('/exams/<int:exam_id>/send', methods=('POST',))
    def exam_send(self, exam_id, body=None, **kw):
        exam = request.env['otm.exam'].browse(exam_id)
        exam.check_access('write')
        if exam.state != 'published':
            raise UserError(_("Publish the marks first."))
        Log = request.env['otm.attendance.whatsapp.log'].sudo()
        queued = Log._queue_for_exam(exam)
        logs = Log.search([('exam_id', '=', exam.id), ('state', '=', 'queued')])
        sent = logs._process_queue() if logs else 0
        return {'queued_new': len(queued), 'attempted': len(logs), 'sent': sent}

    @api('/exams/<int:exam_id>/unpublish', methods=('POST',))
    def exam_unpublish(self, exam_id, body=None, **kw):
        exam = request.env['otm.exam'].browse(exam_id)
        exam.action_unpublish()
        return self._exam_dict(exam, lines=True)

    @api('/whatsapp/logs')
    def wa_logs(self, body=None, state=None, **kw):
        domain = [('state', '=', state)] if state else []
        rows = request.env['otm.attendance.whatsapp.log'].search(domain, limit=100, order='id desc')
        return [{'id': l.id, 'student': l.student_id.name, 'type': l.message_type, 'state': l.state,
                 'number': l.number or '', 'error': l.error or '', 'retries': l.retries,
                 'message': l.message or ''} for l in rows]

    # ------------------------------------------------------- public registration
    @api('/public/options', auth='public')
    def public_options(self, body=None):
        env = request.env
        return {
            'branches': _sel('student.details', 'branch'),
            'districts': _sel('student.details', 'district'),
            'genders': _sel('student.details', 'gender'),
            'courses': [{'id': c.id, 'name': c.name} for c in env['course.master'].sudo().search([('active', '=', True)])],
            'batches': [{'id': b.id, 'name': b.name} for b in env['student.batch'].sudo().search([('active', '=', True)])],
        }

    @api('/public/register', methods=('POST',), auth='public')
    def public_register(self, body=None):
        if body.get('website'):                       # honeypot
            return {'id': 0}
        required = ['name', 'date_of_birth', 'branch', 'email', 'phone', 'district', 'qualification',
                    'school', 'college', 'father_name', 'father_phone', 'mother_name', 'mother_phone']
        missing = [k for k in required if not (body.get(k) or '').strip()]
        if missing:
            raise ValidationError(_("Please fill all mandatory fields."))
        if not _valid_whatsapp(body.get('whatsapp_number')):
            raise ValidationError(_("Parent's WhatsApp number is mandatory (10-15 digits)."))
        if not body.get('course_ids'):
            raise ValidationError(_("Please select the course name."))
        if not body.get('photo'):
            raise ValidationError(_("Passport size photo is required."))
        vals = _student_vals(body)
        vals['photo'] = _decode_photo(body['photo'])
        vals.setdefault('joining_status', 'new')
        rec = request.env['student.details'].sudo().create(vals)
        return {'id': rec.id}
