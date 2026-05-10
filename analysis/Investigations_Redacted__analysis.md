# Verification Report — `Investigations_Redacted`

**Model:** claude-opus-4-7  

**Overall accuracy:** 0.9517  

**Records — agent:** 19  |  **code:** 19


## Score Components

| Component | Score |
|---|---|
| NodeMatchF1 (precision / recall) | 1.0000 / 1.0000 |
| ContentScore (overall) | 0.8792 |
| ContentScore — table | 0.7812 |
| ContentScore — key_value | 0.9167 |
| ContentScore — metadata | 1.0000 |
| StructureScore (edge / path / note) | 1.0000 / 1.0000 / 1.0000 |

**Total mismatches:** 131


---

## Content Mismatches (131)

### R-CELL-DIFFERS — 93 occurrence(s)

**Explanation:** Table cell value differs from agent. Common causes: column alignment off, row prefix/suffix not stripped, merged-cell mis-handling.


| Record | Node | Field | Agent value | Code value |
|---|---|---|---|---|
| r1 | n4 | rows[0].Type Of Complaint | R-3B.1 Courtesy:Profanity | Courtesy:Profanity |
| r1 | n5 | rows[0].Name | Griffet, David I. | David I. 914 |
| r1 | n5 | rows[0].ID No. | 914 | SERGEANT |
| r1 | n5 | rows[0].Rank | SERGEANT |  |
| r10 | n4 | rows[0].Type Of Complaint | S-6 Pursuit Policy | Pursuit Policy |
| r10 | n5 | rows[0].Name | MALONEY, J. BRIAN | J. BRIAN 942 |
| r10 | n5 | rows[0].ID No. | 942 | OFFICER |
| r10 | n5 | rows[0].Rank | OFFICER |  |
| r11 | n4 | rows[0].Type Of Complaint | R-5A3 OPERATIONS | OPERATIONS |
| r11 | n5 | rows[0].Name | Sumption, R. Dustin | R. Dustin 7108 |
| r11 | n5 | rows[0].ID No. | 7108 | RECRUIT |
| r11 | n5 | rows[0].Rank | RECRUIT OFFIC | OFFIC |
| r12 | n4 | rows[0].Type Of Complaint | R-1A2 CONDUCT GENERALLY | CONDUCT GENERALLY |
| r12 | n5 | rows[0].Name | No Officers Entered | Officers Entered |
| r12 | n5 | rows[0].ID No. |  | Not |
| r12 | n5 | rows[0].Rank | Not Stated | Stated |
| r13 | n4 | rows[0].Type Of Complaint | R-3B.4 COURTESY: COMMENT | COURTESY: COMMENT |
| r13 | n4 | rows[1].Type Of Complaint | R-5D Use of physical force | Use of physical force |
| r13 | n5 | rows[0].Name | Bowersock, Jamie | Jamie 705-MED |
| r13 | n5 | rows[0].ID No. | 705-MED | OFFICER |
| r13 | n5 | rows[0].Rank | OFFICER |  |
| r14 | n4 | rows[0].Type Of Complaint | R-3B COURTESY | COURTESY |
| r14 | n5 | rows[0].Name | Olmstead, Kevin A. | Kevin A. 7901 |
| r14 | n5 | rows[0].ID No. | 7901 | RECRUIT |
| r14 | n5 | rows[0].Rank | RECRUIT OFFIC | OFFIC |
| r15 | n4 | rows[0].Type Of Complaint | R-5B ARREST, SEARCH AND SEIZURE | ARREST, SEARCH AND SEIZURE |
| r15 | n4 | rows[1].Type Of Complaint | R-5D Use of physical force | Use of physical force |
| r15 | n5 | rows[0].Name | Bowersock, Jamie | Jamie 705-MED |
| r15 | n5 | rows[0].ID No. | 705-MED | OFFICER |
| r15 | n5 | rows[0].Rank | OFFICER |  |
| r15 | n5 | rows[1].Name | Mitchell, Rodney S. | Rodney S. 717RES |
| r15 | n5 | rows[1].ID No. | 717RES | OFFICER |
| r15 | n5 | rows[1].Rank | OFFICER |  |
| r16 | n4 | rows[0].Type Of Complaint | R-5D Use of physical force | Use of physical force |
| r16 | n5 | rows[0].Name | Mclearin, David M. | David M. 7110 |
| r16 | n5 | rows[0].ID No. | 7110 | RECRUIT |
| r16 | n5 | rows[0].Rank | RECRUIT OFFIC | OFFIC |
| r17 | n4 | rows[0].Type Of Complaint | R-5D Use of physical force | Use of physical force |
| r17 | n5 | rows[0].Name | Prosser, Justin | Justin 7104 |
| r17 | n5 | rows[0].ID No. | 7104 | OFFICER |
| r17 | n5 | rows[0].Rank | OFFICER |  |
| r18 | n4 | rows[0].Type Of Complaint | R-5C2 PERSONS IN CUSTODY | PERSONS IN CUSTODY |
| r18 | n4 | rows[1].Type Of Complaint | R-5D Use of physical force | Use of physical force |
| r18 | n5 | rows[0].Name | Briggs, Mark D. | Mark D. 785RESIG |
| r18 | n5 | rows[0].ID No. | 785RESIG | Senior |
| r18 | n5 | rows[0].Rank | Senior OFFICER | OFFICER |
| r18 | n5 | rows[1].Name | Young, Von D.III | Von D.III 719 |
| r18 | n5 | rows[1].ID No. | 719 | Senior |
| r18 | n5 | rows[1].Rank | Senior Officer | Officer |
| r19 | n4 | rows[0].Type Of Complaint | R-3B.2 Courtesy: Rude | Courtesy: Rude |
| r19 | n4 | rows[1].Type Of Complaint | R-5D Use of physical force | Use of physical force |
| r19 | n5 | rows[0].Name | Bowersock, Jamie | Jamie 705-MED |
| r19 | n5 | rows[0].ID No. | 705-MED | OFFICER |
| r19 | n5 | rows[0].Rank | OFFICER |  |
| r2 | n4 | rows[0].Type Of Complaint | R-3B.1 Courtesy:Profanity | Courtesy:Profanity |
| r2 | n4 | rows[1].Type Of Complaint | R-3B.4 COURTESY: COMMENT | COURTESY: COMMENT |
| r2 | n4 | rows[2].Type Of Complaint | R-5D Use of physical force | Use of physical force |
| r2 | n5 | rows[0].Name | Petrilli, Thomas P. | Thomas P. 939 |
| r2 | n5 | rows[0].ID No. | 939 | Senior |
| r2 | n5 | rows[0].Rank | Senior Officer | Officer |
| r3 | n4 | rows[0].Type Of Complaint | R-3B.2 Courtesy: Rude | Courtesy: Rude |
| r3 | n4 | rows[1].Type Of Complaint | R-3B.2 Courtesy: Rude | Courtesy: Rude |
| r3 | n5 | rows[0].Name | Shepard, Charles F. | Charles F. 921RET |
| r3 | n5 | rows[0].ID No. | 921RET | SERGEANT |
| r3 | n5 | rows[0].Rank | SERGEANT |  |
| r4 | n4 | rows[0].Type Of Complaint | R-3B.2 Courtesy: Rude | Courtesy: Rude |
| r4 | n5 | rows[0].Name | Wilberg, Richard W. | Richard W. 799RESIG |
| r4 | n5 | rows[0].ID No. | 799RESIG | Senior |
| r4 | n5 | rows[0].Rank | Senior Officer | Officer |
| r5 | n4 | rows[0].Type Of Complaint | R-3B.1 Courtesy:Profanity | Courtesy:Profanity |
| r5 | n4 | rows[1].Type Of Complaint | R-3B.4 COURTESY: COMMENT | COURTESY: COMMENT |
| r5 | n5 | rows[0].Name | Kelly, Patrick M. | Patrick M. 722-Ret |
| r5 | n5 | rows[0].ID No. | 722-Ret | DETECTIVE |
| r5 | n5 | rows[0].Rank | DETECTIVE |  |
| r6 | n4 | rows[0].Type Of Complaint | R-5D Use of physical force | Use of physical force |
| r6 | n5 | rows[0].Name | Lack, Aaron V. | Aaron V. 920 |
| r6 | n5 | rows[0].ID No. | 920 | SERGEANT |
| r6 | n5 | rows[0].Rank | SERGEANT |  |
| r6 | n5 | rows[1].Name | MULTIPLE OFFICERS/EMPLOY | OFFICERS/EMPLOY |
| r6 | n5 | rows[1].ID No. |  | NOT |
| r6 | n5 | rows[1].Rank | NOT STATED | STATED |
| r7 | n4 | rows[0].Type Of Complaint | R-5D Use of physical force | Use of physical force |
| r7 | n5 | rows[0].Name | MULTIPLE OFFICERS/EMPLOY | OFFICERS/EMPLOY |
| r7 | n5 | rows[0].ID No. |  | NOT |
| r7 | n5 | rows[0].Rank | NOT STATED | STATED |
| r8 | n4 | rows[0].Type Of Complaint | R-5D Use of physical force | Use of physical force |
| r8 | n5 | rows[0].Name | MULTIPLE OFFICERS/EMPLOY | OFFICERS/EMPLOY |
| r8 | n5 | rows[0].ID No. |  | NOT |
| r8 | n5 | rows[0].Rank | NOT STATED | STATED |
| r9 | n4 | rows[0].Type Of Complaint | R-5D Use of physical force | Use of physical force |
| r9 | n5 | rows[0].Name | MULTIPLE OFFICERS/EMPLOY | OFFICERS/EMPLOY |
| r9 | n5 | rows[0].ID No. |  | NOT |
| r9 | n5 | rows[0].Rank | NOT STATED | STATED |

