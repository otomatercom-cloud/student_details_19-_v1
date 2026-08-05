from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class StudentEnrollment(models.Model):
    _name = 'student.enrollment'
    _description = 'Student Batch Enrollment'
    _rec_name = 'display_name'
    _order = 'enrollment_date desc, id desc'

    display_name = fields.Char(compute='_compute_display_name', store=True)

    student_id      = fields.Many2one('student.details', required=True, ondelete='cascade', index=True)
    batch_id        = fields.Many2one('student.batch', required=True, string='Batch')
    fee_structure_id= fields.Many2one('fee.structure', string='Fee Structure')
    enrollment_date = fields.Date(default=fields.Date.today, string='Enrollment Date')
    status          = fields.Selection([
        ('enrolled', 'Enrolled'),
        ('completed', 'Completed'),
        ('dropped', 'Dropped'),
    ], default='enrolled', string='Status')

    # ── Fee summary (copied from fee structure at enrollment time) ────────────
    total_fee       = fields.Float(string='Total Fee ₹', digits=(10, 2))
    fee_type        = fields.Char(string='Fee Type', readonly=True)
    gst_rate        = fields.Char(string='GST Rate', readonly=True)

    # ── Payment tracking ──────────────────────────────────────────────────────
    payment_ids     = fields.One2many('student.fee.payment', 'enrollment_id', string='Payments')
    paid_amount     = fields.Float(string='Paid ₹', compute='_compute_due', store=True, digits=(10,2))
    due_amount      = fields.Float(string='Due ₹',  compute='_compute_due', store=True, digits=(10,2))
    payment_status  = fields.Selection([
        ('unpaid',   'Unpaid'),
        ('partial',  'Partial'),
        ('paid',     'Paid'),
    ], compute='_compute_due', store=True, string='Payment Status')

    next_due_date   = fields.Date(string='Next Due Date', compute='_compute_next_due', store=True)

    @api.depends('student_id', 'batch_id')
    def _compute_display_name(self):
        for rec in self:
            parts = []
            if rec.student_id:
                parts.append(rec.student_id.name)
            if rec.batch_id:
                parts.append(rec.batch_id.name)
            rec.display_name = ' – '.join(parts) if parts else 'New Enrollment'

    @api.depends('payment_ids.amount', 'total_fee')
    def _compute_due(self):
        for rec in self:
            paid = sum(rec.payment_ids.mapped('amount'))
            rec.paid_amount = round(paid, 2)
            rec.due_amount  = round(rec.total_fee - paid, 2)
            if paid <= 0:
                rec.payment_status = 'unpaid'
            elif paid >= rec.total_fee:
                rec.payment_status = 'paid'
            else:
                rec.payment_status = 'partial'

    @api.depends('fee_structure_id', 'fee_structure_id.installment_ids.due_date',
                 'payment_ids.amount')
    def _compute_next_due(self):
        for rec in self:
            if not rec.fee_structure_id or rec.due_amount <= 0:
                rec.next_due_date = False
                continue
            installments = rec.fee_structure_id.installment_ids.sorted('due_date')
            today = fields.Date.today()
            upcoming = installments.filtered(lambda l: l.due_date and l.due_date >= today)
            rec.next_due_date = upcoming[0].due_date if upcoming else False

    @api.constrains('student_id', 'batch_id')
    def _check_duplicate(self):
        for rec in self:
            dup = self.search([
                ('student_id', '=', rec.student_id.id),
                ('batch_id',   '=', rec.batch_id.id),
                ('status',     '=', 'enrolled'),
                ('id',         '!=', rec.id),
            ])
            if dup:
                raise ValidationError(_(
                    f'{rec.student_id.name} is already enrolled in {rec.batch_id.name}.'
                ))

    def action_add_payment(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Add Payment',
            'res_model': 'student.fee.payment',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_enrollment_id': self.id,
                'default_student_id':    self.student_id.id,
                'default_amount':        self.due_amount,
            },
        }


class StudentFeePayment(models.Model):
    _name = 'student.fee.payment'
    _description = 'Student Fee Payment'
    _order = 'payment_date desc'

    enrollment_id = fields.Many2one('student.enrollment', required=True, ondelete='cascade')
    student_id    = fields.Many2one('student.details', related='enrollment_id.student_id', store=True)
    payment_date  = fields.Date(default=fields.Date.today, required=True)
    amount        = fields.Float(string='Amount Paid ₹', digits=(10, 2), required=True)
    payment_mode  = fields.Selection([
        ('cash',   'Cash'),
        ('upi',    'UPI / GPay / PhonePe'),
        ('neft',   'NEFT / IMPS'),
        ('cheque', 'Cheque'),
        ('dd',     'Demand Draft'),
        ('card',   'Card'),
    ], string='Payment Mode', default='upi')
    receipt_no    = fields.Char(string='Receipt / Ref No.')
    remarks       = fields.Char(string='Remarks')

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_('Payment amount must be positive.'))


# ── Add wallet fields to student.details ─────────────────────────────────────

class StudentWallet(models.Model):
    _inherit = 'student.details'

    enrollment_ids = fields.One2many('student.enrollment', 'student_id', string='Enrollments')

    # Wallet summary
    wallet_total_fee  = fields.Float(compute='_compute_wallet', store=True, digits=(10,2))
    wallet_paid       = fields.Float(compute='_compute_wallet', store=True, digits=(10,2))
    wallet_due        = fields.Float(compute='_compute_wallet', store=True, digits=(10,2))
    wallet_status     = fields.Selection([
        ('clear',   'Clear'),
        ('partial', 'Partial'),
        ('due',     'Due'),
    ], compute='_compute_wallet', store=True)
    wallet_next_due   = fields.Date(compute='_compute_wallet', store=True)
    enrollment_count  = fields.Integer(compute='_compute_wallet', store=True)
    active_enrollment = fields.Many2one('student.enrollment', compute='_compute_wallet',
                                        string='Active Enrollment')

    @api.depends('enrollment_ids.total_fee', 'enrollment_ids.paid_amount',
                 'enrollment_ids.due_amount', 'enrollment_ids.next_due_date',
                 'enrollment_ids.status')
    def _compute_wallet(self):
        for rec in self:
            active = rec.enrollment_ids.filtered(lambda e: e.status == 'enrolled')
            rec.enrollment_count  = len(active)
            rec.wallet_total_fee  = sum(active.mapped('total_fee'))
            rec.wallet_paid       = sum(active.mapped('paid_amount'))
            rec.wallet_due        = sum(active.mapped('due_amount'))

            if rec.wallet_due <= 0 and rec.wallet_total_fee > 0:
                rec.wallet_status = 'clear'
            elif rec.wallet_paid > 0:
                rec.wallet_status = 'partial'
            else:
                rec.wallet_status = 'due'

            dates = active.filtered('next_due_date').mapped('next_due_date')
            rec.wallet_next_due = min(dates) if dates else False
            rec.active_enrollment = active[0].id if active else False

    def action_enroll_batch(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Enroll in Batch',
            'res_model': 'enrollment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_student_id': self.id},
        }
