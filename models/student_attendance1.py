from odoo import api, fields, models, _
from odoo.exceptions import UserError

# Attendance weights used everywhere (student summary, reports, WhatsApp alerts).
# 'leave' is an excused absence: it is excluded from the working-day total.
STATUS_WEIGHT = {'present': 1.0, 'late': 1.0, 'half_day': 0.5, 'absent': 0.0}
ATT_STATUSES = [
    ('present', 'Present'),
    ('late', 'Late'),
    ('half_day', 'Half Day'),
    ('absent', 'Absent'),
    ('leave', 'On Leave'),
]
ATT_SESSIONS = [
    ('full_day', 'Full Day'),
    ('morning', 'Morning'),
    ('afternoon', 'Afternoon'),
    ('evening', 'Evening'),
]


def compute_attendance_percentage(counts):
    """counts: dict status -> number. Returns (working_days, percentage)."""
    working = sum(counts.get(s, 0) for s in STATUS_WEIGHT)
    if not working:
        return 0, 0.0
    score = sum(counts.get(s, 0) * w for s, w in STATUS_WEIGHT.items())
    return working, score / working * 100.0


class StudentAttendance(models.Model):
    _name = "st.attendance"
    _description = "Batch Attendance"
    _inherit = ['mail.thread']
    _order = "date desc, id desc"

    name = fields.Char(string="Reference", compute='_compute_name', store=True)
    date = fields.Date(default=fields.Date.today, required=True, tracking=True)
    session = fields.Selection(ATT_SESSIONS, string="Session", default='full_day',
                               required=True, tracking=True)
    subject_id = fields.Many2one('otm.exam.subject', string="Subject", tracking=True,
                                 help="Same subject master used for exam marks.")
    slot_no = fields.Integer(string="Period Ref", default=0, copy=False,
                             help="0 = whole-day sheet. Timetable periods use the timetable slot id.")
    topic = fields.Char(string="Topic / Subject")
    remarks = fields.Text(string="Notes")
    coordinator_id = fields.Many2one('res.users', string="Taken By",
                                     default=lambda self: self.env.user)
    batch_id = fields.Many2one(
        "student.batch", required=True, tracking=True,
        domain=[('active', '=', True)]
    )
    attendance_line_ids = fields.One2many(
        "st.attendance.line", "attendance_id",
        string="Attendance Lines", copy=False
    )
    state = fields.Selection(
        [('draft', 'Draft'), ('locked', 'Locked')],
        default='draft', string="Status", tracking=True,
    )
    locked_by = fields.Many2one('res.users', string="Locked By", readonly=True, copy=False)
    locked_on = fields.Datetime(string="Locked On", readonly=True, copy=False)

    total_students = fields.Integer(string="Students", compute='_compute_counts', store=True)
    present_count = fields.Integer(string="Present", compute='_compute_counts', store=True)
    late_count = fields.Integer(string="Late", compute='_compute_counts', store=True)
    half_day_count = fields.Integer(string="Half Day", compute='_compute_counts', store=True)
    absent_count = fields.Integer(string="Absent", compute='_compute_counts', store=True)
    leave_count = fields.Integer(string="On Leave", compute='_compute_counts', store=True)
    attendance_rate = fields.Float(string="Attendance %", compute='_compute_counts',
                                   store=True, digits=(6, 1), aggregator='avg')

    wa_message_count = fields.Integer(string="WhatsApp Sent",
                                      compute='_compute_wa_message_count')

    _batch_date_session_uniq = models.Constraint(
        'unique(batch_id, date, session, slot_no)',
        'Attendance for this batch, date and session already exists.',
    )

    @api.depends('batch_id', 'date', 'session')
    def _compute_name(self):
        labels = dict(ATT_SESSIONS)
        for rec in self:
            if rec.batch_id and rec.date:
                rec.name = "%s - %s - %s" % (
                    rec.batch_id.name, rec.date, labels.get(rec.session, ''))
            else:
                rec.name = _("New Attendance")

    @api.depends('attendance_line_ids.status')
    def _compute_counts(self):
        for rec in self:
            counts = {}
            for line in rec.attendance_line_ids:
                counts[line.status] = counts.get(line.status, 0) + 1
            rec.total_students = len(rec.attendance_line_ids)
            rec.present_count = counts.get('present', 0)
            rec.late_count = counts.get('late', 0)
            rec.half_day_count = counts.get('half_day', 0)
            rec.absent_count = counts.get('absent', 0)
            rec.leave_count = counts.get('leave', 0)
            rec.attendance_rate = compute_attendance_percentage(counts)[1]

    def _compute_wa_message_count(self):
        data = self.env['otm.attendance.whatsapp.log']._read_group(
            [('attendance_id', 'in', self.ids), ('state', '=', 'sent')],
            ['attendance_id'], ['__count'])
        mapped = {att.id: count for att, count in data}
        for rec in self:
            rec.wa_message_count = mapped.get(rec.id, 0)

    # ------------------------------------------------------------------ lines
    def _prepare_student_lines(self, exclude_student_ids=()):
        self.ensure_one()
        return [
            (0, 0, {'student_id': student.id, 'status': 'present'})
            for student in self.batch_id.student_ids
            if student.id not in exclude_student_ids
        ]

    @api.onchange('batch_id')
    def _onchange_batch_id(self):
        if not self.batch_id:
            self.attendance_line_ids = [(5, 0, 0)]
            return
        self.attendance_line_ids = [(5, 0, 0)] + self._prepare_student_lines()

    def _api_extra(self):
        """Extra, module-specific info for the JSON API (timetable adds time/faculty/room)."""
        return {}

    @api.model
    def _generate_for_batch(self, batch, day):
        """Create the sheet(s) of one batch for one working day. Returns number created."""
        if self.sudo().search_count([('batch_id', '=', batch.id), ('date', '=', day),
                                     ('session', '=', 'full_day'), ('slot_no', '=', 0)]):
            return 0
        self.sudo().create({'batch_id': batch.id, 'date': day, 'session': 'full_day',
                            'coordinator_id': False})
        return 1

    @api.model
    def _auto_generate(self, day=None):
        """Create the (draft) full-day sheet for every active batch on a working day.
        Safe to call repeatedly: existing sheets are never touched."""
        if self.env['ir.config_parameter'].sudo().get_param('student_details.att_auto', 'on') == 'off':
            return 0
        day = fields.Date.to_date(day) if day else fields.Date.context_today(self)
        Holiday = self.env['st.attendance.holiday']
        made = 0
        for batch in self.env['student.batch'].sudo().search([('active', '=', True)]):
            if not batch.student_ids or Holiday._off_reason(batch, day):
                continue
            made += self._generate_for_batch(batch, day)
        return made

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        # Backend (onchange) and portal both end up with a full class list.
        for rec in records:
            if rec.batch_id and not rec.attendance_line_ids:
                rec.write({'attendance_line_ids': rec._prepare_student_lines()})
        return records

    def action_refresh_students(self):
        """Add students who joined the batch after this sheet was created."""
        for rec in self:
            if rec.state == 'locked':
                raise UserError(_("Unlock the attendance before changing it."))
            existing = set(rec.attendance_line_ids.student_id.ids)
            new_lines = rec._prepare_student_lines(exclude_student_ids=existing)
            if new_lines:
                rec.write({'attendance_line_ids': new_lines})
        return True

    def action_mark_all_present(self):
        for rec in self:
            if rec.state == 'locked':
                raise UserError(_("Unlock the attendance before changing it."))
            rec.attendance_line_ids.write({'status': 'present'})
        return True

    # ------------------------------------------------------------- lock logic
    def action_lock(self, *args, **kwargs):
        for rec in self:
            if rec.state == 'locked':
                continue
            if not rec.attendance_line_ids:
                raise UserError(_("There are no students on this attendance sheet."))
            rec.write({
                'state': 'locked',
                'locked_by': self.env.user.id,
                'locked_on': fields.Datetime.now(),
            })
            rec._queue_whatsapp_notifications()
        return True

    def action_unlock(self, *args, **kwargs):
        user = self.env.user
        if not (self.env.is_superuser()
                or user.has_group('student_details_19.group_student_manager')
                or user.has_group('base.group_system')):
            raise UserError(_("Only a Student Details Manager can unlock attendance."))
        self.write({'state': 'draft', 'locked_by': False, 'locked_on': False})
        for rec in self:
            rec.message_post(body=_("Attendance unlocked by %s.", self.env.user.name))
        return True

    # --------------------------------------------------------------- WhatsApp
    def _queue_whatsapp_notifications(self):
        """Queue guardian alerts for absentees (and latecomers when enabled)."""
        Log = self.env['otm.attendance.whatsapp.log'].sudo()
        for rec in self:
            queued = Log._queue_for_attendance(rec)
            if queued:
                rec.message_post(body=_(
                    "%(n)s WhatsApp alert(s) queued for guardians.", n=len(queued)))

    def action_send_whatsapp_absentees(self):
        """Manual trigger: queue anything missing and send right now."""
        self.ensure_one()
        if self.state != 'locked':
            raise UserError(_("Lock the attendance first, then send WhatsApp alerts."))
        Log = self.env['otm.attendance.whatsapp.log'].sudo()
        Log._queue_for_attendance(self)
        logs = Log.search([('attendance_id', '=', self.id), ('state', '=', 'queued')])
        sent = logs._process_queue() if logs else 0
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _("WhatsApp"),
                'type': 'success' if sent else 'warning',
                'message': _("%(sent)s of %(total)s message(s) sent. See the WhatsApp Log for details.",
                             sent=sent, total=len(logs)),
            },
        }

    def action_view_whatsapp_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("WhatsApp Messages"),
            'res_model': 'otm.attendance.whatsapp.log',
            'view_mode': 'list,form',
            'domain': [('attendance_id', '=', self.id)],
        }

    def action_print_excel(self):
        return {
            'type': 'ir.actions.act_url',
            'url': '/st_attendance/report/excel/%s' % self.id,
            'target': 'new',
        }


