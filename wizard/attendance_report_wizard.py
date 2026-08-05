from odoo import models, fields, api


class AttendanceReportWizard(models.TransientModel):
    _name = "attendance.report.wizard"
    _description = "Monthly Attendance Report Wizard"

    batch_id = fields.Many2one("student.batch", required=True)
    start_date = fields.Date(required=True)
    end_date = fields.Date(required=True)

    def action_generate_report(self):
        AttendanceLine = self.env['st.attendance.line']
        result = []

        for student in self.batch_id.student_ids:
            domain = [
                ('student_id', '=', student.id),
                ('date', '>=', self.start_date),
                ('date', '<=', self.end_date),
                ('attendance_id.state', '=', 'locked'),
            ]
            # Odoo 19: _read_group replaces read_group
            groups = AttendanceLine._read_group(
                domain,
                groupby=['status'],
                aggregates=['__count'],
            )
            present = absent = half = 0
            for (status,), count in groups:
                if status == 'present':
                    present = count
                elif status == 'absent':
                    absent = count
                elif status == 'half_day':
                    half = count

            total = present + absent + half
            percentage = ((present + (half * 0.5)) / total * 100) if total else 0.0

            result.append((0, 0, {
                'student_id': student.id,
                'present_days': present,
                'absent_days': absent,
                'half_days': half,
                'total_days': total,
                'attendance_percentage': percentage,
            }))

        report = self.env['attendance.report.result'].create({
            'wizard_id': self.id,
            'line_ids': result,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': 'Attendance Report',
            'res_model': 'attendance.report.result',
            'view_mode': 'form',
            'res_id': report.id,
            'target': 'current',
        }


class AttendanceReportResult(models.TransientModel):
    _name = "attendance.report.result"
    _description = "Attendance Report Result"

    wizard_id = fields.Many2one("attendance.report.wizard")
    line_ids = fields.One2many("attendance.report.result.line", "result_id")


class AttendanceReportResultLine(models.TransientModel):
    _name = "attendance.report.result.line"
    _description = "Attendance Report Result Line"

    result_id = fields.Many2one("attendance.report.result")
    student_id = fields.Many2one("student.details")
    present_days = fields.Float()
    absent_days = fields.Float()
    half_days = fields.Float()
    total_days = fields.Float()
    attendance_percentage = fields.Float()
