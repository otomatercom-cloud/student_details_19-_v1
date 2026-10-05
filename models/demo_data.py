"""Demo data loader / remover for Student Details.

Creates demo users for every role, courses, batches, fee structures,
~30 students, enrollments with payments (paid / partial / unpaid), batch
transfers and locked attendance, so the module can be demonstrated
without real data.  Everything is registered as ir.model.data
`student_details_19.demo_*` so `remove()` deletes exactly what was created.
"""
import random
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import AccessError

MODULE = 'student_details_19'
DEMO_PASSWORD = 'Demo@1234'
DOMAIN = 'demo.otomater.com'

G = lambda x: 'student_details_19.group_' + x
DEMO_USERS = [
    ('manager', 'Demo Student Manager', ['student_manager']),
    ('tl', 'Demo TL Admission', ['tl_admission']),
    ('ao1', 'Rahul Menon (Admission Officer)', ['admission_officer']),
    ('ao2', 'Anjali Pillai (Admission Officer)', ['admission_officer']),
    ('ac1', 'Demo Academic Coordinator 1', ['academic_coordinator']),
    ('ac2', 'Demo Academic Coordinator 2', ['academic_coordinator']),
    ('cc1', 'Demo Course Coordinator 1', ['course_coordinator']),
    ('cc2', 'Demo Course Coordinator 2', ['course_coordinator']),
]
COURSES = [('ca', 'Demo - CA Foundation', 'DCAF', 'cc1'), ('acca', 'Demo - ACCA', 'DACCA', 'cc1'),
           ('cma', 'Demo - CMA USA', 'DCMA', 'cc2'), ('dm', 'Demo - Digital Marketing', 'DDM', 'cc2')]
# key, name, course keys, start offset (days), end offset, coordinator
BATCHES = [('b_ca', 'Demo CA Foundation - Morning 2026', ['ca'], -60, 120, 'ac1'),
           ('b_acca', 'Demo ACCA - Weekend 2026', ['acca'], -30, 200, 'ac1'),
           ('b_cma', 'Demo CMA USA - Evening 2026', ['cma'], -45, 150, 'ac2'),
           ('b_dm', 'Demo Digital Marketing - Oct 2026', ['dm'], 10, 100, 'ac2'),
           ('b_old', 'Demo CA Foundation - 2025 (Completed)', ['ca'], -300, -20, 'ac1')]
FIRST = ['Aswin', 'Meera', 'Nikhil', 'Sneha', 'Adithya', 'Lakshmi', 'Vishnu', 'Gayathri', 'Akhil', 'Remya',
         'Jishnu', 'Athira', 'Midhun', 'Parvathy', 'Sanjay', 'Keerthi', 'Basil', 'Nimisha', 'Abhijith', 'Devika']
LAST = ['Nair', 'Menon', 'Kurian', 'Thomas', 'Varghese', 'Pillai', 'Krishnan', 'Joseph', 'Mathew', 'Das']
DISTRICTS = ['Ernakulam', 'Kozhikode', 'Thrissur', 'Kannur', 'Palakkad', 'Kottayam', 'Malappuram', 'Alappuzha']
BRANCHES = ['kochi', 'calicut', 'kottayam', 'trivandrum', 'online']
MODES = ['cash', 'upi', 'neft', 'card']


