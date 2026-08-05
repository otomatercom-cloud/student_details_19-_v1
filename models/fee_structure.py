from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from dateutil.relativedelta import relativedelta

GST_RATES = [
    ('0',  '0% (Exempt)'),
    ('5',  '5% GST'),
    ('12', '12% GST'),
    ('18', '18% GST'),
    ('28', '28% GST'),
]

FEE_TYPES = [
    ('lumpsum',      'Lump Sum'),
    ('installment',  'Installment'),
    ('monthly',      'Monthly'),
    ('quarterly',    'Quarterly'),
    ('semi_annual',  'Semi-Annual'),
    ('annual',       'Annual'),
    ('admission',    'Admission Fee'),
    ('exam',         'Exam Fee'),
    ('material',     'Material Fee'),
    ('registration', 'Registration Fee'),
]

ORDINAL = {
    1:'1st', 2:'2nd', 3:'3rd', 4:'4th', 5:'5th',
    6:'6th', 7:'7th', 8:'8th', 9:'9th', 10:'10th',
    11:'11th', 12:'12th', 18:'18th', 24:'24th',
}
def ordinal(n):
    return ORDINAL.get(n, f"{n}th")


class FeeStructure(models.Model):
    _name = 'fee.structure'
    _description = 'Fee Structure'
    _rec_name = 'name'
    _order = 'id desc'

    name = fields.Char(string='Fee Structure Name', required=True)
    fee_type = fields.Selection(FEE_TYPES, string='Fee Type', required=True, default='lumpsum')
    gst_rate = fields.Selection(GST_RATES, string='GST Rate', required=True, default='18')
    active = fields.Boolean(default=True)
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.ref('base.INR', raise_if_not_found=False)
    )
    description = fields.Text(string='Notes')

    # ── Entry mode ────────────────────────────────────────────────────────────
    amount_entry_mode = fields.Selection([
        ('inclusive', 'Enter Amount Inclusive of GST'),
        ('exclusive', 'Enter Amount Exclusive of GST'),
    ], string='Entry Mode', required=True, default='inclusive')

    # ── Lump-sum / non-installment amounts ───────────────────────────────────
    amount_inclusive = fields.Float(string='Amount (Incl. GST) ₹', digits=(10, 2))
    amount_exclusive = fields.Float(string='Amount (Excl. GST) ₹', digits=(10, 2))
    tax_amount   = fields.Float(string='GST ₹',  digits=(10,2), compute='_compute_tax', store=True)
    cgst_amount  = fields.Float(string='CGST ₹', digits=(10,2), compute='_compute_tax', store=True)
    sgst_amount  = fields.Float(string='SGST ₹', digits=(10,2), compute='_compute_tax', store=True)

    # ── Installment configuration ─────────────────────────────────────────────
    total_fee_amount = fields.Float(
        string='Total Fee Amount (₹)',
        digits=(10, 2),
        help="Total fee to be split across installments (Inclusive of GST)."
    )
    num_installments = fields.Integer(
        string='Number of Installments',
        default=3,
        help="How many equal installments to generate."
    )
    first_due_date = fields.Date(
        string='First Due Date',
        help="Due date of the 1st installment. Subsequent ones will be monthly."
    )
    installment_ids = fields.One2many('fee.installment', 'fee_structure_id', string='Installments')

    # ── Installment summary (computed, not stored - live in form) ─────────────
    installment_allocated = fields.Float(
        string='Total Allocated ₹',
        compute='_compute_installment_summary',
        digits=(10, 2),
    )
    installment_balance = fields.Float(
        string='Remaining Balance ₹',
        compute='_compute_installment_summary',
        digits=(10, 2),
        help="Difference between Total Fee and sum of all installments. Should be 0."
    )
    installment_count = fields.Integer(
        string='Installments',
        compute='_compute_installment_summary',
    )

    # ── Batch mapping ──────────────────────────────────────────────────────────
    batch_ids = fields.Many2many(
        'student.batch', 'fee_structure_batch_rel',
        'fee_structure_id', 'batch_id', string='Applicable Batches',
    )

    # ─────────────────────────────────────────────────────────────────────────
    # Computes
    # ─────────────────────────────────────────────────────────────────────────

    @api.depends('amount_inclusive', 'amount_exclusive', 'gst_rate')
    def _compute_tax(self):
        for rec in self:
            rate = float(rec.gst_rate or 0)
            excl = rec.amount_exclusive or 0.0
            tax = round(excl * rate / 100, 2)
            rec.tax_amount = tax
            rec.cgst_amount = round(tax / 2, 2)
            rec.sgst_amount = round(tax / 2, 2)

    @api.depends('installment_ids.amount_inclusive', 'total_fee_amount')
    def _compute_installment_summary(self):
        for rec in self:
            allocated = sum(rec.installment_ids.mapped('amount_inclusive'))
            rec.installment_allocated = round(allocated, 2)
            rec.installment_balance = round(rec.total_fee_amount - allocated, 2)
            rec.installment_count = len(rec.installment_ids)

    # ─────────────────────────────────────────────────────────────────────────
    # Onchanges
    # ─────────────────────────────────────────────────────────────────────────

    @api.onchange('amount_inclusive', 'gst_rate')
    def _onchange_inclusive(self):
        if self.amount_entry_mode == 'inclusive' and self.amount_inclusive:
            rate = float(self.gst_rate or 0)
            self.amount_exclusive = round(self.amount_inclusive / (1 + rate / 100), 2)

    @api.onchange('amount_exclusive', 'gst_rate')
    def _onchange_exclusive(self):
        if self.amount_entry_mode == 'exclusive' and self.amount_exclusive:
            rate = float(self.gst_rate or 0)
            self.amount_inclusive = round(self.amount_exclusive * (1 + rate / 100), 2)

    @api.onchange('amount_entry_mode')
    def _onchange_entry_mode(self):
        self.amount_inclusive = 0.0
        self.amount_exclusive = 0.0

    @api.onchange('installment_ids')
    def _onchange_installment_ids(self):
        """Auto-adjust the LAST installment so total always equals total_fee_amount."""
        if not self.total_fee_amount or not self.installment_ids:
            return
        lines = list(self.installment_ids)
        if len(lines) < 2:
            return
        sum_except_last = sum(l.amount_inclusive for l in lines[:-1])
        last_amount = round(self.total_fee_amount - sum_except_last, 2)
        if last_amount >= 0:
            rate = float(self.gst_rate or 0)
            lines[-1].amount_inclusive = last_amount
            lines[-1].amount_exclusive = round(last_amount / (1 + rate / 100), 2)

    # ─────────────────────────────────────────────────────────────────────────
    # Smart Split Action
    # ─────────────────────────────────────────────────────────────────────────

    def action_auto_split(self):
        """Generate equal installment lines from total_fee_amount / num_installments."""
        self.ensure_one()
        if not self.total_fee_amount:
            raise ValidationError(_('Please enter the Total Fee Amount before splitting.'))
        if not self.num_installments or self.num_installments < 1:
            raise ValidationError(_('Please enter a valid number of installments (minimum 1).'))

        rate = float(self.gst_rate or 0)
        total = self.total_fee_amount
        n = self.num_installments

        # Equal split with rounding correction on last installment
        per_inst = round(total / n, 2)
        amounts = [per_inst] * n
        amounts[-1] = round(total - per_inst * (n - 1), 2)   # absorb rounding diff

        # Clear existing lines
        self.installment_ids.unlink()

        lines = []
        base_date = self.first_due_date or fields.Date.today()
        for i, amt in enumerate(amounts, start=1):
            excl = round(amt / (1 + rate / 100), 2)
            tax  = round(amt - excl, 2)
            due  = base_date + relativedelta(months=i - 1)
            lines.append({
                'fee_structure_id': self.id,
                'sequence': i * 10,
                'name': f"{ordinal(i)} Installment",
                'due_date': due,
                'amount_inclusive': amt,
                'amount_exclusive': excl,
            })

        self.env['fee.installment'].create(lines)

        # Keep total_fee_amount synced to amount_inclusive on parent
        self.amount_inclusive = total
        self.amount_exclusive = round(total / (1 + rate / 100), 2)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('✅ Installments Generated'),
                'message': _(f'{n} installments created. Total: ₹{total:,.2f}'),
                'type': 'success',
                'sticky': False,
            },
        }

    def action_adjust_last(self):
        """Force last installment = total_fee_amount - sum of all others."""
        self.ensure_one()
        if not self.total_fee_amount or not self.installment_ids:
            return
        lines = self.installment_ids.sorted('sequence')
        if len(lines) < 2:
            return
        others = lines[:-1]
        last   = lines[-1]
        sum_others = sum(others.mapped('amount_inclusive'))
        last_amt = round(self.total_fee_amount - sum_others, 2)
        if last_amt < 0:
            raise ValidationError(
                _('Sum of earlier installments (₹%s) already exceeds the total fee (₹%s).'
                  % (f'{sum_others:,.2f}', f'{self.total_fee_amount:,.2f}'))
            )
        rate = float(self.gst_rate or 0)
        last.write({
            'amount_inclusive': last_amt,
            'amount_exclusive': round(last_amt / (1 + rate / 100), 2),
        })

    def action_view_installments(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Installments',
            'res_model': 'fee.installment',
            'view_mode': 'list,form',
            'domain': [('fee_structure_id', '=', self.id)],
            'context': {'default_fee_structure_id': self.id},
        }

    @api.constrains('fee_type', 'installment_ids')
    def _check_installments(self):
        for rec in self:
            if rec.fee_type == 'installment' and not rec.installment_ids:
                raise ValidationError(_('Please add at least one installment.'))


