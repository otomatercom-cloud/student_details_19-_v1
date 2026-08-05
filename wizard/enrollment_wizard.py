from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class EnrollmentWizard(models.TransientModel):
    _name = 'enrollment.wizard'
    _description = 'Enroll Student in Batch'

    student_id       = fields.Many2one('student.details', required=True, readonly=True)
    batch_id         = fields.Many2one('student.batch', required=True,
                                       domain=[('active','=',True)], string='Select Batch')
    fee_structure_id = fields.Many2one('fee.structure', string='Select Fee Structure',
                                       domain="[('batch_ids','in',batch_id),('fee_type','!=','admission')]")

    # Display fields (readonly, populated by onchange)
    fee_type_display    = fields.Char(string='Fee Type', readonly=True)
    gst_rate_display    = fields.Char(string='GST Rate', readonly=True)
    total_fee_display   = fields.Float(string='Total Fee ₹', readonly=True, digits=(10,2))
    base_fee_display    = fields.Float(string='Base (Excl. GST) ₹', readonly=True, digits=(10,2))
    gst_display         = fields.Float(string='GST ₹', readonly=True, digits=(10,2))
    admission_fee_display = fields.Float(string='Admission Fee ₹', readonly=True, digits=(10,2))
    grand_total_display = fields.Float(string='Grand Total ₹', readonly=True, digits=(10,2))
    installment_summary = fields.Text(string='Installment Schedule', readonly=True)

    # Available fee structures for this batch (for display)
    available_fee_ids = fields.Many2many('fee.structure', compute='_compute_available_fees')

    @api.depends('batch_id')
    def _compute_available_fees(self):
        for rec in self:
            rec.available_fee_ids = rec.batch_id.fee_structure_ids if rec.batch_id else []

    @api.onchange('batch_id')
    def _onchange_batch_id(self):
        self.fee_structure_id = False
        self.fee_type_display = ''
        self.total_fee_display = 0.0
        self.grand_total_display = 0.0
        self.installment_summary = ''

    @api.onchange('fee_structure_id', 'batch_id')
    def _onchange_fee_structure(self):
        if not self.fee_structure_id:
            self.fee_type_display = ''
            self.total_fee_display = 0.0
            self.base_fee_display = 0.0
            self.gst_display = 0.0
            self.admission_fee_display = 0.0
            self.grand_total_display = 0.0
            self.gst_rate_display = ''
            self.installment_summary = ''
            return

        fs = self.fee_structure_id
        fee_type_labels = dict([
            ('lumpsum','Lump Sum'), ('installment','Installment'),
            ('monthly','Monthly'), ('quarterly','Quarterly'),
            ('semi_annual','Semi-Annual'), ('annual','Annual'),
            ('admission','Admission Fee'), ('exam','Exam Fee'),
            ('material','Material Fee'), ('registration','Registration Fee'),
        ])
        self.fee_type_display = fee_type_labels.get(fs.fee_type, fs.fee_type)
        self.gst_rate_display = dict([('0','0%'),('5','5%'),('12','12%'),('18','18%'),('28','28%')]).get(fs.gst_rate,'')

        if fs.fee_type == 'installment':
            self.total_fee_display = fs.total_fee_amount
            self.base_fee_display  = round(fs.total_fee_amount / (1 + float(fs.gst_rate or 0) / 100), 2)
            self.gst_display       = round(self.total_fee_display - self.base_fee_display, 2)
        else:
            self.total_fee_display = fs.amount_inclusive
            self.base_fee_display  = fs.amount_exclusive
            self.gst_display       = fs.tax_amount

        # Find admission fee mapped to same batch
        admission = self.batch_id.fee_structure_ids.filtered(lambda f: f.fee_type == 'admission')
        adm_fee = sum(admission.mapped('amount_inclusive'))
        self.admission_fee_display = adm_fee
        self.grand_total_display = self.total_fee_display + adm_fee

        # Build installment schedule text
        if fs.fee_type == 'installment' and fs.installment_ids:
            lines = [f"{'Installment':<22} {'Due Date':<14} {'Amount (₹)':>12}"]
            lines.append('─' * 50)
            for inst in fs.installment_ids.sorted('sequence'):
                due = str(inst.due_date) if inst.due_date else 'TBD'
                lines.append(f"{inst.name:<22} {due:<14} {inst.amount_inclusive:>12,.2f}")
            lines.append('─' * 50)
            lines.append(f"{'TOTAL':<22} {'':14} {fs.total_fee_amount:>12,.2f}")
            self.installment_summary = '\n'.join(lines)
        else:
            self.installment_summary = ''

    def action_confirm_enrollment(self):
        self.ensure_one()
        if not self.fee_structure_id:
            raise ValidationError(_('Please select a fee structure to enroll.'))

        fs = self.fee_structure_id
        total = fs.total_fee_amount if fs.fee_type == 'installment' else fs.amount_inclusive

        # Also include admission fee in total
        admission = self.batch_id.fee_structure_ids.filtered(lambda f: f.fee_type == 'admission')
        adm_total = sum(admission.mapped('amount_inclusive'))
        grand_total = total + adm_total

        enrollment = self.env['student.enrollment'].create({
            'student_id':       self.student_id.id,
            'batch_id':         self.batch_id.id,
            'fee_structure_id': self.fee_structure_id.id,
            'total_fee':        grand_total,
            'fee_type':         fs.fee_type,
            'gst_rate':         fs.gst_rate,
        })

        # Also update student's batch_id for backwards compatibility
        self.student_id.write({'batch_id': self.batch_id.id})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('✅ Enrolled Successfully'),
                'message': _(
                    f'{self.student_id.name} enrolled in {self.batch_id.name}. '
                    f'Total Fee: ₹{grand_total:,.2f}'
                ),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
