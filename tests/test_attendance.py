from unittest.mock import MagicMock, patch

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAttendance(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.batch = cls.env['student.batch'].create({'name': 'T-Batch'})
        Student = cls.env['student.details']
        cls.s1 = Student.create({'name': 'Anu', 'branch': 'kochi', 'batch_id': cls.batch.id,
                                 'whatsapp_number': '98765 43210'})
        cls.s2 = Student.create({'name': 'Ben', 'branch': 'kochi', 'batch_id': cls.batch.id,
                                 'father_phone': '+91 91234-56789'})
        cls.s3 = Student.create({'name': 'Cia', 'branch': 'kochi', 'batch_id': cls.batch.id})
        icp = cls.env['ir.config_parameter'].sudo()
        icp.set_param('student_details.att_wa.enabled', 'True')
        icp.set_param('student_details.att_wa.provider', 'gateway')
        icp.set_param('student_details.att_wa.gateway_url', 'https://gw.example.com/send')

    def _sheet(self, day='2026-10-01', session='full_day'):
        return self.env['st.attendance'].create({
            'batch_id': self.batch.id, 'date': day, 'session': session})

    def test_01_lines_created_and_unique(self):
        sheet = self._sheet()
        self.assertEqual(len(sheet.attendance_line_ids), 3)
        self.assertEqual(sheet.total_students, 3)
        with self.assertRaises(Exception), self.cr.savepoint():
            self._sheet()
        self.assertTrue(self._sheet(session='morning'))

    def test_02_counts_percentage_and_stats(self):
        sheet = self._sheet()
        by = {l.student_id: l for l in sheet.attendance_line_ids}
        by[self.s1].status = 'absent'
        by[self.s2].status = 'late'
        by[self.s3].status = 'leave'
        self.assertEqual((sheet.absent_count, sheet.late_count, sheet.leave_count), (1, 1, 1))
        sheet.action_lock()
        stats = self.env['st.attendance.line'].get_student_stats(
            [self.s1.id, self.s2.id, self.s3.id])
        self.assertEqual(stats[self.s1.id]['percentage'], 0.0)
        self.assertEqual(stats[self.s2.id]['percentage'], 100.0)   # late counts present
        self.assertEqual(stats[self.s3.id]['working_days'], 0)     # leave excluded
        self.s1.att_start_date = '2026-10-01'
        self.s1.att_end_date = '2026-10-31'
        self.assertEqual(self.s1.absent_days, 1)
        self.assertEqual(self.s1.total_days, 1)

    def test_03_half_day_weight(self):
        sheet = self._sheet()
        sheet.attendance_line_ids.filtered(lambda l: l.student_id == self.s1).status = 'half_day'
        sheet.action_lock()
        stats = self.env['st.attendance.line'].get_student_stats([self.s1.id])
        self.assertEqual(stats[self.s1.id]['percentage'], 50.0)

    def test_04_unlock_requires_manager(self):
        sheet = self._sheet()
        sheet.action_lock()
        user = self.env['res.users'].create({
            'name': 'Plain', 'login': 'plain_att', 'group_ids': [(6, 0, [self.env.ref('base.group_user').id])]})
        with self.assertRaises(UserError):
            sheet.with_user(user).action_unlock()
        sheet.action_unlock()
        self.assertEqual(sheet.state, 'draft')

    def test_05_whatsapp_queue_and_send(self):
        Log = self.env['otm.attendance.whatsapp.log']
        sheet = self._sheet()
        for line in sheet.attendance_line_ids:
            line.status = 'absent'
        sheet.action_lock()
        logs = Log.search([('attendance_id', '=', sheet.id)])
        self.assertEqual(len(logs), 3)
        by_student = {l.student_id: l for l in logs}
        self.assertEqual(by_student[self.s1].number, '919876543210')
        self.assertEqual(by_student[self.s2].number, '919123456789')
        self.assertEqual(by_student[self.s3].state, 'skipped')       # no number
        self.assertIn('Anu', by_student[self.s1].message)
        # re-lock cycle must not duplicate
        sheet.action_unlock()
        sheet.action_lock()
        self.assertEqual(Log.search_count([('attendance_id', '=', sheet.id)]), 3)

        ok = MagicMock(ok=True, status_code=200)
        ok.json.return_value = {'success': True, 'id': 'abc'}
        with patch('odoo.addons.student_details_19.models.attendance_whatsapp.requests.post',
                   return_value=ok) as post:
            sent = logs._process_queue()
        self.assertEqual(sent, 2)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(by_student[self.s1].state, 'sent')

    def test_06_whatsapp_failure_retry_limit(self):
        Log = self.env['otm.attendance.whatsapp.log']
        sheet = self._sheet()
        sheet.attendance_line_ids.filtered(lambda l: l.student_id == self.s1).status = 'absent'
        sheet.action_lock()
        log = Log.search([('attendance_id', '=', sheet.id)])
        bad = MagicMock(ok=False, status_code=500, text='boom')
        with patch('odoo.addons.student_details_19.models.attendance_whatsapp.requests.post',
                   return_value=bad):
            for _i in range(3):
                log._process_queue()
        self.assertEqual(log.state, 'failed')
        self.assertEqual(log.retries, 3)

    def test_07_opt_out_and_disabled(self):
        Log = self.env['otm.attendance.whatsapp.log']
        self.s1.att_wa_opt_out = True
        sheet = self._sheet()
        sheet.attendance_line_ids.filtered(lambda l: l.student_id == self.s1).status = 'absent'
        sheet.action_lock()
        self.assertFalse(Log.search([('attendance_id', '=', sheet.id)]))
        self.env['ir.config_parameter'].sudo().set_param('student_details.att_wa.enabled', 'False')
        sheet2 = self._sheet(day='2026-10-02')
        sheet2.attendance_line_ids.status = 'absent'
        sheet2.action_lock()
        self.assertFalse(Log.search([('attendance_id', '=', sheet2.id)]))

    def test_08_report_wizard_and_low_alert(self):
        sheet = self._sheet()
        sheet.attendance_line_ids.filtered(lambda l: l.student_id == self.s2).status = 'absent'
        sheet.action_lock()
        wiz = self.env['attendance.report.wizard'].create({
            'batch_id': self.batch.id, 'start_date': '2026-10-01',
            'end_date': '2026-10-31', 'threshold': 75})
        action = wiz.action_generate_report()
        result = self.env['attendance.report.result'].browse(action['res_id'])
        self.assertEqual(result.low_count, 1)
        self.assertEqual(result.line_ids.filtered('is_low').student_id, self.s2)
        res = result.action_send_low_attendance_whatsapp()
        self.assertEqual(res['tag'], 'display_notification')
        logs = self.env['otm.attendance.whatsapp.log'].search(
            [('message_type', '=', 'low_attendance')])
        self.assertEqual(len(logs), 1)
        self.assertIn('0.0%', logs.message)
        result.action_send_low_attendance_whatsapp()    # idempotent
        self.assertEqual(self.env['otm.attendance.whatsapp.log'].search_count(
            [('message_type', '=', 'low_attendance')]), 1)

    def test_09_message_render_is_safe(self):
        from odoo.addons.student_details_19.models.attendance_whatsapp import render_message
        out = render_message('Hi {student} {__class__.__mro__} {unknown}', {'student': 'Z'})
        self.assertEqual(out, 'Hi Z {__class__.__mro__} {unknown}')

    def test_10_meta_template_payload(self):
        icp = self.env['ir.config_parameter'].sudo()
        icp.set_param('student_details.att_wa.provider', 'meta')
        icp.set_param('student_details.att_wa.meta_phone_id', '123')
        icp.set_param('student_details.att_wa.meta_token', 'tok')
        icp.set_param('student_details.att_wa.absent_template', 'att_absent')
        sheet = self._sheet()
        sheet.attendance_line_ids.filtered(lambda l: l.student_id == self.s1).status = 'absent'
        sheet.action_lock()
        log = self.env['otm.attendance.whatsapp.log'].search([('attendance_id', '=', sheet.id)])
        self.assertEqual(log.template_name, 'att_absent')
        ok = MagicMock(ok=True, status_code=200)
        ok.json.return_value = {'messages': [{'id': 'wamid.1'}]}
        with patch('odoo.addons.student_details_19.models.attendance_whatsapp.requests.post',
                   return_value=ok) as post:
            log._process_queue()
        body = post.call_args.kwargs['json']
        self.assertEqual(body['type'], 'template')
        self.assertEqual(body['template']['name'], 'att_absent')
        self.assertEqual(body['template']['components'][0]['parameters'][0]['text'], 'Anu')
        self.assertEqual(log.state, 'sent')
