import logging
import re

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

MOODLE_URL_KEY = 'student_details.moodle.base_url'
MOODLE_TOKEN_KEY = 'student_details.moodle.token'
PORTAL_PASSWORD_KEY = 'student_details.portal.default_password'
FALLBACK_EMAIL_DOMAIN_KEY = 'student_details.moodle.fallback_email_domain'
MOODLE_STUDENT_ROLE_ID_KEY = 'student_details.moodle.student_role_id'

DEFAULT_PORTAL_PASSWORD = 'Lg#yu870'
DEFAULT_FALLBACK_EMAIL_DOMAIN = 'students.otomater.local'
DEFAULT_MOODLE_STUDENT_ROLE_ID = 5  # stock Moodle's built-in "Student" role


class ResConfigSettingsMoodle(models.TransientModel):
    _inherit = 'res.config.settings'

    moodle_base_url = fields.Char(
        string='Moodle Site URL',
        config_parameter=MOODLE_URL_KEY,
        help="e.g. https://moodle.logiceducation.org (no trailing slash)",
    )
    moodle_ws_token = fields.Char(
        string='Moodle Web Service Token',
        config_parameter=MOODLE_TOKEN_KEY,
        help="Token for a Moodle web service user with core_user_create_users "
             "and core_user_get_users_by_field permissions enabled.",
    )
    portal_default_password = fields.Char(
        string='Default Portal/Moodle Password',
        config_parameter=PORTAL_PASSWORD_KEY,
        default=DEFAULT_PORTAL_PASSWORD,
    )
    moodle_fallback_email_domain = fields.Char(
        string='Fallback Email Domain',
        config_parameter=FALLBACK_EMAIL_DOMAIN_KEY,
        default=DEFAULT_FALLBACK_EMAIL_DOMAIN,
        help="Used to build a placeholder email (phone@domain) for students "
             "who have no email on file, since Moodle requires one.",
    )
    moodle_student_role_id = fields.Integer(
        string='Moodle "Student" Role ID',
        config_parameter=MOODLE_STUDENT_ROLE_ID_KEY,
        default=DEFAULT_MOODLE_STUDENT_ROLE_ID,
        help="The numeric role id Moodle uses for 'Student' on your site "
             "(stock Moodle installs use 5, but this can differ — check "
             "Site administration > Users > Permissions > Define roles, "
             "the id is in that page's URL). Used when enrolling a "
             "student into their batch's Moodle course.",
    )

    def action_test_moodle_connection(self):
        """Tests whatever is currently in the URL/Token fields on this
        settings form — including unsaved changes — rather than only
        the last-saved config parameter, so you can verify new
        credentials before committing to them.

        Uses core_user_get_users_by_field with a lookup value that
        shouldn't exist, rather than core_webservice_get_site_info —
        the latter needs its own separate permission grant on the
        Moodle side, while core_user_get_users_by_field is already
        required (and therefore already enabled) for the real student
        sync this token is used for. An empty result here means the
        connection and permissions are both fine; only a genuine
        connectivity or access error should trigger the failure path."""
        self.ensure_one()
        base_url = (self.moodle_base_url or '').rstrip('/')
        token = self.moodle_ws_token
        if not base_url or not token:
            raise UserError(_(
                "Enter both the Moodle Site URL and Web Service Token first."))

        Student = self.env['student.details']
        try:
            Student._moodle_call(base_url, token, 'core_user_get_users_by_field', {
                'field': 'username',
                'values[0]': '__connection_test_no_such_user__',
            })
        except UserError:
            raise
        except Exception as exc:
            raise UserError(_("Could not reach Moodle: %s") % exc)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Moodle Connection OK"),
                'message': _("Successfully connected to %s and the token has the "
                             "expected permissions.") % base_url,
                'type': 'success',
                'sticky': False,
            },
        }


