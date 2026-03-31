
CUSTOMER_TOTAL_CLIENTS = """
SELECT COUNT(*) AS total_clients
FROM client
WHERE customer_id = %s
"""

CUSTOMER_TOTAL_ACCOUNTANTS = """
SELECT COUNT(*) AS total_accountants
FROM accountant
WHERE customer_id = %s
"""

CUSTOMER_TOTAL_GL_ACCOUNTS = """
SELECT COUNT(*) AS total_gl_accounts
FROM dim_aic_gl_acct
WHERE customer_id = %s
"""

CUSTOMER_TOTAL_JE_TEMPLATES = """
SELECT COUNT(*) AS total_je_templates
FROM dim_aic_je_template_header
WHERE customer_id = %s
"""

CUSTOMER_TOTAL_INPUT_FILES = """
SELECT COUNT(*) AS total_input_files
FROM dim_aic_input_files inf
JOIN client c ON inf.client_id = c.id
WHERE c.customer_id = %s
"""

CUSTOMER_MONTHLY_ACCOUNTING_BY_STATUS = """
SELECT
fma.status,
COUNT(*) AS count
FROM fact_aic_monthly_accounting fma
JOIN client c ON fma.client_id = c.id
WHERE c.customer_id = %s
GROUP BY fma.status
"""

CUSTOMER_DOCUMENT_STATUS_SUMMARY = """
SELECT
mad.status,
COUNT(*) AS count
FROM monthly_accounting_document mad
JOIN fact_aic_monthly_accounting fma ON mad.monthly_accounting_id = fma.id
JOIN client c ON fma.client_id = c.id
WHERE c.customer_id = %s
GROUP BY mad.status
"""

CUSTOMER_RECENT_MONTHLY_ACCOUNTINGS = """
SELECT
    fma.id,
    c.id AS client_id,
    c.client_name,
    ELT(fma.month, 'January','February','March','April','May','June','July','August','September','October','November','December') AS month,
    fma.year,
    fma.status,
    fma.created_at
FROM fact_aic_monthly_accounting fma
JOIN client c ON fma.client_id = c.id
WHERE c.customer_id = %s
ORDER BY fma.created_at DESC
LIMIT 10
"""




ACCOUNTANT_ASSIGNED_CLIENTS_COUNT = """
SELECT COUNT(*) AS assigned_clients_count
FROM client_assigned_accountants
WHERE dimaicaccountant_id = %s
"""

ACCOUNTANT_TOTAL_DOCUMENTS = """
SELECT COUNT(*) AS total_documents
FROM monthly_accounting_document mad
JOIN fact_aic_monthly_accounting fma ON mad.monthly_accounting_id = fma.id
JOIN client_assigned_accountants caa ON fma.client_id = caa.dimaicclient_id
WHERE caa.dimaicaccountant_id = %s
"""

ACCOUNTANT_DOCUMENT_STATUS_BREAKDOWN = """
SELECT
mad.status,
COUNT(*) AS count
FROM monthly_accounting_document mad
JOIN fact_aic_monthly_accounting fma ON mad.monthly_accounting_id = fma.id
JOIN client_assigned_accountants caa ON fma.client_id = caa.dimaicclient_id
WHERE caa.dimaicaccountant_id = %s
GROUP BY mad.status
"""

ACCOUNTANT_PENDING_UPLOADS = """
SELECT COUNT(*) AS pending_uploads
FROM monthly_accounting_document mad
JOIN fact_aic_monthly_accounting fma ON mad.monthly_accounting_id = fma.id
JOIN client_assigned_accountants caa ON fma.client_id = caa.dimaicclient_id
WHERE caa.dimaicaccountant_id = %s
AND mad.status = 'pending'
"""

ACCOUNTANT_MONTHLY_ACCOUNTING_SUMMARY = """
SELECT
fma.status,
COUNT(*) AS count
FROM fact_aic_monthly_accounting fma
JOIN client_assigned_accountants caa ON fma.client_id = caa.dimaicclient_id
WHERE caa.dimaicaccountant_id = %s
GROUP BY fma.status
"""

ACCOUNTANT_RECENT_DOCUMENTS = """
SELECT
    mad.id AS document_id,
    c.id AS client_id,
    fma.id AS monthly_accounting_id,
    c.client_name,
    mad.doc_type,
    mad.status,
    mad.created_at,
    ELT(fma.month, 'January','February','March','April','May','June','July','August','September','October','November','December') AS month,
    fma.year
FROM monthly_accounting_document mad
JOIN fact_aic_monthly_accounting fma ON mad.monthly_accounting_id = fma.id
JOIN client c ON fma.client_id = c.id
JOIN client_assigned_accountants caa ON fma.client_id = caa.dimaicclient_id
WHERE caa.dimaicaccountant_id = %s
ORDER BY mad.created_at DESC
LIMIT 10
"""





REVIEWER_ASSIGNED_DOCUMENTS_COUNT = """
SELECT COUNT(*) AS assigned_documents_count
FROM monthly_accounting_document
WHERE assigned_reviewer_id = %s
"""

REVIEWER_PENDING_REVIEW_COUNT = """
SELECT COUNT(*) AS pending_review_count
FROM monthly_accounting_document
WHERE assigned_reviewer_id = %s
AND status = 'pending_review'
"""

REVIEWER_IN_REVIEW_COUNT = """
SELECT COUNT(*) AS in_review_count
FROM monthly_accounting_document
WHERE assigned_reviewer_id = %s
AND status = 'in_review'
"""

REVIEWER_COMPLETED_REVIEWS_COUNT = """
SELECT COUNT(*) AS completed_reviews_count
FROM monthly_accounting_document
WHERE assigned_reviewer_id = %s
AND status NOT IN ('pending_review', 'in_review')
"""

REVIEWER_DOCUMENT_STATUS_BREAKDOWN = """
SELECT
status,
COUNT(*) AS count
FROM monthly_accounting_document
WHERE assigned_reviewer_id = %s
GROUP BY status
"""

REVIEWER_RECENT_ASSIGNED_DOCUMENTS = """
SELECT
    mad.id AS document_id,
    c.id AS client_id,
    fma.id AS monthly_accounting_id,
    c.client_name,
    mad.doc_type,
    mad.status,
    mad.updated_at,
    ELT(fma.month, 'January','February','March','April','May','June','July','August','September','October','November','December') AS month,
    fma.year
FROM monthly_accounting_document mad
JOIN fact_aic_monthly_accounting fma ON mad.monthly_accounting_id = fma.id
JOIN client c ON fma.client_id = c.id
WHERE mad.assigned_reviewer_id = %s
ORDER BY mad.updated_at DESC
LIMIT 10
"""