### R-KV-VALUE-DIFFERS — 38 occurrence(s)

**Explanation:** Code extracted a different value for this key-value field. Common causes: boundary bleed (extra surrounding text captured), text split at wrong position.


| Record | Node | Field | Agent value | Code value |
|---|---|---|---|---|
| r1 | n2 | Number | 08-01 | 08-01 Swenson, |
| r1 | n2 | Investigator | Swenson, Jon | Jon |
| r10 | n2 | Number | 08-II02 | 08-II02 Nearing, |
| r10 | n2 | Investigator | Nearing, Holly | Holly |
| r11 | n2 | Number | 08-05 | 08-05 Swenson, |
| r11 | n2 | Investigator | Swenson, Jon | Jon |
| r12 | n2 | Number | 09-II01 | 09-II01 Gallo, |
| r12 | n2 | Investigator | Gallo, Joe | Joe |
| r13 | n2 | Number | 08-08 | 08-08 Paulus, |
| r13 | n2 | Investigator | Paulus, Michael | Michael |
| r14 | n2 | Number | 08-07 | 08-07 Swan, |
| r14 | n2 | Investigator | Swan, Scott | Scott |
| r15 | n2 | Number | 08-09 | 08-09 Paulus, |
| r15 | n2 | Investigator | Paulus, Michael | Michael |
| r16 | n2 | Number | 08-10 | 08-10 Yohnka, |
| r16 | n2 | Investigator | Yohnka, Brad | Brad |
| r17 | n2 | Number | 08-11 | 08-11 Paulus, |
| r17 | n2 | Investigator | Paulus, Michael | Michael |
| r18 | n2 | Number | 08-12 | 08-12 shaffer, |
| r18 | n2 | Investigator | shaffer, david | david |
| r19 | n2 | Number | 08-13 | 08-13 Swenson, |
| r19 | n2 | Investigator | Swenson, Jon | Jon |
| r2 | n2 | Number | 08-02 | 08-02 Swan, |
| r2 | n2 | Investigator | Swan, Scott | Scott |
| r3 | n2 | Number | 08-03 | 08-03 Paulus, |
| r3 | n2 | Investigator | Paulus, Michael | Michael |
| r4 | n2 | Number | 08-II01 | 08-II01 Swan, |
| r4 | n2 | Investigator | Swan, Scott | Scott |
| r5 | n2 | Number | 08-06 | 08-06 Gallo, |
| r5 | n2 | Investigator | Gallo, Joe | Joe |
| r6 | n2 | Number | 08-04a | 08-04a Swenson, |
| r6 | n2 | Investigator | Swenson, Jon | Jon |
| r7 | n2 | Number | 08-04b | 08-04b Swenson, |
| r7 | n2 | Investigator | Swenson, Jon | Jon |
| r8 | n2 | Number | 08-04c | 08-04c Swenson, |
| r8 | n2 | Investigator | Swenson, Jon | Jon |
| r9 | n2 | Number | 08-04d | 08-04d Swenson, |
| r9 | n2 | Investigator | Swenson, Jon | Jon |
