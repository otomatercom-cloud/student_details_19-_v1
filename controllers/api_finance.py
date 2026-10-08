"""Finance / enrollment / transfer / sync endpoints for the Next.js frontend."""
from odoo import fields, http, _
from odoo.exceptions import UserError, ValidationError
from odoo.http import request

from .api import api, P  # noqa: F401  (decorator shared with the main API)

FEE_TYPES = [('lumpsum', 'Lump Sum'), ('installment', 'Installment'), ('monthly', 'Monthly'),
             ('quarterly', 'Quarterly'), ('semi_annual', 'Semi-Annual'), ('annual', 'Annual'),
             ('admission', 'Admission Fee'), ('exam', 'Exam Fee'), ('material', 'Material Fee'),
             ('registration', 'Registration Fee')]
GST_RATES = ['0', '5', '12', '18', '28']


def _fee_dict(f, full=False):
    d = {
        'id': f.id, 'name': f.name, 'fee_type': f.fee_type, 'gst_rate': f.gst_rate, 'active': f.active,
        'amount_entry_mode': f.amount_entry_mode,
        'amount_inclusive': f.amount_inclusive, 'amount_exclusive': f.amount_exclusive,
        'tax_amount': f.tax_amount,
        'total': f.total_fee_amount if f.fee_type == 'installment' else f.amount_inclusive,
        'installment_count': f.installment_count,
        'batches': [{'id': b.id, 'name': b.name} for b in f.batch_ids],
    }
    if full:
        d.update({
            'description': f.description or '', 'total_fee_amount': f.total_fee_amount,
            'num_installments': f.num_installments,
            'first_due_date': fields.Date.to_string(f.first_due_date) if f.first_due_date else '',
            'installment_balance': f.installment_balance,
            'installments': [{'id': i.id, 'name': i.name, 'amount_inclusive': i.amount_inclusive,
                              'due_date': fields.Date.to_string(i.due_date) if i.due_date else ''}
                             for i in f.installment_ids.sorted('sequence')],
        })
    return d


def _payment_dict(p):
    return {
        'id': p.id, 'date': fields.Date.to_string(p.payment_date) if p.payment_date else '',
        'amount': p.amount, 'mode': p.payment_mode or '', 'receipt_no': p.receipt_no or '',
        'remarks': p.remarks or '', 'source': p.payment_source,
        'razorpay_status': p.razorpay_status or '', 'short_url': p.razorpay_short_url or '',
        'amount_received': p.amount_received,
    }


def _enrollment_dict(e):
    return {
        'id': e.id, 'batch': {'id': e.batch_id.id, 'name': e.batch_id.name},
        'fees': [{'id': f.id, 'name': f.name, 'fee_type': f.fee_type}
                 for f in (e.fee_structure_ids or e.fee_structure_id)],
        'enrollment_date': fields.Date.to_string(e.enrollment_date) if e.enrollment_date else '',
        'status': e.status, 'total_fee': e.total_fee, 'paid': e.paid_amount, 'due': e.due_amount,
        'payment_status': e.payment_status,
        'next_due_date': fields.Date.to_string(e.next_due_date) if e.next_due_date else '',
        'payments': [_payment_dict(p) for p in e.payment_ids.sorted(lambda x: (x.payment_date or fields.Date.today(), x.id), reverse=True)],
    }