class StudentAttendanceLine(models.Model):
    _name = "st.attendance.line"
    _description = "Attendance Line"
    _order = "date desc, student_id"

    attendance_id = fields.Many2one("st.attendance", ondelete="cascade", required=True, index=True)
    date = fields.Date(related='attendance_id.date', store=True, string="Date", index=True)
    session = fields.Selection(related='attendance_id.session', store=True, string="Session")
    batch_id = fields.Many2one(related='attendance_id.batch_id', store=True,
                               string="Batch", index=True)
    attendance_state = fields.Selection(related='attendance_id.state', store=True,
                                        string="Sheet Status")
    student_id = fields.Many2one("student.details", required=True, index=True)
    roll_no = fields.Char(related='student_id.roll_no', string="Register No.")
    status = fields.Selection(ATT_STATUSES, default='present', required=True)
    remarks = fields.Char(string="Remarks")

    _attendance_student_uniq = models.Constraint(
        'unique(attendance_id, student_id)',
        'A student can appear only once on an attendance sheet.',
    )

    @api.model
    def get_student_stats(self, student_ids, date_from=None, date_to=None, batch_ids=None):
        """Single source of truth for per-student attendance numbers.

        Only LOCKED sheets count. Returns {student_id: {present, late, half_day,
        absent, leave, working_days, percentage}}.
        """
        student_ids = list(student_ids)
        domain = [('student_id', 'in', student_ids),
                  ('attendance_state', '=', 'locked')]
        if date_from:
            domain.append(('date', '>=', date_from))
        if date_to:
            domain.append(('date', '<=', date_to))
        if batch_ids:
            domain.append(('batch_id', 'in', list(batch_ids)))
        result = {
            sid: {'present': 0, 'late': 0, 'half_day': 0, 'absent': 0, 'leave': 0,
                  'working_days': 0, 'percentage': 0.0}
            for sid in student_ids
        }
        groups = self._read_group(domain, ['student_id', 'status'], ['__count'])
        for student, status, count in groups:
            result[student.id][status] = count
        for vals in result.values():
            vals['working_days'], vals['percentage'] = compute_attendance_percentage(vals)
        return result
