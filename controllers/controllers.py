from odoo import http
from odoo.http import request
import io
import xlsxwriter


class StudentDetailsBackend(http.Controller):

    @http.route(
        ['/st_attendance/report/excel/<model("st.attendance"):attendance>'],
        type='http', auth="user"
    )
    def get_st_attendance_excel(self, attendance, **kw):
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Attendance')

        header_fmt = workbook.add_format({'bold': True, 'align': 'center', 'bg_color': '#D3D3D3', 'border': 1})
        cell_fmt = workbook.add_format({'align': 'left', 'border': 1})
        present_fmt = workbook.add_format({'align': 'center', 'border': 1, 'font_color': 'green', 'bold': True})
        absent_fmt = workbook.add_format({'align': 'center', 'border': 1, 'font_color': 'red', 'bold': True})

        sheet.set_column('A:A', 30)
        sheet.set_column('B:B', 15)
        sheet.write(0, 0, 'Student Name', header_fmt)
        sheet.write(0, 1, 'Status', header_fmt)

        row = 1
        for line in attendance.attendance_line_ids:
            sheet.write(row, 0, line.student_id.name, cell_fmt)
            status_label = 'Present' if line.status == 'present' else ('Half Day' if line.status == 'half_day' else 'Absent')
            fmt = present_fmt if line.status == 'present' else absent_fmt
            sheet.write(row, 1, status_label, fmt)
            row += 1

        workbook.close()
        output.seek(0)

        filename = 'Attendance_%s_%s.xlsx' % (attendance.batch_id.name, attendance.date)
        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition', 'attachment; filename="%s"' % filename),
            ]
        )
