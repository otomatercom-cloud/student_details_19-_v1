import io
from datetime import timedelta

import xlsxwriter

from odoo import fields, http
from odoo.exceptions import AccessError
from odoo.http import request

from ..models.student_attendance1 import ATT_STATUSES

STATUS_LABEL = dict(ATT_STATUSES)
STATUS_CODE = {'present': 'P', 'late': 'L', 'half_day': 'H', 'absent': 'A', 'leave': 'LV'}
STATUS_COLOR = {
    'present': '#198754', 'late': '#fd7e14', 'half_day': '#b58900',
    'absent': '#dc3545', 'leave': '#0d6efd',
}
MAX_REGISTER_DAYS = 93


def _xlsx_response(output, filename):
    output.seek(0)
    return request.make_response(
        output.read(),
        headers=[
            ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
            ('Content-Disposition', http.content_disposition(filename)),
        ])


class StudentDetailsBackend(http.Controller):

    @http.route(
        ['/st_attendance/report/excel/<model("st.attendance"):attendance>'],
        type='http', auth="user"
    )
    def get_st_attendance_excel(self, attendance, **kw):
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Attendance')
        title = workbook.add_format({'bold': True, 'font_size': 14})
        header_fmt = workbook.add_format(
            {'bold': True, 'align': 'center', 'bg_color': '#1f6f43', 'font_color': 'white', 'border': 1})
        cell_fmt = workbook.add_format({'border': 1})
        status_fmts = {
            key: workbook.add_format(
                {'align': 'center', 'border': 1, 'bold': True, 'font_color': color})
            for key, color in STATUS_COLOR.items()
        }

        sheet.set_column('A:A', 6)
        sheet.set_column('B:B', 34)
        sheet.set_column('C:C', 18)
        sheet.set_column('D:D', 14)
        sheet.set_column('E:E', 36)
        sheet.write(0, 0, '%s - %s' % (attendance.batch_id.name, attendance.date), title)
        sheet.write(1, 0, 'Session: %s | Taken by: %s | Present %s, Late %s, Half %s, Absent %s, Leave %s (%.1f%%)' % (
            dict(attendance._fields['session'].selection).get(attendance.session, ''),
            attendance.coordinator_id.name or '-', attendance.present_count, attendance.late_count,
            attendance.half_day_count, attendance.absent_count, attendance.leave_count,
            attendance.attendance_rate))
        for col, head in enumerate(['#', 'Student Name', 'Register No.', 'Status', 'Remarks']):
            sheet.write(3, col, head, header_fmt)
        row = 4
        for idx, line in enumerate(attendance.attendance_line_ids.sorted(lambda l: l.student_id.name or ''), 1):
            sheet.write(row, 0, idx, cell_fmt)
            sheet.write(row, 1, line.student_id.name, cell_fmt)
            sheet.write(row, 2, line.student_id.roll_no or '', cell_fmt)
            sheet.write(row, 3, STATUS_LABEL.get(line.status, ''), status_fmts.get(line.status, cell_fmt))
            sheet.write(row, 4, line.remarks or '', cell_fmt)
            row += 1
        workbook.close()
        return _xlsx_response(output, 'Attendance_%s_%s.xlsx' % (attendance.batch_id.name, attendance.date))

    @http.route('/st_attendance/report/register', type='http', auth='user')
    def get_attendance_register_excel(self, batch_id=None, date_from=None, date_to=None,
                                      threshold=None, **kw):
        """Day-wise attendance register for one batch (respects record rules)."""
        try:
            batch = request.env['student.batch'].browse(int(batch_id)).exists()
            d_from = fields.Date.to_date(date_from)
            d_to = fields.Date.to_date(date_to)
            min_pct = float(threshold or 0)
            batch.check_access('read')
        except (TypeError, ValueError, AccessError):
            return request.not_found()
        if not (batch and d_from and d_to) or d_from > d_to:
            return request.not_found()
        if (d_to - d_from).days + 1 > MAX_REGISTER_DAYS:
            d_to = d_from + timedelta(days=MAX_REGISTER_DAYS - 1)

        Line = request.env['st.attendance.line']
        lines = Line.search([
            ('batch_id', '=', batch.id), ('attendance_state', '=', 'locked'),
            ('date', '>=', d_from), ('date', '<=', d_to)])
        sessions = sorted({(l.date, l.session) for l in lines})
        students = batch.student_ids.sorted(lambda s: s.name or '')
        stats = Line.get_student_stats(students.ids, d_from, d_to, batch_ids=[batch.id])
        by_key = {(l.student_id.id, l.date, l.session): l.status for l in lines}
        multi_session = len({s for _d, s in sessions}) > 1
        session_labels = dict(request.env['st.attendance']._fields['session'].selection)

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = wb.add_worksheet('Register')
        title = wb.add_format({'bold': True, 'font_size': 14})
        head = wb.add_format({'bold': True, 'align': 'center', 'valign': 'vcenter',
                              'bg_color': '#1f6f43', 'font_color': 'white', 'border': 1,
                              'text_wrap': True})
        cell = wb.add_format({'border': 1})
        num = wb.add_format({'border': 1, 'align': 'center'})
        pct = wb.add_format({'border': 1, 'align': 'center', 'num_format': '0.0'})
        low_pct = wb.add_format({'border': 1, 'align': 'center', 'num_format': '0.0',
                                 'bold': True, 'font_color': '#dc3545', 'bg_color': '#fde8ea'})
        code_fmts = {k: wb.add_format({'border': 1, 'align': 'center', 'bold': True,
                                       'font_color': c}) for k, c in STATUS_COLOR.items()}

        ws.write(0, 0, '%s - Attendance Register (%s to %s)' % (batch.name, d_from, d_to), title)
        ws.write(1, 0, 'P=Present  L=Late  H=Half Day  A=Absent  LV=On Leave'
                       '  |  Late counts as present; Half Day = 0.5; Leave excluded from total.')
        fixed = ['#', 'Student', 'Register No.']
        summary = ['Present', 'Late', 'Half', 'Absent', 'Leave', 'Total', '%']
        first_day_col = len(fixed)
        for col, text in enumerate(fixed):
            ws.write(3, col, text, head)
        for i, (day, sess) in enumerate(sessions):
            label = day.strftime('%d-%b')
            if multi_session:
                label += '\n' + session_labels.get(sess, sess)
            ws.write(3, first_day_col + i, label, head)
        sum_col = first_day_col + len(sessions)
        for i, text in enumerate(summary):
            ws.write(3, sum_col + i, text, head)
        ws.set_row(3, 32)
        ws.set_column(0, 0, 5)
        ws.set_column(1, 1, 32)
        ws.set_column(2, 2, 16)
        ws.set_column(first_day_col, sum_col + len(summary), 8)
        ws.freeze_panes(4, 3)

        row = 4
        for idx, student in enumerate(students, 1):
            ws.write(row, 0, idx, num)
            ws.write(row, 1, student.name, cell)
            ws.write(row, 2, student.roll_no or '', cell)
            for i, (day, sess) in enumerate(sessions):
                status = by_key.get((student.id, day, sess))
                ws.write(row, first_day_col + i, STATUS_CODE.get(status, ''),
                         code_fmts.get(status, num))
            st = stats[student.id]
            for i, key in enumerate(['present', 'late', 'half_day', 'absent', 'leave', 'working_days']):
                ws.write(row, sum_col + i, st[key], num)
            is_low = st['working_days'] and st['percentage'] < min_pct
            ws.write(row, sum_col + 6, round(st['percentage'], 1), low_pct if is_low else pct)
            row += 1
        wb.close()
        return _xlsx_response(output, 'Attendance_Register_%s_%s_%s.xlsx' % (batch.name, d_from, d_to))
