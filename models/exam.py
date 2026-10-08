from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

EXAM_TYPES = [
    ('unit_test', 'Unit Test'),
    ('monthly', 'Monthly Test'),
    ('mock', 'Mock Exam'),
    ('model', 'Model Exam'),
    ('final', 'Final Exam'),
    ('assignment', 'Assignment'),
    ('other', 'Other'),
]


class OtmExamSubject(models.Model):
    _name = "otm.exam.subject"
    _description = "Exam Subject / Paper"
    _order = "name"

    name = fields.Char(string="Subject / Paper", required=True)
    code = fields.Char(string="Code")
    active = fields.Boolean(default=True)

    _name_uniq = models.Constraint('unique(name)', 'This subject already exists.')


class OtmExam(models.Model):
    _name = 'otm.exam'
    _description = 'Exam / Mark Entry'
    _inherit = ['mail.thread']
    _order = 'exam_date desc, id desc'

    name = fields.Char(string="Reference", compute='_compute_name', store=True)
    title = fields.Char(string="Exam Title", required=True, tracking=True,
                        help="e.g. Unit Test 1, Mock Exam")
    subject_id = fields.Many2one('otm.exam.subject', string="Subject", tracking=True,
                                 domain=[('active', '=', True)])
    subject = fields.Char(string="Subject / Paper", required=True, tracking=True,
                          compute='_compute_subject', store=True, readonly=False, precompute=True)
    exam_type = fields.Selection(EXAM_TYPES, string="Exam Type", default='unit_test', required=True)
    batch_id = fields.Many2one('student.batch', string="Batch", required=True, tracking=True,
                               domain=[('active', '=', True)])
    exam_date = fields.Date(string="Exam Date", required=True, default=fields.Date.today, tracking=True)
    max_marks = fields.Float(string="Maximum Marks", required=True, default=100.0, digits=(8, 2))
    pass_marks = fields.Float(string="Pass Marks", required=True, default=40.0, digits=(8, 2))
    coordinator_id = fields.Many2one('res.users', string="Entered By",
                                     default=lambda self: self.env.user)
    state = fields.Selection([('draft', 'Draft'), ('published', 'Published')],
                             default='draft', string="Status", tracking=True)
    remarks = fields.Text(string="Notes")
    line_ids = fields.One2many('otm.exam.line', 'exam_id', string="Marks", copy=False)

    total_students = fields.Integer(string="Students", compute='_compute_stats', store=True)
    appeared_count = fields.Integer(string="Appeared", compute='_compute_stats', store=True)
    absent_count = fields.Integer(string="Absent", compute='_compute_stats', store=True)
    pass_count = fields.Integer(string="Passed", compute='_compute_stats', store=True)
    fail_count = fields.Integer(string="Failed", compute='_compute_stats', store=True)
    average_marks = fields.Float(string="Class Average", compute='_compute_stats',
                                 store=True, digits=(8, 2))
    highest_marks = fields.Float(string="Highest", compute='_compute_stats', store=True, digits=(8, 2))
    lowest_marks = fields.Float(string="Lowest", compute='_compute_stats', store=True, digits=(8, 2))
    pass_percentage = fields.Float(string="Pass %", compute='_compute_stats',
                                   store=True, digits=(6, 1), aggregator='avg')
    wa_sent_count = fields.Integer(string="WhatsApp Sent", compute='_compute_wa_sent_count')

    @api.constrains('max_marks', 'pass_marks')
    def _check_marks_limits(self):
        for rec in self:
            if rec.max_marks <= 0:
                raise ValidationError(_("Maximum marks must be greater than zero."))
            if not 0 <= rec.pass_marks <= rec.max_marks:
                raise ValidationError(_("Pass marks must be between 0 and the maximum marks."))

    @api.depends('subject_id')
    def _compute_subject(self):
        for rec in self:
            if rec.subject_id:
                rec.subject = rec.subject_id.name

    @api.depends('title', 'subject', 'batch_id')
    def _compute_name(self):
        for rec in self:
            if rec.title and rec.batch_id:
                rec.name = "%s - %s (%s)" % (rec.title, rec.subject or '', rec.batch_id.name)
            else:
                rec.name = _("New Exam")

    @api.depends('line_ids.marks', 'line_ids.status', 'line_ids.result')
    def _compute_stats(self):
        for rec in self:
            appeared = rec.line_ids.filtered(lambda l: l.status == 'appeared')
            marks = appeared.mapped('marks')
            rec.total_students = len(rec.line_ids)
            rec.appeared_count = len(appeared)
            rec.absent_count = len(rec.line_ids.filtered(lambda l: l.status == 'absent'))
            rec.pass_count = len(appeared.filtered(lambda l: l.result == 'pass'))
            rec.fail_count = len(appeared.filtered(lambda l: l.result == 'fail'))
            rec.average_marks = sum(marks) / len(marks) if marks else 0.0
            rec.highest_marks = max(marks) if marks else 0.0
            rec.lowest_marks = min(marks) if marks else 0.0
            rec.pass_percentage = rec.pass_count / len(appeared) * 100 if appeared else 0.0

    def _compute_wa_sent_count(self):
        data = self.env['otm.attendance.whatsapp.log']._read_group(
            [('exam_id', 'in', self.ids), ('state', '=', 'sent')], ['exam_id'], ['__count'])
        mapped = {exam.id: count for exam, count in data}
        for rec in self:
            rec.wa_sent_count = mapped.get(rec.id, 0)

    # ------------------------------------------------------------------ lines
    def _prepare_student_lines(self, exclude_student_ids=()):
        self.ensure_one()
        return [(0, 0, {'student_id': s.id}) for s in self.batch_id.student_ids
                if s.id not in exclude_student_ids]

    @api.onchange('batch_id')
    def _onchange_batch_id(self):
        if not self.batch_id:
            self.line_ids = [(5, 0, 0)]
            return
        self.line_ids = [(5, 0, 0)] + self._prepare_student_lines()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            if rec.batch_id and not rec.line_ids:
                rec.write({'line_ids': rec._prepare_student_lines()})
        return records

    def action_refresh_students(self, *args, **kwargs):
        for rec in self:
            if rec.state == 'published':
                raise UserError(_("Unlock the marks before changing them."))
            existing = set(rec.line_ids.student_id.ids)
            new_lines = rec._prepare_student_lines(exclude_student_ids=existing)
            if new_lines:
                rec.write({'line_ids': new_lines})
        return True

    # ----------------------------------------------------------- publish logic
    def action_publish(self, *args, **kwargs):
        for rec in self:
            if rec.state == 'published':
                continue
            if not rec.line_ids:
                raise UserError(_("There are no students on this mark sheet."))
            pending = rec.line_ids.filtered(lambda l: l.status == 'pending')
            if pending:
                names = ', '.join(pending[:8].mapped('student_id.name'))
                raise UserError(_(
                    "Enter marks (or mark Absent) for every student before publishing. "
                    "Pending: %(names)s%(more)s",
                    names=names, more=' ...' if len(pending) > 8 else ''))
            rec.write({'state': 'published'})
            rec.message_post(body=_("Marks published by %s.", self.env.user.name))
            if self.env['otm.attendance.whatsapp.log']._get_config()['marks_auto']:
                rec.sudo()._queue_marks_whatsapp()
        return True

    def action_unpublish(self, *args, **kwargs):
        user = self.env.user
        if not (self.env.is_superuser()
                or user.has_group('student_details_19.group_student_manager')
                or user.has_group('base.group_system')):
            raise UserError(_("Only a Student Details Manager can unlock published marks."))
        self.write({'state': 'draft'})
        for rec in self:
            rec.message_post(body=_("Marks unlocked by %s.", user.name))
        return True

    # --------------------------------------------------------------- WhatsApp
    def _queue_marks_whatsapp(self):
        self.ensure_one()
        return self.env['otm.attendance.whatsapp.log'].sudo()._queue_for_exam(self)

    def action_send_marks_whatsapp(self, *args, **kwargs):
        self.ensure_one()
        if self.state != 'published':
            raise UserError(_("Publish the marks first, then send them to parents."))
        Log = self.env['otm.attendance.whatsapp.log'].sudo()
        self._queue_marks_whatsapp()
        logs = Log.search([('exam_id', '=', self.id), ('state', '=', 'queued')])
        sent = logs._process_queue() if logs else 0
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _("WhatsApp"), 'type': 'success' if sent else 'warning',
                'message': _("%(sent)s of %(total)s mark message(s) sent. Messages already sent "
                             "for unchanged marks are skipped. See the WhatsApp Log.",
                             sent=sent, total=len(logs)),
            },
        }

    def action_view_whatsapp_logs(self, *args, **kwargs):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window', 'name': _("WhatsApp Messages"),
            'res_model': 'otm.attendance.whatsapp.log', 'view_mode': 'list,form',
            'domain': [('exam_id', '=', self.id)],
        }

    def action_print_excel(self, *args, **kwargs):
        return {'type': 'ir.actions.act_url',
                'url': '/st_marks/report/excel/%s' % self.id, 'target': 'new'}


