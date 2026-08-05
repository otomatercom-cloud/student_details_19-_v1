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
    absent_days = fields.Float("Absent Days", compute="_compute_attendance_summary")
    half_days = fields.Float("Half Days", compute="_compute_attendance_summary")
    total_days = fields.Float("Total Working Days", compute="_compute_attendance_summary")
    attendance_percentage = fields.Float("Attendance %", compute="_compute_attendance_summary")

    def _compute_attendance_summary(self):
        AttendanceLine = self.env['st.attendance.line']
        for student in self:
            student.present_days = 0.0
            student.absent_days = 0.0
            student.half_days = 0.0
            student.total_days = 0.0
            student.attendance_percentage = 0.0

            if not student.att_start_date or not student.att_end_date:
                continue

            domain = [
                ('student_id', '=', student.id),
                ('date', '>=', student.att_start_date),
                ('date', '<=', student.att_end_date),
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
            student.present_days = present
            student.absent_days = absent
            student.half_days = half
            student.total_days = total
            if total:
                student.attendance_percentage = ((present + (half * 0.5)) / total) * 100

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