# ─────────────────────────────────────────────────────────────────────────────

class FeeInstallment(models.Model):
    _name = 'fee.installment'
    _description = 'Fee Installment Line'
    _order = 'sequence, due_date'

    fee_structure_id = fields.Many2one(
        'fee.structure', required=True, ondelete='cascade', string='Fee Structure'
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Installment', required=True)
    due_date = fields.Date(string='Due Date')
    remarks = fields.Char(string='Remarks')

    gst_rate = fields.Selection(
        GST_RATES, related='fee_structure_id.gst_rate', store=True, readonly=True
    )

    amount_inclusive = fields.Float(string='Amount (Incl. GST) ₹', digits=(10, 2))
    amount_exclusive = fields.Float(string='Amount (Excl. GST) ₹', digits=(10, 2))
    tax_amount  = fields.Float(string='GST ₹',  digits=(10,2), compute='_compute_tax', store=True)
    cgst_amount = fields.Float(string='CGST ₹', digits=(10,2), compute='_compute_tax', store=True)
    sgst_amount = fields.Float(string='SGST ₹', digits=(10,2), compute='_compute_tax', store=True)

    @api.onchange('amount_inclusive')
    def _onchange_inclusive(self):
        if self.amount_inclusive is not None:
            rate = float(self.gst_rate or 0)
            self.amount_exclusive = round(self.amount_inclusive / (1 + rate / 100), 2)

    @api.onchange('amount_exclusive')
    def _onchange_exclusive(self):
        if self.amount_exclusive is not None:
            rate = float(self.gst_rate or 0)
            self.amount_inclusive = round(self.amount_exclusive * (1 + rate / 100), 2)

    @api.depends('amount_inclusive', 'amount_exclusive', 'gst_rate')
    def _compute_tax(self):
        for rec in self:
            rate = float(rec.gst_rate or 0)
            excl = rec.amount_exclusive or 0.0
            tax = round(excl * rate / 100, 2)
            rec.tax_amount = tax
            rec.cgst_amount = round(tax / 2, 2)
            rec.sgst_amount = round(tax / 2, 2)


# ─────────────────────────────────────────────────────────────────────────────

class StudentBatchFeeInherit(models.Model):
    _inherit = 'student.batch'

    fee_structure_ids = fields.Many2many(
        'fee.structure', 'fee_structure_batch_rel',
        'batch_id', 'fee_structure_id', string='Fee Structures',
    )

    fee_lumpsum              = fields.Float(compute='_compute_fee_summary', store=True, digits=(10,2))
    fee_admission            = fields.Float(compute='_compute_fee_summary', store=True, digits=(10,2))
    fee_installment          = fields.Float(compute='_compute_fee_summary', store=True, digits=(10,2))
    fee_registration         = fields.Float(compute='_compute_fee_summary', store=True, digits=(10,2))
    fee_exam                 = fields.Float(compute='_compute_fee_summary', store=True, digits=(10,2))
    fee_material             = fields.Float(compute='_compute_fee_summary', store=True, digits=(10,2))
    total_lumpsum_package    = fields.Float(compute='_compute_fee_summary', store=True, digits=(10,2))
    total_installment_package= fields.Float(compute='_compute_fee_summary', store=True, digits=(10,2))
    has_installment_fee      = fields.Boolean(compute='_compute_fee_summary', store=True)
    has_lumpsum_fee          = fields.Boolean(compute='_compute_fee_summary', store=True)

    @api.depends('fee_structure_ids', 'fee_structure_ids.amount_inclusive',
                 'fee_structure_ids.total_fee_amount', 'fee_structure_ids.fee_type',
                 'fee_structure_ids.installment_ids.amount_inclusive')
    def _compute_fee_summary(self):
        for batch in self:
            lumpsum = admission = installment = registration = exam = material = 0.0
            for fs in batch.fee_structure_ids:
                amt = fs.total_fee_amount if fs.fee_type == 'installment' else fs.amount_inclusive
                if fs.fee_type == 'lumpsum':
                    lumpsum += fs.amount_inclusive
                elif fs.fee_type == 'admission':
                    admission += fs.amount_inclusive
                elif fs.fee_type == 'installment':
                    installment += fs.total_fee_amount or sum(fs.installment_ids.mapped('amount_inclusive'))
                elif fs.fee_type == 'registration':
                    registration += fs.amount_inclusive
                elif fs.fee_type == 'exam':
                    exam += fs.amount_inclusive
                elif fs.fee_type == 'material':
                    material += fs.amount_inclusive
                else:
                    lumpsum += fs.amount_inclusive

            batch.fee_lumpsum = lumpsum
            batch.fee_admission = admission
            batch.fee_installment = installment
            batch.fee_registration = registration
            batch.fee_exam = exam
            batch.fee_material = material
            batch.total_lumpsum_package = lumpsum + admission
            batch.total_installment_package = installment + admission
            batch.has_installment_fee = installment > 0
            batch.has_lumpsum_fee = lumpsum > 0
