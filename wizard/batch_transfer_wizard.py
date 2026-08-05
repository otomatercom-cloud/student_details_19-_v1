from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class BatchTransferWizard(models.TransientModel):
    _name = 'batch.transfer.wizard'
    _description = 'Batch Transfer Wizard'

    student_id = fields.Many2one('student.details', required=True, readonly=True)
    from_batch_id = fields.Many2one('student.batch', string='Current Batch',
                                     readonly=True)
    to_batch_id = fields.Many2one(
        'student.batch', string='Transfer To Batch', required=True,
        domain="[('active','=',True),('id','!=',from_batch_id)]"
    )
    transfer_date = fields.Date(default=fields.Date.today, required=True)
    reason = fields.Text(string='Reason for Transfer')
    notes = fields.Text(string='Notes')

    # Info display
    student_photo = fields.Image(related='student_id.photo', readonly=True)
    student_phone = fields.Char(related='student_id.phone', readonly=True)
    student_roll_no = fields.Char(related='student_id.roll_no', readonly=True)
    current_join_date = fields.Date(related='student_id.current_batch_join_date',
                                     readonly=True, string='Joined On')
    transfer_count = fields.Integer(related='student_id.transfer_count', readonly=True)

    from_batch_student_count = fields.Integer(compute='_compute_counts')
    to_batch_student_count = fields.Integer(compute='_compute_counts')

    @api.depends('from_batch_id', 'to_batch_id')
    def _compute_counts(self):
        for rec in self:
            rec.from_batch_student_count = len(rec.from_batch_id.student_ids) if rec.from_batch_id else 0
            rec.to_batch_student_count = len(rec.to_batch_id.student_ids) if rec.to_batch_id else 0

    def action_confirm_transfer(self):
        self.ensure_one()
        student = self.student_id
        join_date = student.current_batch_join_date

        self.env['batch.transfer.history'].create({
            'student_id': student.id,
            'from_batch_id': self.from_batch_id.id,
            'to_batch_id': self.to_batch_id.id,
            'join_date': join_date,
            'transfer_date': self.transfer_date,
            'transferred_by': self.env.user.id,
            'reason': self.reason,
            'notes': self.notes,
        })

        student.write({
            'batch_id': self.to_batch_id.id,
            'current_batch_join_date': self.transfer_date,
        })

        # Mark old enrollment as dropped
        self.env['student.enrollment'].search([
            ('student_id', '=', student.id),
            ('batch_id', '=', self.from_batch_id.id),
            ('status', '=', 'enrolled'),
        ], limit=1).write({'status': 'dropped'})

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('✅ Transfer Complete'),
                'message': _(
                    f'{student.name} transferred: '
                    f'{self.from_batch_id.name} → {self.to_batch_id.name}'
                ),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
