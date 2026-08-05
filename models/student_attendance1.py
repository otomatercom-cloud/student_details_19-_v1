from odoo import models, fields, api


class StudentAttendance(models.Model):
    _name = "st.attendance"
    _description = "Batch Attendance"
    _order = "date desc"

    date = fields.Date(default=fields.Date.today, required=True)
    coordinator_id = fields.Many2one('res.users', default=lambda self: self.env.user)
    batch_id = fields.Many2one(
        "student.batch", required=True,
        domain=[('active', '=', True)]
    )
    attendance_line_ids = fields.One2many(
        "st.attendance.line", "attendance_id",
        string="Attendance Lines", copy=False, auto_join=True
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('locked', 'Locked')],
        default='draft', string="Status",
    )

    @api.onchange('batch_id')
    def _onchange_batch_id(self):
        if not self.batch_id:
            self.attendance_line_ids = [(5, 0, 0)]
            return
        self.attendance_line_ids = [
            (0, 0, {'student_id': student.id, 'status': 'present'})
            for student in self.batch_id.student_ids
        ]

    def action_lock(self):
        self.state = 'locked'

    def action_unlock(self):
        self.state = 'draft'

    def action_print_excel(self):
        return {
            'type': 'ir.actions.act_url',
            'url': '/st_attendance/report/excel/%s' % self.id,
            'target': 'new',
        }


class StudentAttendanceLine(models.Model):
    _name = "st.attendance.line"
    _description = "Attendance Line"

    attendance_id = fields.Many2one("st.attendance", ondelete="cascade")
    date = fields.Date(related='attendance_id.date', store=True, string="Date")
    student_id = fields.Many2one("student.details", required=True)
    status = fields.Selection(
        [('present', 'Present'), ('absent', 'Absent'), ('half_day', 'Half Day')],
        default='present'
    )
