from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class BatchTransferHistory(models.Model):
    _name = 'batch.transfer.history'
    _description = 'Batch Transfer History'
    _order = 'transfer_date desc, id desc'
    _rec_name = 'display_name'

    display_name = fields.Char(compute='_compute_display_name', store=True)
    student_id = fields.Many2one('student.details', required=True,
                                  ondelete='cascade', index=True)
    from_batch_id = fields.Many2one('student.batch', string='From Batch',
                                     required=True, ondelete='restrict')
    to_batch_id = fields.Many2one('student.batch', string='To Batch',
                                   required=True, ondelete='restrict')
    join_date = fields.Date(string='Joined From-Batch On')
    transfer_date = fields.Date(string='Transfer Date',
                                 default=fields.Date.today, required=True)
    transferred_by = fields.Many2one('res.users', string='Transferred By',
                                      default=lambda self: self.env.user, readonly=True)
    reason = fields.Text(string='Reason')
    notes = fields.Text(string='Notes')

    @api.depends('student_id', 'from_batch_id', 'to_batch_id', 'transfer_date')
    def _compute_display_name(self):
        for rec in self:
            s = rec.student_id.name or ''
            f = rec.from_batch_id.name or ''
            t = rec.to_batch_id.name or ''
            d = str(rec.transfer_date) if rec.transfer_date else ''
            rec.display_name = f'{s} | {f} → {t} | {d}'

    @api.constrains('from_batch_id', 'to_batch_id')
    def _check_different(self):
        for rec in self:
            if rec.from_batch_id == rec.to_batch_id:
                raise ValidationError(_('From Batch and To Batch must be different.'))


class StudentTransferInherit(models.Model):
    _inherit = 'student.details'

    transfer_history_ids = fields.One2many(
        'batch.transfer.history', 'student_id', string='Transfer History'
    )
    transfer_count = fields.Integer(
        compute='_compute_transfer_count', store=True, string='Transfers'
    )
    current_batch_join_date = fields.Date(string='Joined Current Batch On')

    @api.depends('transfer_history_ids')
    def _compute_transfer_count(self):
        for rec in self:
            rec.transfer_count = len(rec.transfer_history_ids)

    def action_batch_transfer(self):
        self.ensure_one()
        if not self.batch_id:
            raise ValidationError(
                _('Student is not assigned to any batch. Please enroll first.')
            )
        return {
            'type': 'ir.actions.act_window',
            'name': 'Batch Transfer',
            'res_model': 'batch.transfer.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_student_id': self.id,
                'default_from_batch_id': self.batch_id.id,
            },
        }