def _fee_vals(body, rec=None):
    """Derive stored amounts exactly like the form's onchange does."""
    vals = {k: body[k] for k in ('name', 'fee_type', 'gst_rate', 'amount_entry_mode', 'active',
                                 'description', 'num_installments') if k in body}
    if vals.get('fee_type') and vals['fee_type'] not in dict(FEE_TYPES):
        raise ValidationError(_("Invalid fee type."))
    if vals.get('gst_rate') and vals['gst_rate'] not in GST_RATES:
        raise ValidationError(_("Invalid GST rate."))
    rate = float(vals.get('gst_rate') or (rec.gst_rate if rec else '18'))
    mode = vals.get('amount_entry_mode') or (rec.amount_entry_mode if rec else 'inclusive')
    fee_type = vals.get('fee_type') or (rec.fee_type if rec else 'lumpsum')
    if fee_type == 'installment':
        total = float(body.get('total_fee_amount') or 0)
        vals['total_fee_amount'] = total
        vals['amount_inclusive'] = total
        vals['amount_exclusive'] = round(total / (1 + rate / 100), 2)
    elif 'amount_inclusive' in body or 'amount_exclusive' in body:
        if mode == 'exclusive':
            excl = float(body.get('amount_exclusive') or 0)
            vals['amount_exclusive'] = excl
            vals['amount_inclusive'] = round(excl * (1 + rate / 100), 2)
        else:
            incl = float(body.get('amount_inclusive') or 0)
            vals['amount_inclusive'] = incl
            vals['amount_exclusive'] = round(incl / (1 + rate / 100), 2)
    if 'first_due_date' in body:
        vals['first_due_date'] = body['first_due_date'] or False
    if 'batch_ids' in body:
        vals['batch_ids'] = [(6, 0, [int(i) for i in body['batch_ids'] or []])]
    return vals, rate


