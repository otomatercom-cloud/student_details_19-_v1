from odoo import api, fields, models

REG_PREFIX_KEY = 'student_details.registration.prefix'


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    student_registration_prefix = fields.Char(
        string='Registration Prefix Letters',
        config_parameter=REG_PREFIX_KEY,
        default='ANJ',
    )
    student_registration_next_number = fields.Integer(
        string='Next Serial Number',
        compute='_compute_student_registration_next_number',
        inverse='_inverse_student_registration_next_number',
        help='Serial counter continues across financial years. '
             'Only the year segment in the number changes each April.',
    )

    def _get_registration_sequence(self):
        return self.env['ir.sequence'].sudo().search([
            ('code', '=', 'student.registration.serial'),
            '|', ('company_id', '=', False), ('company_id', '=', self.env.company.id),
        ], order='company_id desc', limit=1)

    @api.depends('company_id')
    def _compute_student_registration_next_number(self):
        for settings in self:
            sequence = settings._get_registration_sequence()
            settings.student_registration_next_number = (
                getattr(sequence, 'number_next_actual', None) or sequence.number_next
            ) if sequence else 1

    def _inverse_student_registration_next_number(self):
        for settings in self:
            sequence = settings._get_registration_sequence()
            if sequence and settings.student_registration_next_number:
                sequence.sudo().number_next = settings.student_registration_next_number

    def action_load_demo_data(self):
        self.env['student.demo.data'].load()
        return {'type': 'ir.actions.client', 'tag': 'display_notification', 'params': {
            'title': 'Demo data loaded', 'type': 'success', 'sticky': True,
            'message': 'Login: demo.<role>@demo.otomater.com / Demo@1234 (see the demo guide).'}}

    def action_remove_demo_data(self):
        archived = self.env['student.demo.data'].remove()
        msg = 'All demo records removed.'
        if archived:
            msg += ' Archived (have history): ' + ', '.join(archived[:6])
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'title': 'Demo data removed', 'message': msg, 'type': 'warning', 'sticky': True}}
