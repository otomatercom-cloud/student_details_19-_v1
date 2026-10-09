# Attendance & WhatsApp (v19.0.1.3.0)

**Statuses:** Present, Late, Half Day (0.5), Absent, On Leave (excused, excluded from total). Late counts as present.
Only **locked** sheets count in any percentage. One sheet per batch + date + session (unique).

**Take attendance:** backend *Students Details > Attendance > Attendance Records*, or portal `/my/attendance/batches`
(Save Draft / Submit & Lock; back-dating limited to 14 days). Unlock = Student Manager or Administrator only.

**Reports:** *Attendance Analysis* (pivot/graph on all lines), *Attendance Report* wizard (per batch, low-attendance
flag, Excel day-wise register), per-student *Attendance Summary* tab and stat button.

**WhatsApp:** Registration Settings > Attendance WhatsApp Alerts. Provider = HTTP gateway (POST JSON
`{number, phone, message}`, optional Bearer token) or Meta Cloud API (text or approved templates).
Locking a sheet queues one message per absent (optionally late) student to the guardian number
(whatsapp_number, else father/mother/student phone); a cron sends every 5 min (3 attempts). Low-attendance alerts
are sent from the report screen (once per student per period). Everything is visible in *Attendance > WhatsApp Log*
with Retry / Send Now. To use another WhatsApp service, override `otm.attendance.whatsapp.log._dispatch()`.

## Mark Entry & Parent Mark Report (v19.0.1.4.0)
Student Details > Marks > Exams: create exam (batch, subject, max/pass marks) -> students auto-listed -> enter marks (or tick Absent) -> **Publish Marks** (locks) -> marks go to parents on WhatsApp (or press *Send Marks to Parents*). Coordinators can do the same at `/my/marks`.
Settings > WhatsApp: set the *Marks template* name + message, and *Auto-send on publish*.

Meta template `student_marks_report` (Utility, English), 4 variables:
    📝 *Exam Result*
    Dear Parent, {{1}} scored *{{3}}* in {{2}}.
    ✅ Result: *{{4}}*
    Thank you, Logic School of Management

## Next.js frontend API (v19.0.1.6.0)
`controllers/api.py` exposes JSON endpoints under `/api/sdm/*` (session auth, ACL/record rules apply; `/api/sdm/public/*` is open for the join form). Used by the `student-frontend` Next.js app. Restart Odoo after deploying this release.

## Finance API (v1.7.0) – used by the Next.js frontend
`/api/sdm/fees`, `/fees/save` (installments, GST inclusive/exclusive), `/enroll` (multi-fee), `/enrollments`,
`/enrollments/<id>/payment|status|razorpay`, `/payments/<id>/refresh|mark-paid`, `/students/<id>/finance|transfer|overview`,
`/finance/summary`. Handled API errors now roll back the transaction (no half-saved records).
**Restart Odoo before upgrading.**

## Daily auto sheets (v1.8.0)
A daily cron ("Attendance: create today's sheets", ~00:05 IST) creates a draft full-day sheet for each active batch, skipping weekly-off days
(Settings > Weekly Off Days, default Sunday), holidays (Attendance > Holidays, optionally per batch) and days outside the batch start/end dates.
Coordinators open the sheet in the frontend, mark and submit. Access: administrators/managers and academic coordinators (own batches). Course coordinators have no attendance access.
Restart Odoo before upgrading.

## Subject on attendance + timetable (v1.9.0)
Attendance sheets now have an optional Subject (same master as exam marks). Install `student_timetable_19` (needs faculty_19) to add classrooms and the weekly timetable:
for a batch with periods on a weekday the daily job creates one sheet per period (subject, faculty, room, time); other batches keep one full-day sheet.
Absent WhatsApp alerts are sent once per student per day for period sheets. Install order: student_details_19 -> faculty_19 -> student_timetable_19. Restart Odoo before upgrading/installing.
