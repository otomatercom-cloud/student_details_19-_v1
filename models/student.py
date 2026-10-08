from odoo import models, fields, api, _


class Student(models.Model):
    _name = 'student.details'
    _description = 'Student Details'
    _rec_name = 'name'

    name = fields.Char(string="Full Name", required=True)
    date_of_birth = fields.Date(string="Date of Birth")
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other')
    ], string="Gender")
    email = fields.Char(string="Email")
    phone = fields.Char(string="Phone Number")
    address = fields.Text(string="Address")
    photo = fields.Image(string="Passport Photo", max_width=413, max_height=531)

    father_name = fields.Char(string="Father Name")
    father_phone = fields.Char(string="Father Phone")
    mother_name = fields.Char(string="Mother Name")
    mother_phone = fields.Char(string="Mother Phone")
    whatsapp_number = fields.Char(string="Whatsapp Number Father or Mother")

    district = fields.Selection([
        ('Alappuzha', 'Alappuzha'), ('Ernakulam', 'Ernakulam'),
        ('Idukki', 'Idukki'), ('Kannur', 'Kannur'),
        ('Kasaragod', 'Kasaragod'), ('Kollam', 'Kollam'),
        ('Kottayam', 'Kottayam'), ('Kozhikode', 'Kozhikode'),
        ('Malappuram', 'Malappuram'), ('Palakkad', 'Palakkad'),
        ('Pathanamthitta', 'Pathanamthitta'),
        ('Thiruvananthapuram', 'Thiruvananthapuram'),
        ('Thrissur', 'Thrissur'), ('Wayanad', 'Wayanad'),
    ], string="District")
    city = fields.Char(string="City")
    guardian_occupation = fields.Char(string="Guardian Occupation")
    qualification = fields.Char(string="Qualification")

    active = fields.Boolean(string="Active", default=True)
    follow_social = fields.Boolean(string="Do you Follow us on Social Media", default=True)
    see_social = fields.Boolean(string="Do you See our Post on Social Media", default=True)
    school = fields.Char(string="Previous School Name")
    college = fields.Char(string="Previous College Name")

    logic_join = fields.Selection([
        ('ads', 'Ads'), ('social_media', 'Social Media'),
        ('seminar', 'Seminar'), ('reference', 'Reference')
    ])
    reference_code = fields.Char(string="Reference Code")
    lead_reference_no = fields.Char(
        string="Lead Reference Number",
        readonly=True,
        copy=False,
        help="Reference number fetched from the connected lead.",
    )
    registration_no = fields.Char(
        string="Register Number",
        readonly=True,
        copy=False,
        help="Auto-generated register number, e.g. ANJ/2026/01",
    )
    insta_id = fields.Char(string="Instagram ID")

    roll_no = fields.Char(string="Register Number")
    batch_id = fields.Many2one('student.batch', string="Batch")
    course_ids = fields.Many2many('course.master', string="Courses")

    admission_officer_text = fields.Char(string="Admission Officer Name (Portal)")
    admission_officer_id = fields.Many2one('res.users', string="Admission Officer")

    joining_status = fields.Selection([
        ('new', 'New'), ('existing', 'Existing')
    ], string="Joining Status", required=True, default='new')

    branch = fields.Selection([
        ('kochi', 'Kochi'), ('calicut', 'Calicut'),
        ('kottayam', 'Kottayam'), ('trivandrum', 'Trivandrum'),
        ('malappuram', 'Malappuram'), ('kozhikode', 'Kozhikode'),
        ('online', 'Online')
    ], string="Branch", required=True)

    # Attendance summary fields (computed, not stored)
    att_start_date = fields.Date("Attendance From")
    att_end_date = fields.Date("Attendance To")
    present_days = fields.Float("Present Days", compute="_compute_attendance_summary")
    late_days = fields.Float("Late Days", compute="_compute_attendance_summary")
    absent_days = fields.Float("Absent Days", compute="_compute_attendance_summary")
    half_days = fields.Float("Half Days", compute="_compute_attendance_summary")
    leave_days = fields.Float("Leave Days", compute="_compute_attendance_summary")
    total_days = fields.Float("Total Working Days", compute="_compute_attendance_summary")
    attendance_percentage = fields.Float("Attendance %", compute="_compute_attendance_summary")
    overall_attendance = fields.Float("Overall Attendance %", compute="_compute_overall_attendance",
                                      help="All locked attendance sheets of the current batch.")
    attendance_record_count = fields.Integer("Attendance Records",
                                             compute="_compute_overall_attendance")
    att_wa_opt_out = fields.Boolean(
        string="Stop Attendance WhatsApp Alerts",
        help="Tick if the guardian asked not to receive attendance alerts on WhatsApp.")

    @api.depends('att_start_date', 'att_end_date')
    def _compute_attendance_summary(self):
        Line = self.env['st.attendance.line']
        with_range = self.filtered(lambda s: s.id and s.att_start_date and s.att_end_date)
        stats = {}
        for student in with_range:
            stats[student.id] = Line.get_student_stats(
                [student.id], student.att_start_date, student.att_end_date)[student.id]
        for student in self:
            st = stats.get(student.id, {})
            student.present_days = st.get('present', 0)
            student.late_days = st.get('late', 0)
            student.half_days = st.get('half_day', 0)
            student.absent_days = st.get('absent', 0)
            student.leave_days = st.get('leave', 0)
            student.total_days = st.get('working_days', 0)
            student.attendance_percentage = st.get('percentage', 0.0)

    @api.depends('batch_id')
    def _compute_overall_attendance(self):
        Line = self.env['st.attendance.line']
        ids = [sid for sid in self.ids if sid]
        stats = Line.get_student_stats(ids) if ids else {}
        for student in self:
            st = stats.get(student.id, {})
            student.overall_attendance = st.get('percentage', 0.0)
            student.attendance_record_count = (
                st.get('working_days', 0) + st.get('leave', 0))

    def action_view_attendance(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Attendance - %s", self.name),
            'res_model': 'st.attendance.line',
            'view_mode': 'list,pivot',
            'domain': [('student_id', '=', self.id)],
            'context': {'search_default_locked': 1},
        }

    @api.model
    def _get_financial_year_start(self, ref_date=None):
        """Indian financial year: April to March."""
        ref_date = ref_date or fields.Date.context_today(self)
        year = ref_date.year
        if ref_date.month < 4:
            year -= 1
        return year

    @api.model
    def _get_registration_prefix(self):
        prefix = self.env['ir.config_parameter'].sudo().get_param(
            'student_details.registration.prefix', 'ANJ'
        )
        return (prefix or 'ANJ').strip().upper()

    @api.model
    def _generate_registration_no(self):
        prefix = self._get_registration_prefix()
        fy_year = self._get_financial_year_start()
        serial = self.env['ir.sequence'].next_by_code('student.registration.serial')
        if not serial:
            serial = '01'
        return f"{prefix}/{fy_year}/{serial}"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault('name', 'New Student')
            if not vals.get('registration_no'):
                vals['registration_no'] = self._generate_registration_no()
            if not vals.get('roll_no'):
                vals['roll_no'] = vals['registration_no']
        return super().create(vals_list)


