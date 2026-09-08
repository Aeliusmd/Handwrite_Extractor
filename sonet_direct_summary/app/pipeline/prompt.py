SUMMARIZE_SYSTEM = """You are a medical-legal visit summarizer.
Use only facts visible in the attached PDF.
Do not invent names, dates, diagnoses, codes, medications, providers, or page numbers.
Do not use asterisks (*).
Output only the filled template. No introductions, explanations, or apologies.
Never return an empty answer when clinical visits, exams, flowsheets, or drug-test forms are present.
Skip ignored admin/legal pages, then summarize every remaining clinical report."""

SUMMARIZE_PROMPT = """Strictly follow all instructions and write a short summary within 350 words for each Date of Service.

The source is the attached PDF (not an extraction transcript).
Original packet page numbers in this file: {page_list}
The first page of THIS file is original page {first_page}.

Identify each unique report in the document. For each report, extract the unique visit date/date of service and provide a detailed summary in the following format without using any special characters like asterisks (*):

Date of Service: {{Date of Service}}

Page Numbers: {{PageNo:XXXXX list for this report only}}

Summary (max 350 words):
{{factual visit summary}}

Clinic Address:
{{accurate complete address, or Not provided}}

Referral Clinics:
{{external clinic names only, formatted as 'abc clinic', or Not provided}}

Body Parts and Pages:
♦ Body Part: {{one anatomical body part}} | Pages: {{exact PageNo:XXXXX references}}

Diagnosis ICD-10 Codes and Pages:
♦ Diagnosis Entry: {{diagnosis name}} | ICD-10 Codes: {{exact code or codes}} | Pages: {{exact PageNo:XXXXX references}}

Diagnostic Procedures and Pages:
♦ Diagnostic Procedure: {{procedure name}} | Codes: {{exact CPT/HCPCS code or codes}} | Pages: {{exact PageNo:XXXXX references}}

Medications and Pages:
♦ Medication: {{medication name}} | Pages: {{exact PageNo:XXXXX references}}

Providers and Pages:
♦ Provider: {{provider name, credentials}} | Specialty: {{specialty or N/A}} | Facility: {{facility or N/A}} | Pages: {{exact PageNo:XXXXX references}}

Surgical Procedures and Pages:
♦ Surgical Procedure: {{surgical procedure name}} | Codes: {{exact CPT code or codes, else None}} | Pages: {{exact PageNo:XXXXX references}}

Visit Chronology and Pages:
♦ Visit Date: {{MM/DD/YYYY}} | Facility: {{facility name}} | Visit Type: {{visit type}} | Pages: {{exact PageNo:XXXXX references}}

PAGE NUMBER SOURCE:
- Use original packet page numbers listed above.
- Convert original page N to PageNo:XXXXX with 5-digit zero padding. Example: page 7 -> PageNo:00007.
- Need accurate page numbers for the summary. Do not print the same Page Number for different Date of Service summaries.

### STRICT INSTRUCTIONS:
1. PAGE NUMBERS: Use the exact PageNo:XXXXX format. Do not print the same Page Number for different summaries.
2. CLINIC ADDRESS: provide the accurate and complete address (e.g., 11500 Brookshire Ave., Downey, CA 90241). If not found, write 'Not provided'.
3. REFERRAL CLINICS: Find only external clinic names (formatted as 'abc clinic'). No other info. If none, write 'Not provided'.
4. SECTIONS: Fill each section accurately. If a section is missing, write 'Not provided'. Do not add sections beyond this template.
5. NO FLUFF: No introductory text, explanations, feedback, apologies, or comments. Output ONLY the filled template.
6. DATES: Ignore nonsense or invalid Date of Service information.
7. EMPTY CONTENT: Skip a report only if it has no clinical content after applying the ignore list. Never skip the whole packet. If clinical visits exist, you must output at least one Date of Service block.

### BODY PARTS AND PAGE REFERENCES (ADDITIONAL REQUIRED OUTPUT):
1. After the existing template sections for EACH report, output the exact heading 'Body Parts and Pages:'.
2. Under that heading, output one line per distinct anatomical body part using exactly: ♦ Body Part: Body Part Name | Pages: PageNo:00001, PageNo:00002
3. Include every anatomical body part or region explicitly named in complaints, history, injury descriptions, review of systems, physical examinations (including normal or negative findings), diagnoses, treatment, procedures, or imaging. Do not infer or invent body parts.
4. For each body part, include every exact PageNo:XXXXX page in THIS report where that body part is explicitly named or clinically discussed. Preserve the source page labels exactly.
5. Use one body part per line. Merge duplicate mentions of the same body part and list its unique pages once in ascending order.
6. If no body part is clinically identified for a report, output only 'Body Parts and Pages: None'.
7. Do not place the body-parts block inside another section.

### DIAGNOSIS ICD-10 CODES AND PAGE REFERENCES (ADDITIONAL REQUIRED OUTPUT):
1. After the body-parts block for EACH report, output the exact heading 'Diagnosis ICD-10 Codes and Pages:'.
2. Under that heading, output one line per distinct explicitly documented diagnosis using exactly: ♦ Diagnosis Entry: Diagnosis Name | ICD-10 Codes: R10.9 | Pages: PageNo:00001, PageNo:00002
3. Audit every diagnosis/code list, assessment, billing section, problem list, and report header/footer. Copy every ICD-10 code exactly as documented; do not infer, calculate, correct, or invent a code.
4. Include every exact PageNo:XXXXX page in THIS report where the diagnosis and its ICD-10 code are documented together. Preserve source page labels exactly.
5. Use one diagnosis per line. Merge duplicate instances of the same diagnosis and code combination, and list unique pages once in ascending order.
6. Exclude symptoms, body parts, procedures, medications, and suspected or ruled-out conditions unless the source explicitly identifies them as a diagnosis with an ICD-10 code.
7. If no diagnosis with an explicit ICD-10 code is found, output only 'Diagnosis ICD-10 Codes and Pages: None'.
8. Do not place the diagnosis block inside another section.

### DIAGNOSTIC PROCEDURES AND PAGE REFERENCES (ADDITIONAL REQUIRED OUTPUT):
1. After the diagnosis block for EACH report, output the exact heading 'Diagnostic Procedures and Pages:'.
2. Under that heading, output one line per distinct diagnostic test/procedure using exactly: ♦ Diagnostic Procedure: Procedure Name | Codes: 84460 | Pages: PageNo:00001, PageNo:00002
3. Include every explicitly named laboratory test, imaging study, electrodiagnostic test, pathology test, and other diagnostic test/procedure whether ordered, performed, reviewed, or reported. Copy CPT/HCPCS codes exactly when documented; do not infer, invent, or correct codes.
4. Include every exact PageNo:XXXXX page in THIS report where the procedure is documented. Preserve source page labels exactly.
5. Use one procedure per line. Merge duplicate mentions of the same procedure and list unique pages once in ascending order.
6. Exclude surgeries, treatments, medications, body parts, and diagnoses. If a CPT/HCPCS code is not documented, write 'N/A' in Codes so the procedure row is still retained.
7. If no diagnostic procedure is found, output only 'Diagnostic Procedures and Pages: None'.
8. Do not place the diagnostic-procedure block inside another section.

### MEDICATIONS AND PAGE REFERENCES (ADDITIONAL REQUIRED OUTPUT):
1. After the diagnostic-procedures block for EACH report, output the exact heading 'Medications and Pages:'.
2. Under that heading, output one line per distinct explicitly documented medication using exactly: ♦ Medication: Medication Name | Pages: PageNo:00001, PageNo:00002
3. Include every explicitly named prescription drug, over-the-counter drug, vaccine, anesthetic medication, or contrast agent when prescribed, administered, ordered, listed as current/active, or documented in a medication list.
4. Preserve the medication name from the source. Do not infer medications from diagnoses. Exclude allergies and medications explicitly marked discontinued unless the page documents they were administered or used.
5. Include every exact PageNo:XXXXX page in THIS report where the medication is documented. Merge duplicates only after collecting all occurrences and sort pages ascending.
6. If no medication is found, output only 'Medications and Pages: None'.
7. Do not place the medication block inside another section.

### PROVIDERS AND PAGE REFERENCES (ADDITIONAL REQUIRED OUTPUT):
1. After the medications block for EACH report, output the exact heading 'Providers and Pages:'.
2. Under that heading, output one line per distinct explicitly named provider using exactly: ♦ Provider: Provider Name, Credentials | Specialty: Specialty or N/A | Facility: Facility Name or N/A | Pages: PageNo:00001, PageNo:00002
3. Include every clinician/provider with credentials when present (MD, DO, NP, PA, RN, LVN, PT, therapist, surgeon, anesthesiologist, radiologist, etc.).
4. Copy specialty and facility exactly when documented; otherwise write N/A. Do not invent names, specialties, or facilities. Exclude patients, employers, and attorneys.
5. Include every exact PageNo:XXXXX page in THIS report where the provider is documented. Merge duplicates only after collecting all occurrences and sort pages ascending.
6. If no provider is found, output only 'Providers and Pages: None'.
7. Do not place the provider block inside another section.

### SURGICAL PROCEDURES AND PAGE REFERENCES (ADDITIONAL REQUIRED OUTPUT):
1. After the providers block for EACH report, output the exact heading 'Surgical Procedures and Pages:'.
2. Under that heading, output one line per distinct surgical/operative procedure using exactly: ♦ Surgical Procedure: Procedure Name | Codes: exact CPT code printed on the page, else None | Pages: PageNo:00001, PageNo:00002
3. Include every named operative or surgical procedure whether scheduled, authorized, performed, or reported. Audit operative reports, surgical scheduling and authorization pages, anesthesia records, pathology specimen sources, discharge summaries, and past surgical history. Endoscopic and interventional operative procedures (for example colonoscopy, EGD, polypectomy, arthroscopy) belong in this block.
4. Copy a CPT code only when it is printed on a cited page for that procedure. Never infer a code from the procedure name and never reuse a code shown in these instructions. If no code is documented, write 'None' in Codes so the surgical row is still retained.
5. Keep the procedure name exactly as documented. Do not merge distinct operative descriptions into one row; merge only identical procedure names, then list unique pages once in ascending order.
6. Include every exact PageNo:XXXXX page in THIS report where the surgical procedure is documented. Preserve source page labels exactly.
7. Exclude laboratory tests, imaging studies, and other purely diagnostic tests; those belong in the diagnostic-procedures block.
8. If no surgical procedure is found, output only 'Surgical Procedures and Pages: None'.
9. Do not place the surgical-procedure block inside another section.

### VISIT CHRONOLOGY AND PAGE REFERENCES (ADDITIONAL REQUIRED OUTPUT):
1. After the surgical-procedures block for EACH report, output the exact heading 'Visit Chronology and Pages:'.
2. Under that heading, output one line for the visit using exactly: ♦ Visit Date: MM/DD/YYYY | Facility: Facility Name | Visit Type: Office / Outpatient | Pages: PageNo:00001, PageNo:00002
3. Use the same Date of Service as this report. Facility is the clinic/facility name. Visit Type should be one of Office / Outpatient, Emergency Department / Urgent Care, Hospital (Inpatient/Observation), Surgical / Operative, Diagnostic / Imaging, Therapy / Rehabilitation, or Telehealth when supported; otherwise copy the documented report/encounter type.
4. Include every exact PageNo:XXXXX page belonging to THIS visit/report. Preserve source page labels exactly.
5. If a visit date cannot be determined, output only 'Visit Chronology and Pages: None'.
6. The body-parts, diagnosis, diagnostic-procedure, medication, provider, surgical-procedure, and visit-chronology blocks are the only permitted additions beyond the existing template sections. Do not place any of them inside another section.

### STRICTLY IGNORE THESE REPORTS (skip these pages only; still summarize all other clinical visits):
- Cures Drug Utilization Report, Pain Management Contract, 3R-2 (Employer), Registration Forms (LAC+USC).
- Subpoena Duces Tecum, Declaration of Service, HIPAA Authorizations, Insurance Verification, CT/Ultrasound Appointment Details, Admission Education, Forms Request, Form Completion, Care Management.
- Legal Consent, Worker's Compensation Denial, Summary Discharge Report for LIS ELR.
- Cover sheets, index tables, and attorney-packet dividers that are not a patient visit.

DO summarize Concentra visits, non-injury flowsheets, patient information forms, exams, drug testing custody and control forms, imaging, operative notes, and any dated clinical encounter.

Do not return an empty string. If at least one clinical report exists, output the filled template for each Date of Service.
"""

COMBINE_PROMPT = """Combine the following partial visit summaries into one final output.
Keep the same Date of Service template and diamond-line blocks.
Merge duplicate Date of Service reports. Keep chronological order.
Do not invent facts. Do not use asterisks (*).
Do not return an empty string if any partial summary has a Date of Service block.
Output ONLY the filled template.

PARTIAL SUMMARIES:
"""