class SdmFinanceApi(http.Controller):

    # -------------------------------------------------------------------- fees
    @api('/fees/meta')
    def fees_meta(self, body=None):
        return {'fee_types': [{'value': k, 'label': v} for k, v in FEE_TYPES],
                'gst_rates': GST_RATES}

    @api('/fees')
    def fees(self, body=None, batch_id=None, **kw):
        domain = [('batch_ids', 'in', int(batch_id))] if batch_id else []
        rows = request.env['fee.structure'].with_context(active_test=False).search(domain)
        return [_fee_dict(f) for f in rows]

    @api('/fees/<int:fee_id>')
    def fee_get(self, fee_id, body=None, **kw):
        f = request.env['fee.structure'].with_context(active_test=False).browse(fee_id)
        f.check_access('read')
        return _fee_dict(f, full=True)

    @api('/fees/save', methods=('POST',))
    def fee_save(self, body=None):
        Fee = request.env['fee.structure'].with_context(active_test=False)
        rec = Fee.browse(int(body['id'])) if body.get('id') else None
        vals, rate = _fee_vals(body, rec)
        fee_type = vals.get('fee_type') or (rec.fee_type if rec else 'lumpsum')
        installments = body.get('installments')
        # The model requires >=1 installment for installment fees, so the type is applied last.
        if fee_type == 'installment':
            vals['fee_type'] = rec.fee_type if rec else 'lumpsum'
        if rec:
            rec.write(vals)
        else:
            if not (vals.get('name') or '').strip():
                raise ValidationError(_("Fee name is required."))
            rec = Fee.create(vals)
        if fee_type == 'installment':
            if installments:
                rec.installment_ids.unlink()
                for i, row in enumerate(installments, start=1):
                    amt = round(float(row.get('amount_inclusive') or 0), 2)
                    request.env['fee.installment'].create({
                        'fee_structure_id': rec.id, 'sequence': i * 10,
                        'name': row.get('name') or '%s Installment' % i,
                        'due_date': row.get('due_date') or False,
                        'amount_inclusive': amt, 'amount_exclusive': round(amt / (1 + rate / 100), 2)})
                if abs(rec.installment_balance) > 0.01:
                    raise ValidationError(_("Installments must add up to the total fee (difference: %s).",
                                            rec.installment_balance))
            elif body.get('auto_split') or not rec.installment_ids:
                if not rec.first_due_date:
                    rec.first_due_date = fields.Date.today()
                rec.action_auto_split()
            rec.write({'fee_type': 'installment'})
        return _fee_dict(rec, full=True)

    # -------------------------------------------------------------- enrollment
    @api('/students/<int:student_id>/finance')
    def student_finance(self, student_id, body=None, **kw):
        s = request.env['student.details'].browse(student_id)
        s.check_access('read')
        return {
            'wallet': {'total': s.wallet_total_fee, 'paid': s.wallet_paid, 'due': s.wallet_due,
                       'status': s.wallet_status,
                       'next_due': fields.Date.to_string(s.wallet_next_due) if s.wallet_next_due else ''},
            'enrollments': [_enrollment_dict(e) for e in s.enrollment_ids],
            'transfers': [{'id': t.id, 'from': t.from_batch_id.name, 'to': t.to_batch_id.name,
                           'date': fields.Date.to_string(t.transfer_date), 'reason': t.reason or '',
                           'by': t.transferred_by.name or ''} for t in s.transfer_history_ids.sorted('transfer_date', reverse=True)],
        }

    @api('/enroll', methods=('POST',))
    def enroll(self, body=None):
        env = request.env
        wiz = env['enrollment.wizard'].create({
            'student_id': int(body['student_id']), 'batch_id': int(body['batch_id']),
            'fee_structure_ids': [(6, 0, [int(i) for i in body.get('fee_ids') or []])]})
        total = wiz.grand_total_display
        wiz.action_confirm_enrollment()
        enr = env['student.enrollment'].search([('student_id', '=', int(body['student_id'])),
                                                ('batch_id', '=', int(body['batch_id']))], order='id desc', limit=1)
        return {'enrollment_id': enr.id, 'total': total}

    @api('/enrollments')
    def enrollments(self, body=None, payment_status=None, status='enrolled', batch_id=None, **kw):
        domain = []
        if status:
            domain.append(('status', '=', status))
        if payment_status:
            domain.append(('payment_status', '=', payment_status))
        if batch_id:
            domain.append(('batch_id', '=', int(batch_id)))
        rows = request.env['student.enrollment'].search(domain, limit=200, order='due_amount desc')
        out = []
        for e in rows:
            d = _enrollment_dict(e)
            d['student'] = {'id': e.student_id.id, 'name': e.student_id.name,
                            'phone': e.student_id.phone or ''}
            d.pop('payments')
            out.append(d)
        return out

    @api('/enrollments/<int:enr_id>/payment', methods=('POST',))
    def add_payment(self, enr_id, body=None, **kw):
        enr = request.env['student.enrollment'].browse(enr_id)
        enr.check_access('write')
        amount = float(body.get('amount') or 0)
        if amount <= 0:
            raise ValidationError(_("Payment amount must be positive."))
        pay = request.env['student.fee.payment'].create({
            'enrollment_id': enr.id, 'amount': amount,
            'payment_date': body.get('payment_date') or fields.Date.today(),
            'payment_mode': body.get('payment_mode') or 'cash',
            'receipt_no': (body.get('receipt_no') or '')[:100], 'remarks': (body.get('remarks') or '')[:200]})
        return {'payment_id': pay.id, 'due': enr.due_amount, 'payment_status': enr.payment_status}

    @api('/enrollments/<int:enr_id>/status', methods=('POST',))
    def enrollment_status(self, enr_id, body=None, **kw):
        if body.get('status') not in ('enrolled', 'completed', 'dropped'):
            raise ValidationError(_("Invalid status."))
        request.env['student.enrollment'].browse(enr_id).write({'status': body['status']})
        return {'ok': True}

    @api('/enrollments/<int:enr_id>/razorpay', methods=('POST',))
    def enrollment_razorpay(self, enr_id, body=None, **kw):
        enr = request.env['student.enrollment'].browse(enr_id)
        enr.check_access('write')
        enr.action_generate_payment_link()
        pay = enr.payment_ids.filtered(lambda p: p.payment_source == 'razorpay').sorted('id')[-1:]
        return {'payment': _payment_dict(pay)}

    @api('/payments/<int:pay_id>/refresh', methods=('POST',))
    def payment_refresh(self, pay_id, body=None, **kw):
        pay = request.env['student.fee.payment'].browse(pay_id)
        pay.action_refresh_razorpay_status()
        return _payment_dict(pay)

    @api('/payments/<int:pay_id>/mark-paid', methods=('POST',))
    def payment_mark_paid(self, pay_id, body=None, **kw):
        pay = request.env['student.fee.payment'].browse(pay_id)
        pay.action_mark_paid_manually()
        return _payment_dict(pay)

    # ---------------------------------------------------------------- transfer
    @api('/students/<int:student_id>/transfer', methods=('POST',))
    def transfer(self, student_id, body=None, **kw):
        s = request.env['student.details'].browse(student_id)
        if not s.batch_id:
            raise UserError(_("This student has no current batch."))
        wiz = request.env['batch.transfer.wizard'].create({
            'student_id': s.id, 'from_batch_id': s.batch_id.id,
            'to_batch_id': int(body['to_batch_id']),
            'transfer_date': body.get('transfer_date') or fields.Date.today(),
            'reason': body.get('reason') or False, 'notes': body.get('notes') or False})
        wiz.action_confirm_transfer()
        return {'batch': s.batch_id.name}

    # ------------------------------------------------- student 360 (read-only)
    @api('/students/<int:student_id>/overview')
    def student_overview(self, student_id, body=None, **kw):
        env = request.env
        s = env['student.details'].browse(student_id)
        s.check_access('read')
        stats = env['st.attendance.line'].get_student_stats([s.id])[s.id]
        lines = env['st.attendance.line'].search(
            [('student_id', '=', s.id), ('attendance_state', '=', 'locked')], limit=15, order='date desc')
        marks = env['otm.exam.line'].search(
            [('student_id', '=', s.id), ('exam_id.state', '=', 'published')], limit=30, order='id desc')
        return {
            'attendance': {**{k: stats[k] for k in ('present', 'late', 'half_day', 'absent', 'leave', 'working_days')},
                           'percentage': round(stats['percentage'], 1),
                           'recent': [{'date': fields.Date.to_string(l.date), 'session': l.session,
                                       'status': l.status, 'batch': l.batch_id.name} for l in lines]},
            'marks': [{'exam': m.exam_id.title, 'subject': m.exam_id.subject,
                       'date': fields.Date.to_string(m.exam_id.exam_date), 'status': m.status,
                       'marks': m.marks, 'max': m.exam_id.max_marks, 'percentage': round(m.percentage, 1),
                       'result': m.result, 'rank': m.rank} for m in marks],
            'account': {'portal_login': s.portal_user_id.login or '', 'portal_state': s.portal_sync_state or '',
                        'portal_message': s.portal_sync_message or '', 'moodle_username': s.moodle_username or '',
                        'moodle_user_id': s.moodle_user_id or 0},
        }

    @api('/students/<int:student_id>/sync-moodle', methods=('POST',))
    def sync_moodle(self, student_id, body=None, **kw):
        s = request.env['student.details'].browse(student_id)
        s.check_access('write')
        s.action_sync_moodle_and_portal()
        return {'portal_login': s.portal_user_id.login or '', 'portal_state': s.portal_sync_state or '',
                'portal_message': s.portal_sync_message or '', 'moodle_username': s.moodle_username or ''}

    @api('/finance/summary')
    def finance_summary(self, body=None):
        Enr = request.env['student.enrollment']
        active = Enr.search([('status', '=', 'enrolled')])
        return {'total': sum(active.mapped('total_fee')), 'collected': sum(active.mapped('paid_amount')),
                'due': sum(active.mapped('due_amount')),
                'unpaid': len(active.filtered(lambda e: e.payment_status == 'unpaid')),
                'partial': len(active.filtered(lambda e: e.payment_status == 'partial')),
                'paid': len(active.filtered(lambda e: e.payment_status == 'paid'))}
