# Verification Report — `Final_Disposition_Report_2015_-_2021_Redacted`

**Model:** claude-opus-4-7  

**Overall accuracy:** 0.9909  

**Records — agent:** 21  |  **code:** 21


## Score Components

| Component | Score |
|---|---|
| NodeMatchF1 (precision / recall) | 1.0000 / 1.0000 |
| ContentScore (overall) | 0.9773 |
| ContentScore — table | 1.0000 |
| ContentScore — key_value | 0.9320 |
| ContentScore — metadata | 1.0000 |
| StructureScore (edge / path / note) | 1.0000 / 1.0000 / 1.0000 |

**Total mismatches:** 30


---

## Content Mismatches (30)

### R-KV-VALUE-DIFFERS — 30 occurrence(s)

**Explanation:** Code extracted a different value for this key-value field. Common causes: boundary bleed (extra surrounding text captured), text split at wrong position.


| Record | Node | Field | Agent value | Code value |
|---|---|---|---|---|
| r1 | n2 | Officer | Mathew Young | Mathew |
| r1 | n2 | SSN |  | Young |
| r10 | n2 | Officer | Daniel Robison | Daniel |
| r10 | n2 | SSN |  | Robison |
| r11 | n2 | Officer | Matthew Costa | Matthew |
| r11 | n2 | SSN |  | Costa |
| r13 | n2 | Officer | Matthew Doughty | Matthew |
| r13 | n2 | SSN |  | Doughty |
| r15 | n2 | Officer | Christopher Neff | Christopher |
| r15 | n2 | SSN |  | Neff |
| r16 | n2 | Officer | Mario Villarreal | Mario |
| r16 | n2 | SSN |  | Villarreal |
| r17 | n2 | Officer | Gabriel Suarez | Gabriel |
| r17 | n2 | SSN |  | Suarez |
| r19 | n2 | Officer | Jacqueline (RETIRED) Bohn | Jacqueline Bohn |
| r19 | n2 | SSN |  | (RETIRED) |
| r2 | n2 | Officer | Rachel Beuttler | Rachel |
| r2 | n2 | SSN |  | Beuttler |
| r20 | n2 | Officer | Dominic Mercurio | Dominic |
| r20 | n2 | SSN |  | Mercurio |
| r3 | n2 | Officer | Anthony Garcia | Anthony |
| r3 | n2 | SSN |  | Garcia |
| r4 | n2 | Officer | Kevin McArthur | Kevin |
| r4 | n2 | SSN |  | McArthur |
| r6 | n2 | Officer | Jesse Alvarez | Jesse |
| r6 | n2 | SSN |  | Alvarez |
| r8 | n2 | Officer | John Lawrence | John |
| r8 | n2 | SSN |  | Lawrence |
| r9 | n2 | Officer | Matthew Donatoni(not W/SPD) | Matthew W/SPD) |
| r9 | n2 | SSN |  | Donatoni(not |