class StudentMoodlePortalSync(models.Model):
    _inherit = 'student.details'

    portal_user_id = fields.Many2one(
        'res.users', string='Portal User', readonly=True, copy=False)
    portal_sync_state = fields.Selection([
        ('not_synced', 'Not Synced'),
        ('synced', 'Synced'),
        ('failed', 'Failed'),
    ], string='Portal Status', default='not_synced', readonly=True, copy=False)
    portal_sync_message = fields.Char(readonly=True, copy=False)

    moodle_user_id = fields.Integer(readonly=True, copy=False)
    moodle_username = fields.Char(readonly=True, copy=False)
    moodle_sync_state = fields.Selection([
        ('not_synced', 'Not Synced'),
        ('synced', 'Synced'),
        ('failed', 'Failed'),
    ], string='Moodle Status', default='not_synced', readonly=True, copy=False)
    moodle_sync_message = fields.Char(readonly=True, copy=False)

    moodle_enrol_state = fields.Selection([
        ('not_applicable', 'No Batch Course Configured'),
        ('enrolled', 'Enrolled'),
        ('failed', 'Failed'),
    ], string='Moodle Course Enrolment', default='not_applicable', readonly=True, copy=False)
    moodle_enrol_message = fields.Char(readonly=True, copy=False)

    # ── config helpers ────────────────────────────────────────────────
    @api.model
    def _get_moodle_config(self):
        icp = self.env['ir.config_parameter'].sudo()
        base_url = (icp.get_param(MOODLE_URL_KEY) or '').rstrip('/')
        token = icp.get_param(MOODLE_TOKEN_KEY)
        if not base_url or not token:
            raise UserError(_(
                "Moodle Site URL and Web Service Token must be configured "
                "first (Students > Configuration > Registration Settings)."
            ))
        return base_url, token

    @api.model
    def _get_default_password(self):
        icp = self.env['ir.config_parameter'].sudo()
        return icp.get_param(PORTAL_PASSWORD_KEY) or DEFAULT_PORTAL_PASSWORD

    @api.model
    def _get_fallback_email_domain(self):
        icp = self.env['ir.config_parameter'].sudo()
        return icp.get_param(FALLBACK_EMAIL_DOMAIN_KEY) or DEFAULT_FALLBACK_EMAIL_DOMAIN

    def _clean_login(self):
        self.ensure_one()
        if not self.phone:
            raise UserError(_("%s has no Phone Number set.") % self.name)
        login = re.sub(r'\D', '', self.phone)
        if not login:
            raise UserError(_(
                "Phone Number '%s' on %s does not contain any digits."
            ) % (self.phone, self.name))
        return login

    def _split_name(self):
        self.ensure_one()
        parts = (self.name or '').strip().split()
        if not parts:
            return 'Student', 'Student'
        firstname = parts[0]
        lastname = ' '.join(parts[1:]) or parts[0]
        return firstname, lastname

    def _get_email_for_external_systems(self):
        self.ensure_one()
        if self.email:
            return self.email
        login = self._clean_login()
        return f"{login}@{self._get_fallback_email_domain()}"

    # ── portal user ───────────────────────────────────────────────────
    def _create_or_get_portal_user(self, password):
        self.ensure_one()
        login = self._clean_login()
        Users = self.env['res.users'].sudo()
        existing = Users.with_context(active_test=False).search(
            [('login', '=', login)], limit=1)
        if existing:
            return existing, False

        portal_group = self.env.ref('base.group_portal')
        vals = {
            'name': self.name or login,
            'login': login,
            'password': password,
            'email': self.email or False,
            'phone': self.phone,
            'company_id': self.env.company.id,
            'company_ids': [(6, 0, [self.env.company.id])],
            'group_ids': [(4, portal_group.id)],
        }
        user = Users.with_context(no_reset_password=True).create(vals)
        return user, True

    # ── moodle ────────────────────────────────────────────────────────
    def _moodle_call(self, base_url, token, wsfunction, extra_params):
        params = {
            'wstoken': token,
            'wsfunction': wsfunction,
            'moodlewsrestformat': 'json',
        }
        params.update(extra_params)
        try:
            resp = requests.post(
                f"{base_url}/webservice/rest/server.php",
                data=params, timeout=20,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise UserError(_("Could not reach Moodle: %s") % exc)
        result = resp.json()
        if isinstance(result, dict) and result.get('exception'):
            raise UserError(_("Moodle error (%s): %s") % (
                result.get('errorcode'), result.get('message')))
        return result

    def _moodle_find_user_id(self, base_url, token, username):
        result = self._moodle_call(base_url, token, 'core_user_get_users_by_field', {
            'field': 'username',
            'values[0]': username,
        })
        if result:
            return result[0]['id']
        return False

    def _create_or_get_moodle_user(self, base_url, token, password):
        self.ensure_one()
        username = self._clean_login()
        existing_id = self._moodle_find_user_id(base_url, token, username)
        if existing_id:
            return existing_id, username, False

        firstname, lastname = self._split_name()
        email = self._get_email_for_external_systems()
        result = self._moodle_call(base_url, token, 'core_user_create_users', {
            'users[0][username]': username,
            'users[0][password]': password,
            'users[0][firstname]': firstname,
            'users[0][lastname]': lastname,
            'users[0][email]': email,
        })
        moodle_id = result[0]['id']
        return moodle_id, username, True

    def _moodle_enrol_in_batch_course(self, base_url, token, moodle_user_id):
        """Enrols this student's Moodle account into their batch's Moodle
        course, if one has been configured (student.batch.moodle_course_id).
        Idempotent — re-enrolling someone already enrolled is a no-op on
        Moodle's side, not an error."""
        self.ensure_one()
        course_id = self.batch_id.moodle_course_id
        if not course_id:
            return 'not_applicable', _("No Moodle course configured for batch '%s'.") % (
                self.batch_id.name or '')

        role_id = self.env['ir.config_parameter'].sudo().get_param(
            MOODLE_STUDENT_ROLE_ID_KEY) or DEFAULT_MOODLE_STUDENT_ROLE_ID
        self._moodle_call(base_url, token, 'enrol_manual_enrol_users', {
            'enrolments[0][roleid]': int(role_id),
            'enrolments[0][userid]': moodle_user_id,
            'enrolments[0][courseid]': int(course_id),
        })
        return 'enrolled', _("Enrolled into Moodle course #%s.") % course_id

    # ── combined action ──────────────────────────────────────────────
    def action_sync_moodle_and_portal(self):
        password = self._get_default_password()
        base_url = token = None
        try:
            base_url, token = self._get_moodle_config()
        except UserError as exc:
            # Still let portal creation proceed even if Moodle isn't configured yet.
            _logger.info("Moodle not configured, skipping Moodle sync: %s", exc)

        portal_ok = portal_skipped = portal_fail = 0
        moodle_ok = moodle_skipped = moodle_fail = 0
        enrol_ok = enrol_fail = 0

        for student in self:
            # Portal user
            try:
                user, created = student._create_or_get_portal_user(password)
                student.portal_user_id = user.id
                student.portal_sync_state = 'synced'
                student.portal_sync_message = (
                    _("Portal user created.") if created
                    else _("Portal user already existed (linked).")
                )
                portal_ok += 1 if created else 0
                portal_skipped += 0 if created else 1
            except Exception as exc:  # noqa: BLE001
                student.portal_sync_state = 'failed'
                student.portal_sync_message = str(exc)
                portal_fail += 1
                _logger.warning("Portal sync failed for %s: %s", student.name, exc)

            # Moodle user
            if base_url and token:
                try:
                    moodle_id, username, created = student._create_or_get_moodle_user(
                        base_url, token, password)
                    student.moodle_user_id = moodle_id
                    student.moodle_username = username
                    student.moodle_sync_state = 'synced'
                    student.moodle_sync_message = (
                        _("Moodle account created.") if created
                        else _("Moodle account already existed (linked).")
                    )
                    moodle_ok += 1 if created else 0
                    moodle_skipped += 0 if created else 1

                    try:
                        enrol_state, enrol_message = student._moodle_enrol_in_batch_course(
                            base_url, token, moodle_id)
                        student.moodle_enrol_state = enrol_state
                        student.moodle_enrol_message = enrol_message
                        if enrol_state == 'enrolled':
                            enrol_ok += 1
                    except Exception as enrol_exc:  # noqa: BLE001
                        student.moodle_enrol_state = 'failed'
                        student.moodle_enrol_message = str(enrol_exc)
                        enrol_fail += 1
                        _logger.warning(
                            "Moodle course enrolment failed for %s: %s", student.name, enrol_exc)
                except Exception as exc:  # noqa: BLE001
                    student.moodle_sync_state = 'failed'
                    student.moodle_sync_message = str(exc)
                    moodle_fail += 1
                    _logger.warning("Moodle sync failed for %s: %s", student.name, exc)
            else:
                student.moodle_sync_state = 'failed'
                student.moodle_sync_message = _("Moodle URL/Token not configured.")
                moodle_fail += 1

        message = _(
            "Portal: %(p_ok)d created, %(p_skip)d already existed, %(p_fail)d failed.\n"
            "Moodle: %(m_ok)d created, %(m_skip)d already existed, %(m_fail)d failed.\n"
            "Batch Course Enrolment: %(e_ok)d enrolled, %(e_fail)d failed."
        ) % {
            'p_ok': portal_ok, 'p_skip': portal_skipped, 'p_fail': portal_fail,
            'm_ok': moodle_ok, 'm_skip': moodle_skipped, 'm_fail': moodle_fail,
            'e_ok': enrol_ok, 'e_fail': enrol_fail,
        }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Moodle / Portal Sync"),
                'message': message,
                'sticky': True,
                'type': 'warning' if (portal_fail or moodle_fail or enrol_fail) else 'success',
            },
        }


