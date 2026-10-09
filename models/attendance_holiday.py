from odoo import api, fields, models
from odoo.exceptions import ValidationError

WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']


class AttendanceHoliday(models.Model):
    _name = 'st.attendance.holiday'
    _description = 'Attendance Holiday'
    _order = 'date_from desc'

    name = fields.Char(string="Holiday", required=True)
    date_from = fields.Date(string="From", required=True)
    date_to = fields.Date(string="To", required=True)
    batch_ids = fields.Many2many(
        'student.batch', 'st_attendance_holiday_batch_rel', 'holiday_id', 'batch_id',
        string="Only these batches", help="Leave empty to apply to every batch.")
    active = fields.Boolean(default=True)

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_to < rec.date_from:
                raise ValidationError(self.env._("'To' date cannot be before 'From' date."))

    @api.model
    def _weekly_off_days(self):
        raw = self.env['ir.config_parameter'].sudo().get_param('student_details.att_weekly_off', '6')
        return {int(x) for x in (raw or '').replace(' ', '').split(',') if x.isdigit() and int(x) < 7}

    @api.model
    def _off_reason(self, batch, day):
        """Return a reason text when no attendance is needed for this batch on `day`, else ''."""
        day = fields.Date.to_date(day)
        if day.weekday() in self._weekly_off_days():
            return 'Weekly off (%s)' % WEEKDAYS[day.weekday()]
        if batch.start_date and day < batch.start_date:
            return 'Batch not started'
        if batch.end_date and day > batch.end_date:
            return 'Batch ended'
        hol = self.sudo().search([('date_from', '<=', day), ('date_to', '>=', day)]).filtered(
            lambda h: not h.batch_ids or batch in h.batch_ids)[:1]
        return ('Holiday: %s' % hol.name) if hol else ''
