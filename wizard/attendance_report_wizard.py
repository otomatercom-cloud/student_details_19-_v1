from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AttendanceReportWizard(models.TransientModel):
    _name = "attendance.report.wizard"
    _description = "Monthly Attendance Report Wizard"

    batch_id = fields.Many2one("student.batch", required=True)
    start_date = fields.Date(
        required=True,
        default=lambda self: fields.Date.today().replace(day=1))
    end_date = fields.Date(required=True, default=fields.Date.today)
    threshold = fields.Float(
        string="Minimum Attendance %",
        default=lambda self: self.env['otm.attendance.whatsapp.log']._get_config()['low_threshold'])

    def action_generate_report(self):
        self.ensure_one()
        if self.start_date > self.end_date:
            raise UserError(_("Start date must be before the end date."))
        students = self.batch_id.student_ids
        stats = self.env['st.attendance.line'].get_student_stats(
            students.ids, self.start_date, self.end_date, batch_ids=[self.batch_id.id])
        lines = []
        for student in students.sorted('name'):
            st = stats[student.id]
            lines.append((0, 0, {
                'student_id': student.id,
                'present_days': st['present'],
                'late_days': st['late'],
                'half_days': st['half_day'],
                'absent_days': st['absent'],
                'leave_days': st['leave'],
                'total_days': st['working_days'],
                'attendance_percentage': st['percentage'],
                'is_low': bool(st['working_days']) and st['percentage'] < self.threshold,
            }))
        report = self.env['attendance.report.result'].create({
            'wizard_id': self.id,
            'batch_id': self.batch_id.id,
            'start_date': self.start_date,
            'end_date': self.end_date,
            'threshold': self.threshold,
            'line_ids': lines,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Attendance Report'),
            'res_model': 'attendance.report.result',
            'view_mode': 'form',
            'res_id': report.id,
            'target': 'current',
        }


class AttendanceReportResult(models.TransientModel):
    _name = "attendance.report.result"
    _description = "Attendance Report Result"

    wizard_id = fields.Many2one("attendance.report.wizard")
    batch_id = fields.Many2one("student.batch", readonly=True)
    start_date = fields.Date(readonly=True)
    end_date = fields.Date(readonly=True)
    threshold = fields.Float(string="Minimum Attendance %", readonly=True)
    line_ids = fields.One2many("attendance.report.result.line", "result_id")
    low_count = fields.Integer(string="Below Minimum", compute="_compute_low_count")

    @api.depends('line_ids.is_low')
    def _compute_low_count(self):
        for rec in self:
            rec.low_count = len(rec.line_ids.filtered('is_low'))

    def action_export_excel(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/st_attendance/report/register?batch_id=%s&date_from=%s&date_to=%s&threshold=%s' % (
                self.batch_id.id, self.start_date, self.end_date, self.threshold),
            'target': 'new',
        }

    def action_send_low_attendance_whatsapp(self):
        self.ensure_one()
        low = self.line_ids.filtered('is_low')
        if not low:
            raise UserError(_("No student is below %(t)s%% for this period.", t=self.threshold))
        rows = [(l.student_id, self.batch_id, l.attendance_percentage) for l in low]
        Log = self.env['otm.attendance.whatsapp.log']
        logs = Log._queue_low_attendance(rows, self.start_date, self.end_date, self.threshold)
        sent = logs._process_queue() if logs else 0
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _("WhatsApp"), 'type': 'success' if sent else 'warning',
                'message': _("%(new)s alert(s) created, %(sent)s sent. Students already alerted "
                             "for this period are skipped. Check the WhatsApp Log.",
                             new=len(logs), sent=sent),
            },
        }


class AttendanceReportResultLine(models.TransientModel):
    _name = "attendance.report.result.line"
    _description = "Attendance Report Result Line"

    result_id = fields.Many2one("attendance.report.result", ondelete="cascade")
    student_id = fields.Many2one("student.details")
    roll_no = fields.Char(related="student_id.roll_no", string="Register No.")
    present_days = fields.Float()
    late_days = fields.Float()
    half_days = fields.Float()
    absent_days = fields.Float()
    leave_days = fields.Float()
    total_days = fields.Float()
    attendance_percentage = fields.Float()
    is_low = fields.Boolean(string="Below Minimum")