class StudentBatchMoodle(models.Model):
    _inherit = 'student.batch'

    moodle_course_id = fields.Integer(
        string='Moodle Course ID',
        help="The numeric course id in Moodle that this batch's students "
             "should be enrolled into (visible in the course's URL in "
             "Moodle, e.g. .../course/view.php?id=7 -> 7). Leave blank to "
             "skip Moodle course enrolment for this batch.")
    moodle_enrolled_count = fields.Integer(compute='_compute_moodle_enrolled_count')

    def _compute_moodle_enrolled_count(self):
        Student = self.env['student.details']
        for rec in self:
            rec.moodle_enrolled_count = Student.search_count([
                ('batch_id', '=', rec.id), ('moodle_enrol_state', '=', 'enrolled'),
            ])

    def action_sync_batch_to_moodle(self):
        """Backfill enrolment for students in this batch who already have
        a Moodle account (from an earlier sync) but haven't been enrolled
        into this batch's course yet — e.g. because the course id was
        only just configured."""
        self.ensure_one()
        if not self.moodle_course_id:
            raise UserError(_(
                "Set a Moodle Course ID on this batch first."))

        Student = self.env['student.details']
        students = Student.search([
            ('batch_id', '=', self.id), ('moodle_user_id', '!=', False),
        ])
        if not students:
            raise UserError(_(
                "No students in this batch have a Moodle account yet — "
                "run 'Create Portal Users / Sync to Moodle' on them first."))

        base_url, token = students[:1]._get_moodle_config()
        ok = fail = 0
        for student in students:
            try:
                enrol_state, enrol_message = student._moodle_enrol_in_batch_course(
                    base_url, token, student.moodle_user_id)
                student.moodle_enrol_state = enrol_state
                student.moodle_enrol_message = enrol_message
                if enrol_state == 'enrolled':
                    ok += 1
            except Exception as exc:  # noqa: BLE001
                student.moodle_enrol_state = 'failed'
                student.moodle_enrol_message = str(exc)
                fail += 1
                _logger.warning("Batch Moodle enrolment failed for %s: %s", student.name, exc)

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Batch Moodle Enrolment"),
                'message': _("%(ok)d enrolled, %(fail)d failed.") % {'ok': ok, 'fail': fail},
                'sticky': True,
                'type': 'warning' if fail else 'success',
            },
        }
