"""
GL classification service.

Runs after extraction succeeds (optionally after control-total validation)
to classify each line item against the client's chart of accounts via the
Responses API + vector stores.
"""

import logging

from account.models.monthly_accounting_document_model import MonthlyAccountingDocument

logger = logging.getLogger(__name__)


class DocumentNotFoundError(Exception):
    """Raised when a document ID cannot be found."""
    pass


class GLClassificationService:
    """
    Service for GL account classification operations.

    Handles the classification of line items in processed documents.
    """

    def __init__(self, document: MonthlyAccountingDocument):
        self.document = document

    @classmethod
    def from_document_id(cls, document_id: str) -> "GLClassificationService":
        """Create service from document ID."""
        try:
            document = MonthlyAccountingDocument.objects.get(id=document_id)
            return cls(document)
        except MonthlyAccountingDocument.DoesNotExist:
            raise DocumentNotFoundError(f"Document not found: {document_id}")

    def enrich_check_descriptions(self) -> int:
        """
        Enrich check transaction descriptions with payee/memo info.

        Returns:
            Number of descriptions enriched
        """
        enriched_count = 0

        check_items = self.document.check_items.filter(
            related_line_item__isnull=False
        ).select_related('related_line_item')

        for check_item in check_items:
            line_item = check_item.related_line_item
            description_parts = [line_item.description or ""]

            if check_item.payee and check_item.payee.strip():
                raw_payee = check_item.payee.strip()
                if raw_payee.lower() != "null":
                    payee_info = f"Payee: {raw_payee}"
                    if payee_info not in description_parts[0]:
                        description_parts.append(payee_info)

            if check_item.memo and check_item.memo.strip():
                raw_memo = check_item.memo.strip()
                if raw_memo.lower() != "null":
                    memo_info = f"Memo: {raw_memo}"
                    if memo_info not in description_parts[0]:
                        description_parts.append(memo_info)

            if len(description_parts) > 1:
                line_item.description = " | ".join(description_parts)
                line_item.save(update_fields=['description'])
                enriched_count += 1

        logger.info(
            f"Enriched {enriched_count} check descriptions for document {self.document.id}")
        return enriched_count

    def classify_line_items(self) -> int:
        """
        Classify GL accounts for all line items in the document.

        Uses the Responses API (classify_v2) for stateless, isolated
        classification — safe for concurrent multi-client processing.

        Returns:
            Number of line items classified
        """
        from account.models.monthly_document_line_models import MonthlyDocumentBankLineItem
        from account.models import DimAICGLAcct
        from extractor.classification.classifier import GLClassifier

        input_file_rules = (
            self.document.input_file_snapshot.description
            if self.document.input_file_snapshot else ""
        )

        self.enrich_check_descriptions()

        client_assistant = getattr(
            self.document.monthly_accounting.client, 'assistant', None)
        vector_store_ids = (
            [client_assistant.vector_store_id]
            if client_assistant and client_assistant.vector_store_id else []
        )

        classified_count = 0

        if vector_store_ids:
            try:
                line_items_qs = MonthlyDocumentBankLineItem.objects.filter(
                    document=self.document
                ).select_related('gl_account', 'offset_gl_account').order_by('page_number', 'line_number')

                default_offset_gl = self._get_default_offset_gl()
                line_items_qs.update(offset_gl_account=default_offset_gl)

                line_items_list = list(line_items_qs)

                if not line_items_list:
                    logger.info(
                        f"No line items to classify for document {self.document.id}")
                    return 0

                logger.info(
                    f"Processing {len(line_items_list)} line items for classification")

                extracted_data = self._build_extracted_data(line_items_list)

                classifier = GLClassifier(
                    vector_store_ids=vector_store_ids,
                    model=client_assistant.model_name if client_assistant else "gpt-4o",
                    response_schema=client_assistant.response_schema if client_assistant else None,
                    special_rules=input_file_rules,
                )

                classified_pages = classifier.classify_extracted_data(
                    extracted_data)

                line_items_by_page = {}
                for li in line_items_list:
                    line_items_by_page.setdefault(li.page_number, {})[
                        li.line_number] = li

                updated_items = []
                for page_num, page_data in (classified_pages or {}).items():
                    iterable = page_data.values() if isinstance(page_data, dict) else page_data
                    for cls_item in iterable:
                        try:
                            line_num = int(cls_item.get('id', 0))
                            target = line_items_by_page.get(
                                int(page_num), {}).get(line_num)

                            if not target or target.gl_account:
                                continue

                            gl_identifier = cls_item.get('gl_account')
                            if gl_identifier:
                                resolved_gl = DimAICGLAcct.objects.filter(
                                    client_id=self.document.monthly_accounting.client,
                                    account_number=str(gl_identifier).strip()
                                ).first()

                                if resolved_gl:
                                    target.gl_account = resolved_gl
                                    updated_items.append(target)
                        except Exception as e:
                            logger.warning(
                                f"Skipping classification item: {e}")

                if updated_items:
                    MonthlyDocumentBankLineItem.objects.bulk_update(
                        updated_items, ['gl_account']
                    )
                    classified_count = len(updated_items)

            except Exception as e:
                logger.error(
                    f"Classification failed for document {self.document.id}: {e}")

        logger.info(
            f"Classified {classified_count} line items for document {self.document.id}")
        return classified_count

    def _build_extracted_data(self, line_items: list) -> dict:
        """
        Build extracted data structure for a batch of line items.

        Returns:
            Dict structured as {page_number: {"line_items": {line_number: {...}}}}
        """
        extracted = {}

        for li in line_items:
            page_dict = extracted.setdefault(
                li.page_number, {"line_items": {}})
            txn_type = li.transaction_type

            debit_amount = None
            credit_amount = None
            if txn_type == 'debit':
                debit_amount = float(
                    li.amount) if li.amount is not None else None
            elif txn_type == 'credit':
                credit_amount = float(
                    li.amount) if li.amount is not None else None
            else:
                if li.amount is not None:
                    debit_amount = float(li.amount)

            page_dict["line_items"][li.line_number] = {
                "id": li.line_number,
                "description": li.description or "",
                "debit_amount": debit_amount,
                "credit_amount": credit_amount,
                "transaction_type": txn_type or ("debit" if debit_amount else "credit")
            }

        return extracted

    def _get_default_offset_gl(self):
        """Get default offset GL account from input file snapshot."""
        if not self.document.input_file_snapshot:
            return None

        bank_attributes = self.document.input_file_snapshot.attribute_snapshots.all()
        if bank_attributes.count() == 1:
            return bank_attributes.first().offset_gl_account
        return None
