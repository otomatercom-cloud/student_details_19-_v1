from datetime import date

from odoo import api, models


class StudentSaasDashboard(models.Model):
    _inherit = 'student.batch'

    @api.model
    def get_saas_dashboard(self):
        Batch = self.env['student.batch'].sudo()
        Enrollment = self.env['student.enrollment'].sudo()
        Student = self.env['student.details'].sudo()

        batches = Batch.search([('active', '=', True)])
        today = date.today()

        # "Live" = active AND currently within its date range (started,
        # not yet ended). A batch with no end_date is treated as
        # ongoing/live once started.
        def is_live(b):
            if b.start_date and b.start_date > today:
                return False
            if b.end_date and b.end_date < today:
                return False
            return True

        live_batches = batches.filtered(is_live)

        total_students = Student.search_count([('active', '=', True)])

        enrollments = Enrollment.search([])
        fully_paid_students = enrollments.filtered(lambda e: e.payment_status == 'paid').mapped('student_id')
        pending_students = enrollments.filtered(
            lambda e: e.payment_status in ('unpaid', 'partial')).mapped('student_id')
        dropped_students = enrollments.filtered(lambda e: e.status == 'dropped').mapped('student_id')

        total_paid = sum(enrollments.mapped('paid_amount'))
        total_due = sum(enrollments.mapped('due_amount'))

        batch_rows = []
        for b in batches:
            b_enrollments = enrollments.filtered(lambda e: e.batch_id.id == b.id)
            batch_rows.append({
                'batch_id': b.id,
                'batch_name': b.name,
                'student_count': b.student_count,
                'is_live': b in live_batches,
                'fully_paid_count': len(b_enrollments.filtered(
                    lambda e: e.payment_status == 'paid').mapped('student_id')),
                'pending_count': len(b_enrollments.filtered(
                    lambda e: e.payment_status in ('unpaid', 'partial')).mapped('student_id')),
                'dropped_count': len(b_enrollments.filtered(
                    lambda e: e.status == 'dropped').mapped('student_id')),
                'paid_amount': sum(b_enrollments.mapped('paid_amount')),
                'due_amount': sum(b_enrollments.mapped('due_amount')),
            })
        batch_rows.sort(key=lambda r: -r['student_count'])

        return {
            'total_students': total_students,
            'total_batches': len(batches),
            'live_batches': len(live_batches),
            'fully_paid_count': len(fully_paid_students),
            'pending_payment_count': len(pending_students),
            'dropped_count': len(dropped_students),
            'total_paid': round(total_paid, 2),
            'total_due': round(total_due, 2),
            'batches': batch_rows,
        }