class StudentDemoData(models.AbstractModel):
    _name = 'student.demo.data'
    _description = 'Student Details Demo Data Loader'

    @api.model
    def _demo_check_admin(self):
        if not self.env.user.has_group('base.group_system'):
            raise AccessError(_('Only Settings administrators can load or remove demo data.'))

    @api.model
    def _demo_ref(self, key):
        return self.env.ref('%s.demo_%s' % (MODULE, key), raise_if_not_found=False)

    @api.model
    def _demo_reg(self, rec, key):
        self.env['ir.model.data'].sudo().create({
            'module': MODULE, 'name': 'demo_%s' % key, 'model': rec._name,
            'res_id': rec.id, 'noupdate': True})
        return rec

    @api.model
    def _demo_get(self, model, key, vals):
        rec = self._demo_ref(key)
        if rec and rec.exists():
            return rec
        return self._demo_reg(self.env[model].sudo().create(vals), key)

    @api.model
    def load(self):
        self._demo_check_admin()
        env = self.with_context(tracking_disable=True, mail_create_nolog=True,
                                mail_notrigger=True, no_reset_password=True).env
        self = self.with_env(env)
        rnd = random.Random(2026)
        today = fields.Date.today()
        base_user = env.ref('base.group_user')

        users = {}
        for key, name, groups in DEMO_USERS:
            login = 'demo.%s@%s' % (key, DOMAIN)
            user = self._demo_ref('user_' + key)
            if not user or not user.exists():
                gids = [base_user.id] + [env.ref(G(g)).id for g in groups]
                user = env['res.users'].sudo().search([('login', '=', login)], limit=1) or \
                    env['res.users'].sudo().create({
                        'name': name, 'login': login, 'email': login, 'password': DEMO_PASSWORD,
                        'group_ids': [(6, 0, gids)]})
                self._demo_reg(user, 'user_' + key)
            users[key] = user

        courses = {}
        for key, name, code, cc in COURSES:
            courses[key] = self._demo_get('course.master', 'course_' + key, {
                'name': name, 'code': code, 'coordinator_ids': [(6, 0, [users[cc].id])]})

        # fee structures
        fees = {}
        fees['lump'] = self._demo_get('fee.structure', 'fee_lump', {
            'name': 'Demo - Lump Sum Full Course', 'fee_type': 'lumpsum', 'gst_rate': '18',
            'amount_inclusive': 59000.0, 'amount_exclusive': round(59000 / 1.18, 2)})
        total, n = 60000.0, 4
        per = round(total / n, 2)
        lines = []
        for i in range(n):
            amt = per if i < n - 1 else round(total - per * (n - 1), 2)
            lines.append((0, 0, {'sequence': (i + 1) * 10, 'name': '%d%s Installment' % (
                i + 1, ['st', 'nd', 'rd', 'th'][min(i, 3)]),
                'due_date': today + timedelta(days=30 * (i - 1)),
                'amount_inclusive': amt, 'amount_exclusive': round(amt / 1.18, 2)}))
        fees['inst'] = self._demo_get('fee.structure', 'fee_inst', {
            'name': 'Demo - 4 Installments', 'fee_type': 'installment', 'gst_rate': '18',
            'total_fee_amount': total, 'num_installments': n,
            'first_due_date': today - timedelta(days=30),
            'amount_inclusive': total, 'amount_exclusive': round(total / 1.18, 2),
            'installment_ids': lines})
        fees['adm'] = self._demo_get('fee.structure', 'fee_adm', {
            'name': 'Demo - Admission Fee', 'fee_type': 'admission', 'gst_rate': '18',
            'amount_inclusive': 2500.0, 'amount_exclusive': round(2500 / 1.18, 2)})

        batches = {}
        for key, name, ckeys, s, e, ac in BATCHES:
            batches[key] = self._demo_get('student.batch', key, {
                'name': name, 'start_date': today + timedelta(days=s), 'end_date': today + timedelta(days=e),
                'course_ids': [(6, 0, [courses[c].id for c in ckeys])],
                'coordinator_ids': [(6, 0, [users[ac].id])],
                'fee_structure_ids': [(6, 0, [f.id for f in fees.values()])]})
        # courses <-> batches inverse
        for key, name, ckeys, s, e, ac in BATCHES:
            for c in ckeys:
                courses[c].write({'batch_ids': [(4, batches[key].id)]})

        active_b = ['b_ca', 'b_acca', 'b_cma']
        students = []
        for n_ in range(1, 31):
            if self._demo_ref('student_%d' % n_):
                students.append(self._demo_ref('student_%d' % n_))
                continue
            bk = active_b[(n_ - 1) % 3] if n_ <= 27 else 'b_old'
            batch = batches[bk]
            name = '%s %s' % (rnd.choice(FIRST), rnd.choice(LAST))
            st = env['student.details'].sudo().create({
                'name': name, 'gender': rnd.choice(['male', 'female']),
                'date_of_birth': today - timedelta(days=365 * rnd.randint(18, 26)),
                'email': 'demo.student%d@example.com' % n_, 'phone': '9100000%03d' % n_,
                'father_name': 'Mr. %s' % rnd.choice(LAST), 'father_phone': '9200000%03d' % n_,
                'whatsapp_number': '9200000%03d' % n_,
                'district': rnd.choice(DISTRICTS), 'city': 'Demo City', 'qualification': rnd.choice(['Plus Two', 'B.Com', 'BBA', 'Degree']),
                'logic_join': rnd.choice(['ads', 'social_media', 'seminar', 'reference']),
                'joining_status': 'new', 'branch': rnd.choice(BRANCHES),
                'batch_id': batch.id, 'course_ids': [(6, 0, batch.course_ids.ids)],
                'admission_officer_id': users['ao1' if n_ % 2 else 'ao2'].id,
                'admission_officer_text': 'Demo Officer',
                'current_batch_join_date': batch.start_date})
            self._demo_reg(st, 'student_%d' % n_)
            students.append(st)

            fee = fees['inst'] if n_ % 2 else fees['lump']
            total_fee = fee.total_fee_amount if fee.fee_type == 'installment' else fee.amount_inclusive
            enr = env['student.enrollment'].sudo().create({
                'student_id': st.id, 'batch_id': batch.id, 'fee_structure_id': fee.id,
                'enrollment_date': batch.start_date + timedelta(days=rnd.randint(0, 10)),
                'status': 'completed' if bk == 'b_old' else 'enrolled',
                'total_fee': total_fee, 'fee_type': dict(fee._fields['fee_type'].selection)[fee.fee_type],
                'gst_rate': '%s%%' % fee.gst_rate})
            self._demo_reg(enr, 'enr_%d' % n_)
            pattern = n_ % 4            # 0 unpaid, 1 partial, 2 paid, 3 two part-payments
            amounts = {0: [], 1: [round(total_fee * 0.25, 2)], 2: [total_fee],
                       3: [round(total_fee * 0.25, 2), round(total_fee * 0.25, 2)]}[pattern]
            for j, amt in enumerate(amounts):
                pay = env['student.fee.payment'].sudo().create({
                    'enrollment_id': enr.id, 'amount': amt,
                    'payment_date': enr.enrollment_date + timedelta(days=30 * j),
                    'payment_mode': rnd.choice(MODES), 'receipt_no': 'DEMO-%04d-%d' % (n_, j + 1),
                    'remarks': 'Demo payment'})
                self._demo_reg(pay, 'pay_%d_%d' % (n_, j))

        # batch transfers (2 students move CA -> ACCA)
        for i, idx in enumerate([0, 3], 1):
            if self._demo_ref('transfer_%d' % i):
                continue
            st = students[idx]
            frm, to = st.batch_id, batches['b_acca' if st.batch_id != batches['b_acca'] else 'b_ca']
            self._demo_reg(env['batch.transfer.history'].sudo().create({
                'student_id': st.id, 'from_batch_id': frm.id, 'to_batch_id': to.id,
                'join_date': frm.start_date, 'transfer_date': today - timedelta(days=5),
                'reason': 'Demo: changed to weekend timing', 'transferred_by': users['manager'].id}), 'transfer_%d' % i)
            st.write({'batch_id': to.id, 'current_batch_join_date': today - timedelta(days=5)})

        # attendance: last 6 weekdays for the 3 live batches
        for bk in active_b:
            d, made = today - timedelta(days=1), 0
            while made < 6:
                if d.weekday() < 6 and not self._demo_ref('att_%s_%s' % (bk, d)):
                    b = batches[bk]
                    lines_ = [(0, 0, {'student_id': s.id, 'status': rnd.choices(
                        ['present', 'absent', 'half_day'], [80, 12, 8])[0]}) for s in b.student_ids]
                    att = env['st.attendance'].sudo().create({
                        'date': d, 'batch_id': b.id, 'coordinator_id': b.coordinator_ids[:1].id,
                        'attendance_line_ids': lines_, 'state': 'locked'})
                    self._demo_reg(att, 'att_%s_%s' % (bk, d))
                    made += 1
                elif d.weekday() < 6:
                    made += 1
                d -= timedelta(days=1)
        return True

    @api.model
    def remove(self):
        self._demo_check_admin()
        env = self.with_context(tracking_disable=True).env
        IMD = env['ir.model.data'].sudo()
        rows = IMD.search([('module', '=', MODULE), ('name', '=like', 'demo\\_%')])
        by_model = {}
        for r in rows:
            by_model.setdefault(r.model, []).append(r.res_id)
        order = ['student.fee.payment', 'student.enrollment', 'batch.transfer.history', 'st.attendance',
                 'student.details', 'student.batch', 'fee.structure', 'course.master', 'res.users']
        archived = []
        for model in order:
            recs = env[model].sudo().with_context(active_test=False).browse(by_model.get(model, [])).exists()
            if model == 'res.users':
                for rec in recs:
                    try:
                        with env.cr.savepoint():
                            rec.unlink()
                    except Exception:
                        rec.write({'active': False})
                        archived.append(rec.display_name)
            else:
                recs.unlink()
        rows.unlink()
        return archived
