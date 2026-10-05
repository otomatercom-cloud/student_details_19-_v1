# Student Details – Demo Guide

## 1. Load the demo (demo/training DB only)
Student Details → **Registration Settings** → *Demo Data* → **Load Demo Data**. *Remove Demo Data* deletes exactly what was created.

## 2. Demo logins (password for all: `Demo@1234`)
| Role | Login |
|---|---|
| Student Details Manager | demo.manager@demo.otomater.com |
| TL Admission | demo.tl@demo.otomater.com |
| Admission Officers | demo.ao1@… / demo.ao2@… (each sees only own students) |
| Academic Coordinators | demo.ac1@… (CA, ACCA batches) / demo.ac2@… (CMA, Digital Marketing) |
| Course Coordinators | demo.cc1@… (CA, ACCA) / demo.cc2@… (CMA, Digital Marketing) |

Data: 4 courses, 6 batches (3 live, 1 upcoming, 1 completed, 1 inactive), students spread over all 7 branches (Kochi … Online), fee structures (lump sum 59,000, 4-installment 60,000, admission fee), 30 students, enrollments with unpaid / partial / paid payments, 2 batch transfers, 6 days of locked attendance for each live batch.

## 3. Demo script (≈12 min)
1. **Manager** – open Students: show register numbers (ANJ/yyyy/nn), wallet status (Clear / Partial / Due), filter by branch/batch.
2. **Enrollment & fees** – open a student → Enroll in Batch → pick fee structure → Add Payment; watch Paid / Due / Next Due update.
3. **Fee structures** – open *Demo - 4 Installments*: installments, Auto Split, Adjust Last.
4. **Batch transfer** – student → Batch Transfer; show transfer history tab.
5. **Admission Officer** – log in as `ao1`: only own students, read-only batches/fees.
6. **Academic Coordinator** – log in as `ac1`: only assigned batches' students; take/lock today's attendance.
7. **Course Coordinator** – log in as `cc2`: only students of assigned courses.
8. **Attendance report** – manager: attendance report wizard for a batch/date range; Excel export.
9. **Dashboard** – SaaS dashboard: live batches, students, due amounts.
10. **Cleanup** – Remove Demo Data.

Never load demo data on a live database.
