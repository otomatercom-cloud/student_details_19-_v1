from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

FEE_TYPE_LABELS = dict([
    ('lumpsum', 'Lump Sum'), ('installment', 'Installment'),
    ('monthly', 'Monthly'), ('quarterly', 'Quarterly'),
    ('semi_annual', 'Semi-Annual'), ('annual', 'Annual'),
    ('admission', 'Admission Fee'), ('exam', 'Exam Fee'),
    ('material', 'Material Fee'), ('registration', 'Registration Fee'),
])
# Only ONE of these "course package" fees can be chosen; the rest are add-ons.
PACKAGE_TYPES = ('lumpsum', 'installment', 'monthly', 'quarterly', 'semi_annual', 'annual')


def fee_total(fs):
    """Incl.-GST payable amount of one fee structure."""
    return fs.total_fee_amount if fs.fee_type == 'installment' else fs.amount_inclusive


class EnrollmentWizard(models.TransientModel):
    _name = 'enrollment.wizard'
    _description = 'Enroll Student in Batch'

    student_id = fields.Many2one('student.details', required=True, readonly=True)
    batch_id = fields.Many2one('student.batch', required=True,
                               domain=[('active', '=', True)], string='Select Batch')
    fee_structure_ids = fields.Many2many(
        'fee.structure', 'enrollment_wizard_fee_rel', 'wizard_id', 'fee_id',
        string='Select Fees',
        domain="[('batch_ids', 'in', batch_id)]")

    # Display (computed from the selected fees)
    fee_count = fields.Integer(compute='_compute_fee_display')
    base_fee_display = fields.Float(string='Base (Excl. GST) ₹', compute='_compute_fee_display', digits=(10, 2))
    gst_display = fields.Float(string='GST ₹', compute='_compute_fee_display', digits=(10, 2))
    grand_total_display = fields.Float(string='Grand Total ₹', compute='_compute_fee_display', digits=(10, 2))
    fee_breakdown = fields.Text(string='Fee Breakdown', compute='_compute_fee_display')
    installment_summary = fields.Text(string='Installment Schedule', compute='_compute_fee_display')

    available_fee_ids = fields.Many2many('fee.structure', compute='_compute_available_fees')

    @api.depends('batch_id')
    def _compute_available_fees(self):
        for rec in self:
            rec.available_fee_ids = rec.batch_id.fee_structure_ids if rec.batch_id else []

    @api.onchange('batch_id')
    def _onchange_batch_id(self):
        self.fee_structure_ids = False

    @api.constrains('fee_structure_ids')
    def _check_single_package(self):
        for rec in self:
            packages = rec.fee_structure_ids.filtered(lambda f: f.fee_type in PACKAGE_TYPES)
            if len(packages) > 1:
                raise ValidationError(_(
                    "Choose only ONE course package fee (Lump Sum / Installment / Monthly ...). "
                    "Admission, Registration, Exam and Material fees can be added along with it."))

    @api.depends('fee_structure_ids')
    def _compute_fee_display(self):
        for rec in self:
            fees = rec.fee_structure_ids
            rec.fee_count = len(fees)
            grand = sum(fee_total(f) for f in fees)
            gst = 0.0
            lines = []
            for f in fees:
                amount = fee_total(f)
                rate = float(f.gst_rate or 0)
                base = round(amount / (1 + rate / 100), 2)
                gst += amount - base
                lines.append("%-30s %-16s %12s" % (
                    (f.name or '')[:30], FEE_TYPE_LABELS.get(f.fee_type, f.fee_type), "{:,.2f}".format(amount)))
            if lines:
                lines.insert(0, "-" * 60)
                lines.insert(0, "%-30s %-16s %12s" % ('Fee', 'Type', 'Amount (₹)'))
                lines.append("-" * 60)
                lines.append("%-30s %-16s %12s" % ('TOTAL', '', "{:,.2f}".format(grand)))
            rec.fee_breakdown = '\n'.join(lines)
            rec.grand_total_display = round(grand, 2)
            rec.gst_display = round(gst, 2)
            rec.base_fee_display = round(grand - gst, 2)

            sched = []
            for f in fees.filtered(lambda x: x.fee_type == 'installment' and x.installment_ids):
                sched.append("%s" % f.name)
                sched.append("%-22s %-14s %12s" % ('Installment', 'Due Date', 'Amount (₹)'))
                for inst in f.installment_ids.sorted('sequence'):
                    sched.append("%-22s %-14s %12s" % (
                        (inst.name or '')[:22], str(inst.due_date) if inst.due_date else 'TBD',
                        "{:,.2f}".format(inst.amount_inclusive)))
                sched.append('')
            rec.installment_summary = '\n'.join(sched).strip()

    def action_confirm_enrollment(self):
        self.ensure_one()
        if not self.fee_structure_ids:
            raise ValidationError(_('Please select at least one fee to enroll.'))

        fees = self.fee_structure_ids
        primary = fees.filtered(lambda f: f.fee_type in PACKAGE_TYPES)[:1] or fees[:1]
        grand_total = round(sum(fee_total(f) for f in fees), 2)

        self.env['student.enrollment'].create({
            'student_id': self.student_id.id,
            'batch_id': self.batch_id.id,
            'fee_structure_id': primary.id,
            'fee_structure_ids': [(6, 0, fees.ids)],
            'total_fee': grand_total,
            'fee_type': ', '.join(FEE_TYPE_LABELS.get(f.fee_type, f.fee_type) for f in fees),
            'gst_rate': primary.gst_rate,
        })
        # Backwards compatibility: keep the student's current batch in sync.
        self.student_id.write({'batch_id': self.batch_id.id})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Enrolled Successfully'),
                'message': _('%(student)s enrolled in %(batch)s. Total Fee: ₹%(total)s',
                             student=self.student_id.name, batch=self.batch_id.name,
                             total="{:,.2f}".format(grand_total)),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
