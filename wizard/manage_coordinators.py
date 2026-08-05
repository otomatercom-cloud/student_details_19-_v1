from odoo import models, fields, api, _
from odoo.exceptions import UserError


class ManageCoordinators(models.TransientModel):
    _name = 'manage.coordinators'
    _description = 'Manage Coordinators'

    coordinator_type = fields.Selection([
        ('academic', 'Academic Coordinators'),
        ('course', 'Course Coordinators'),
        ('tl', 'TL Admission'),
        ('admission', 'Admission Officer'),
    ], string='Coordinator Type', required=True)

    user_ids = fields.Many2many('res.users', string='Coordinators')

    def _get_group(self, coordinator_type):
        ref_map = {
            'academic': 'student_details_19.group_academic_coordinator',
            'course':   'student_details_19.group_course_coordinator',
            'tl':       'student_details_19.group_tl_admission',
            'admission':'student_details_19.group_admission_officer',
        }
        ref = ref_map.get(coordinator_type)
        return self.env.ref(ref, raise_if_not_found=False) if ref else False

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        coordinator_type = self.env.context.get('default_coordinator_type')
        group = self._get_group(coordinator_type)
        if group:
            res['user_ids'] = [(6, 0, group.users.ids)]
        return res

    def action_save(self):
        self.ensure_one()
        group = self._get_group(self.coordinator_type)
        if not group:
            raise UserError(_('Valid coordinator type not selected.'))
        group.write({'users': [(6, 0, self.user_ids.ids)]})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'message': _('Coordinators updated successfully.'),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
