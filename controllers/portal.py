from odoo import http, fields
from odoo.http import request
import base64


class StudentPortal(http.Controller):

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

    @http.route('/my/attendance/batches', type='http', auth='user', website=True)
    def portal_attendance_batches(self, **kw):
        user = request.env.user
        batches = request.env['student.batch'].search([
            ('active', '=', True),
            ('coordinator_ids', 'in', user.id),
        ])
        return request.render('student_details_19.portal_attendance_batches', {'batches': batches})

    @http.route('/my/attendance/take', type='http', auth='user', website=True)
    def portal_attendance_take(self, batch_id=None, **kw):
        if not batch_id:
            return request.redirect('/my/attendance/batches')

        batch = request.env['student.batch'].browse(int(batch_id))
        user = request.env.user
        today = fields.Date.today()

        attendance = request.env['st.attendance'].search([
            ('batch_id', '=', batch.id),
            ('date', '=', today),
            ('coordinator_id', '=', user.id),
        ], limit=1)

        if not attendance:
            attendance = request.env['st.attendance'].create({
                'batch_id': batch.id,
                'coordinator_id': user.id,
                'date': today,
            })
            # Populate lines manually (onchange doesn't fire on create)
            if not attendance.attendance_line_ids:
                request.env['st.attendance.line'].create([
                    {'attendance_id': attendance.id, 'student_id': s.id, 'status': 'present'}
                    for s in batch.student_ids
                ])

        return request.render('student_details_19.portal_attendance_sheet', {
            'attendance': attendance,
            'batch': batch,
        })

    @http.route('/my/attendance/history', type='http', auth='user', website=True)
    def portal_attendance_history(self, batch_id=None, **kw):
        if not batch_id:
            return request.redirect('/my/attendance/batches')
        batch = request.env['student.batch'].browse(int(batch_id))
        attendances = request.env['st.attendance'].search(
            [('batch_id', '=', batch.id)], order='date desc')
        return request.render('student_details_19.portal_attendance_history', {
            'batch': batch, 'attendances': attendances,
        })

    @http.route('/my/attendance/view', type='http', auth='user', website=True)
    def portal_attendance_view(self, attendance_id=None, **kw):
        if not attendance_id:
            return request.redirect('/my/attendance/batches')
        attendance = request.env['st.attendance'].browse(int(attendance_id))
        return request.render('student_details_19.portal_attendance_sheet', {
            'attendance': attendance, 'batch': attendance.batch_id,
        })

    @http.route('/my/attendance/save', type='http', auth='user',
                website=True, methods=['POST'])
    def portal_attendance_save(self, **post):
        attendance_id = post.get('attendance_id')
        if not attendance_id:
            return request.redirect('/my/attendance/batches')

        attendance = request.env['st.attendance'].browse(int(attendance_id))
        if attendance.state == 'locked':
            return request.render('student_details_19.portal_attendance_success', {'locked': True})

        for line in attendance.attendance_line_ids:
            new_status = post.get('status_%s' % line.id)
            if new_status:
                line.sudo().write({'status': new_status})

        attendance.sudo().action_lock()
        return request.render('student_details_19.portal_attendance_success')