class StudentBatch(models.Model):
    _name = 'student.batch'
    _description = 'Student Batch'
    _rec_name = 'name'
    _order = 'id desc'

    name = fields.Char(string="Batch Name", required=True)
    start_date = fields.Date(string="Start Date")
    end_date = fields.Date(string="End Date")
    active = fields.Boolean(string="Active", default=True)
    student_ids = fields.One2many('student.details', 'batch_id', string="Students")
    course_ids = fields.Many2many('course.master', string="Courses")
    coordinator_ids = fields.Many2many('res.users', string="Academic Coordinators")

    student_count = fields.Integer(
        string="Students",
        compute="_compute_student_count",
        store=False,
    )

    @api.depends('student_ids')
    def _compute_student_count(self):
        for rec in self:
            rec.student_count = len(rec.student_ids)


class CourseMaster(models.Model):
    _name = "course.master"
    _description = "Course Master"
    _order = "name"

    name = fields.Char(string="Course Name", required=True)
    code = fields.Char(string="Course Code")
    active = fields.Boolean(string="Active", default=True)
    batch_ids = fields.Many2many('student.batch', string="Batches")
    coordinator_ids = fields.Many2many('res.users', string="Course Coordinators")


class BatchAddStudentsWizard(models.TransientModel):
    _name = "batch.add.students.wizard"
    _description = "Bulk Add Students"

    batch_id = fields.Many2one('student.batch', string="Batch")
    student_ids = fields.Many2many('student.details', string="Select Students")

    def action_add_students(self):
        for student in self.student_ids:
            student.batch_id = self.batch_id.id
