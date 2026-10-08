from odoo import http, fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import request
import base64
import re

from ..models.student_attendance1 import ATT_STATUSES


class StudentPortal(http.Controller):

    @staticmethod
    def _valid_whatsapp(value):
        digits = re.sub(r'\D', '', value or '')
        return 10 <= len(digits) <= 15

    @http.route('/students/policy', type='http', auth='public', website=True)
    def portal_student_policy(self, **kw):
        return request.render('student_details_19.portal_student_policy')

    @http.route('/my/students/details', type='http', auth='public', website=True)
    def portal_student_form(self, **kw):
        courses = request.env['course.master'].sudo().search([('active', '=', True)])
        batches = request.env['student.batch'].sudo().search([('active', '=', True)])
        return request.render('student_details_19.portal_student_form', {
            'courses': courses,
            'batches': batches,
        })

    @http.route('/my/students/details/review', type='http', auth='public',
                website=True, methods=['POST'])
    def portal_student_review(self, **post):
        if not self._valid_whatsapp(post.get('whatsapp_number')):
            return request.redirect('/my/students/details?error=whatsapp')
        photo_file = request.httprequest.files.get('photo')
        if photo_file:
            raw_bytes = photo_file.read()
            base64_bytes = base64.b64encode(raw_bytes)
            request.session['uploaded_photo'] = base64_bytes
            post['photo_preview'] = base64_bytes.decode()
        else:
            post['photo_preview'] = False

        course_ids = request.httprequest.form.getlist('course_ids[]')
        if course_ids:
            c_ids = [int(i) for i in course_ids]
            courses = request.env['course.master'].sudo().browse(c_ids)
            post['course_name'] = ", ".join(courses.mapped('name'))
        else:
            post['course_name'] = ''
        post['course_ids[]'] = course_ids

        batch_id = post.get('batch_id')
        if batch_id:
            batch = request.env['student.batch'].sudo().browse(int(batch_id))
            post['batch_name'] = batch.name
        else:
            post['batch_name'] = ''

        return request.render('student_details_19.portal_student_review', {'student': post})

    @http.route('/my/students/details/submit', type='http', auth='public',
                website=True, methods=['POST'])
    def portal_student_submit(self, **post):
        if not self._valid_whatsapp(post.get('whatsapp_number')):
            return request.redirect('/my/students/details?error=whatsapp')
        photo_binary = request.session.get('uploaded_photo', False)
        course_ids = request.httprequest.form.getlist('course_ids')
        batch_id = post.get('batch_id')

        request.env['student.details'].sudo().create({
            'name': post.get('name'),
            'joining_status': post.get('joining_status'),
            'branch': post.get('branch'),
            'date_of_birth': post.get('date_of_birth') or False,
            'gender': post.get('gender'),
            'email': post.get('email'),
            'phone': post.get('phone'),
            'address': post.get('address'),
            'district': post.get('district'),
            'city': post.get('city'),
            'qualification': post.get('qualification'),
            'father_name': post.get('father_name'),
            'father_phone': post.get('father_phone'),
            'mother_name': post.get('mother_name'),
            'mother_phone': post.get('mother_phone'),
            'whatsapp_number': post.get('whatsapp_number'),
            'guardian_occupation': post.get('guardian_occupation'),
            'reference_code': post.get('reference_code'),
            'insta_id': post.get('insta_id'),
            'school': post.get('school'),
            'college': post.get('college'),
            'photo': photo_binary,
            'course_ids': [(6, 0, [int(c) for c in course_ids])] if course_ids else False,
            'batch_id': int(batch_id) if batch_id else False,
            'admission_officer_text': post.get('admission_officer_text'),
        })
        request.session.pop('uploaded_photo', None)
        return request.render('student_details_19.portal_student_success')

    # ── Attendance Portal ────────────────────────────────────────────────────

    BACKDATE_LIMIT_DAYS = 14

    def _attendance_batches(self):
        user = request.env.user
        domain = [('active', '=', True)]
        if not user.has_group('student_details_19.group_student_manager'):
            domain.append(('coordinator_ids', 'in', user.id))
        return request.env['student.batch'].search(domain)

    def _parse_att_date(self, raw):
        today = fields.Date.context_today(request.env['st.attendance'])
        try:
            day = fields.Date.to_date(raw) if raw else today
        except (TypeError, ValueError):
            day = today
        if not day or day > today or (today - day).days > self.BACKDATE_LIMIT_DAYS:
            return today
        return day

    @http.route('/my/attendance/batches', type='http', auth='user', website=True)
    def portal_attendance_batches(self, **kw):
        batches = self._attendance_batches()
        today = fields.Date.context_today(request.env['st.attendance'])
        sheets = request.env['st.attendance'].search(
            [('batch_id', 'in', batches.ids), ('date', '=', today)])
        today_by_batch = {}
        for sheet in sheets:
            today_by_batch.setdefault(sheet.batch_id.id, request.env['st.attendance'])
            today_by_batch[sheet.batch_id.id] |= sheet
        return request.render('student_details_19.portal_attendance_batches', {
            'batches': batches, 'today_by_batch': today_by_batch, 'today': today})

    @http.route('/my/attendance/take', type='http', auth='user', website=True)
    def portal_attendance_take(self, batch_id=None, session='full_day', date=None, **kw):
        try:
            batch = self._attendance_batches().filtered(lambda b: b.id == int(batch_id))
        except (TypeError, ValueError):
            batch = None
        if not batch:
            return request.redirect('/my/attendance/batches')
        Attendance = request.env['st.attendance']
        sessions = dict(Attendance._fields['session'].selection)
        if session not in sessions:
            session = 'full_day'
        day = self._parse_att_date(date)

        attendance = Attendance.search([
            ('batch_id', '=', batch.id), ('date', '=', day), ('session', '=', session),
        ], limit=1)
        if not attendance:
            # Lines are generated by st.attendance.create()
            attendance = Attendance.create({
                'batch_id': batch.id,
                'coordinator_id': request.env.user.id,
                'date': day,
                'session': session,
            })
        elif attendance.state == 'draft':
            attendance.action_refresh_students()

        return request.render('student_details_19.portal_attendance_sheet', {
            'attendance': attendance, 'batch': batch, 'sessions': sessions,
        })

    @http.route('/my/attendance/history', type='http', auth='user', website=True)
    def portal_attendance_history(self, batch_id=None, **kw):
        try:
            batch = self._attendance_batches().filtered(lambda b: b.id == int(batch_id))
        except (TypeError, ValueError):
            batch = None
        if not batch:
            return request.redirect('/my/attendance/batches')
        attendances = request.env['st.attendance'].search(
            [('batch_id', '=', batch.id)], order='date desc, id desc', limit=200)
        return request.render('student_details_19.portal_attendance_history', {
            'batch': batch, 'attendances': attendances,
        })

    @http.route('/my/attendance/view', type='http', auth='user', website=True)
    def portal_attendance_view(self, attendance_id=None, **kw):
        try:
            attendance = request.env['st.attendance'].browse(int(attendance_id)).exists()
            attendance.check_access('read')
        except (TypeError, ValueError, AccessError):
            return request.redirect('/my/attendance/batches')
        if not attendance:
            return request.redirect('/my/attendance/batches')
        return request.render('student_details_19.portal_attendance_sheet', {
            'attendance': attendance, 'batch': attendance.batch_id,
            'sessions': dict(attendance._fields['session'].selection),
        })

    @http.route('/my/attendance/save', type='http', auth='user',
                website=True, methods=['POST'])
    def portal_attendance_save(self, **post):
        try:
            attendance = request.env['st.attendance'].browse(int(post.get('attendance_id'))).exists()
            attendance.check_access('write')
        except (TypeError, ValueError, AccessError):
            return request.redirect('/my/attendance/batches')
        if not attendance:
            return request.redirect('/my/attendance/batches')
        if attendance.state == 'locked':
            return request.render('student_details_19.portal_attendance_success', {'locked': True})

        valid = set(dict(ATT_STATUSES))
        for line in attendance.attendance_line_ids:
            new_status = post.get('status_%s' % line.id)
            vals = {}
            if new_status in valid:
                vals['status'] = new_status
            remark = (post.get('remarks_%s' % line.id) or '').strip()[:200]
            if remark != (line.remarks or ''):
                vals['remarks'] = remark
            if vals:
                line.sudo().write(vals)
        attendance.sudo().write({'topic': (post.get('topic') or '').strip()[:200]})

        locked = post.get('action') == 'lock'
        if locked:
            attendance.sudo().action_lock()
        return request.render('student_details_19.portal_attendance_success', {
            'attendance': attendance, 'submitted': locked})

    # ── Marks Portal ─────────────────────────────────────────────────────────

    def _exam_for_user(self, exam_id):
        try:
            exam = request.env['otm.exam'].browse(int(exam_id)).exists()
            exam.check_access('read')
        except (TypeError, ValueError, AccessError):
            return request.env['otm.exam']
        return exam

    @http.route('/my/marks', type='http', auth='user', website=True)
    def portal_marks(self, **kw):
        batches = self._attendance_batches()
        exams = request.env['otm.exam'].search(
            [('batch_id', 'in', batches.ids)], order='exam_date desc, id desc', limit=40)
        return request.render('student_details_19.portal_marks_home', {
            'batches': batches, 'exams': exams, 'today': fields.Date.context_today(exams),
            'exam_types': request.env['otm.exam']._fields['exam_type'].selection,
            'subjects': request.env['otm.exam.subject'].search([]),
            'error': kw.get('error'),
        })

    @http.route('/my/marks/new', type='http', auth='user', website=True, methods=['POST'])
    def portal_marks_new(self, **post):
        batches = self._attendance_batches()
        try:
            batch = batches.filtered(lambda b: b.id == int(post.get('batch_id')))
            max_marks = float(post.get('max_marks') or 100)
            pass_marks = float(post.get('pass_marks') or 0)
            title = (post.get('title') or '').strip()[:100]
            subject = (post.get('subject') or '').strip()[:100]
            day = fields.Date.to_date(post.get('exam_date'))
            exam_type = post.get('exam_type')
            if not (batch and title and subject and day):
                raise ValueError('missing')
            if exam_type not in dict(request.env['otm.exam']._fields['exam_type'].selection):
                exam_type = 'other'
            Subject = request.env['otm.exam.subject']
            subj = Subject.search([('name', '=ilike', subject)], limit=1) or Subject.create({'name': subject})
            exam = request.env['otm.exam'].create({
                'batch_id': batch.id, 'title': title, 'subject_id': subj.id, 'subject': subj.name, 'exam_date': day,
                'max_marks': max_marks, 'pass_marks': pass_marks, 'exam_type': exam_type,
                'coordinator_id': request.env.user.id,
            })
        except (TypeError, ValueError, AccessError, ValidationError):
            return request.redirect('/my/marks?error=1')
        return request.redirect('/my/marks/sheet?exam_id=%s' % exam.id)

    @http.route('/my/marks/sheet', type='http', auth='user', website=True)
    def portal_marks_sheet(self, exam_id=None, **kw):
        exam = self._exam_for_user(exam_id)
        if not exam:
            return request.redirect('/my/marks')
        if exam.state == 'draft':
            exam.action_refresh_students()
        return request.render('student_details_19.portal_marks_sheet', {
            'exam': exam, 'error': kw.get('error'),
        })

    @http.route('/my/marks/save', type='http', auth='user', website=True, methods=['POST'])
    def portal_marks_save(self, **post):
        exam = self._exam_for_user(post.get('exam_id'))
        if not exam:
            return request.redirect('/my/marks')
        try:
            exam.check_access('write')
        except AccessError:
            return request.redirect('/my/marks')
        if exam.state == 'published':
            return request.redirect('/my/marks/sheet?exam_id=%s' % exam.id)
        try:
            for line in exam.line_ids:
                raw = (post.get('marks_%s' % line.id) or '').strip()
                absent = post.get('absent_%s' % line.id) == 'on'
                vals = {'remarks': (post.get('remarks_%s' % line.id) or '').strip()[:200]}
                if absent:
                    vals.update(status='absent', marks=0.0)
                elif raw:
                    vals.update(status='appeared', marks=float(raw))
                else:
                    vals.update(status='pending', marks=0.0)
                line.sudo().write(vals)
            if post.get('action') == 'publish':
                exam.sudo().action_publish()
        except ValueError:
            request.env.cr.rollback()
            return request.redirect('/my/marks/sheet?exam_id=%s&error=Enter+valid+numbers' % exam.id)
        except (UserError, ValidationError) as exc:
            request.env.cr.rollback()
            from urllib.parse import quote_plus
            return request.redirect('/my/marks/sheet?exam_id=%s&error=%s' % (
                exam.id, quote_plus(str(exc.args[0])[:200])))
        return request.redirect('/my/marks/sheet?exam_id=%s&saved=1' % exam.id)