class OtmExamLine(models.Model):
    _name = 'otm.exam.line'
    _description = 'Exam Mark Line'
    _order = 'exam_id, rank, student_id'

    exam_id = fields.Many2one('otm.exam', required=True, ondelete='cascade', index=True)
    batch_id = fields.Many2one(related='exam_id.batch_id', store=True, string="Batch", index=True)
    exam_date = fields.Date(related='exam_id.exam_date', store=True, string="Exam Date")
    subject = fields.Char(related='exam_id.subject', store=True, string="Subject")
    exam_state = fields.Selection(related='exam_id.state', store=True, string="Sheet Status")
    max_marks = fields.Float(related='exam_id.max_marks', string="Max Marks", digits=(8, 2))
    student_id = fields.Many2one('student.details', required=True, index=True)
    roll_no = fields.Char(related='student_id.roll_no', string="Register No.")
    status = fields.Selection([
        ('pending', 'Not Entered'), ('appeared', 'Appeared'), ('absent', 'Absent'),
    ], default='pending', required=True)
    marks = fields.Float(string="Marks", digits=(8, 2))
    remarks = fields.Char(string="Remarks")
    percentage = fields.Float(string="Percentage", compute='_compute_result', store=True, digits=(6, 1))
    result = fields.Selection([
        ('pending', 'Pending'), ('pass', 'Pass'), ('fail', 'Fail'), ('absent', 'Absent'),
    ], compute='_compute_result', store=True, string="Result")
    rank = fields.Integer(string="Rank", compute='_compute_rank', store=True)

    _exam_student_uniq = models.Constraint(
        'unique(exam_id, student_id)', 'A student can appear only once on a mark sheet.')

    @api.constrains('marks', 'status')
    def _check_marks(self):
        for line in self:
            if line.status == 'appeared' and not 0 <= line.marks <= line.exam_id.max_marks:
                raise ValidationError(_(
                    "Marks for %(s)s must be between 0 and %(m)s.",
                    s=line.student_id.name, m=line.exam_id.max_marks))

    @api.depends('marks', 'status', 'exam_id.max_marks', 'exam_id.pass_marks')
    def _compute_result(self):
        for line in self:
            if line.status == 'appeared':
                maxm = line.exam_id.max_marks or 1.0
                line.percentage = line.marks / maxm * 100.0
                line.result = 'pass' if line.marks >= line.exam_id.pass_marks else 'fail'
            else:
                line.percentage = 0.0
                line.result = 'absent' if line.status == 'absent' else 'pending'

    @api.depends('marks', 'status', 'exam_id.line_ids.marks', 'exam_id.line_ids.status')
    def _compute_rank(self):
        for line in self:
            if line.status != 'appeared':
                line.rank = 0
                continue
            higher = {o.marks for o in line.exam_id.line_ids
                      if o.status == 'appeared' and o.marks > line.marks}
            line.rank = len(higher) + 1

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'marks' in vals and vals.get('marks') and 'status' not in vals:
                vals['status'] = 'appeared'
        return super().create(vals_list)

    def write(self, vals):
        if set(vals) & {'marks', 'status', 'remarks', 'student_id'} and not self.env.context.get('exam_force'):
            if any(line.exam_id.state == 'published' for line in self):
                raise UserError(_("These marks are published. Unlock the sheet to change them."))
        # typing a mark on a not-yet-entered row means the student appeared
        if 'marks' in vals and 'status' not in vals:
            vals = dict(vals)
            pending = self.filtered(lambda l: l.status == 'pending')
            if pending and pending == self:
                vals['status'] = 'appeared'
            elif pending:
                (self - pending).write(vals)
                pending.write(dict(vals, status='appeared'))
                return True
        return super().write(vals)
