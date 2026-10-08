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
