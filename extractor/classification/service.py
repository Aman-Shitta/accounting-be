"""
GL classification.

Runs after extraction (and after control-total validation, when that applies)
to assign a ledger account to every transaction, using the client's classifier
profile — an OpenAI assistant backed by a vector store built from the client's
chart of accounts.
"""

import logging

from django.utils import timezone

from v1.periods.models import PeriodDocument, PeriodTransaction

logger = logging.getLogger(__name__)


class DocumentNotFoundError(Exception):
    """No document with that id."""


class ClassifierUnavailableError(Exception):
    """
    The client has no usable classifier profile.

    Raised rather than returning zero, so a missing profile surfaces as a
    failure instead of looking like a document with nothing to classify.
    """


class GLClassificationService:
    """Assigns ledger accounts to a document's extracted transactions."""

    def __init__(self, document: PeriodDocument):
        self.document = document

    @classmethod
    def from_document_id(cls, document_id) -> "GLClassificationService":
        document = (
            PeriodDocument.objects.filter(id=document_id)
            .select_related("period__client", "document_source")
            .first()
        )
        if document is None:
            raise DocumentNotFoundError(f"Document not found: {document_id}")
        return cls(document)

    @property
    def client(self):
        return self.document.period.client

    # ---- check enrichment --------------------------------------------------

    def enrich_check_descriptions(self) -> int:
        """
        Fold payee and memo from check images into the transaction
        description, so the classifier sees "Check 1042 | Payee: Acme Supply"
        rather than an opaque check number.
        """
        enriched = 0
        details = self.document.check_details.filter(
            transaction__isnull=False
        ).select_related("transaction")

        for detail in details:
            transaction = detail.transaction
            parts = [transaction.description or ""]

            for label, value in (("Payee", detail.payee), ("Memo", detail.memo)):
                text = (value or "").strip()
                if text and text.lower() != "null" and label not in parts[0]:
                    parts.append(f"{label}: {text}")

            if len(parts) == 1:
                continue

            transaction.description = " | ".join(p for p in parts if p)
            transaction.save(update_fields=["description", "updated_at"])
            enriched += 1

        logger.info(f"Enriched {enriched} check descriptions")
        return enriched

    # ---- classification ----------------------------------------------------

    def classify_transactions(self) -> int:
        """
        Classify every unclassified transaction on the document.

        Returns the number assigned an account. Raises
        :class:`ClassifierUnavailableError` when the client has no usable
        classifier profile.
        """
        from extractor.classification.classifier import GLClassifier
        from v1.ledger.models import LedgerAccount

        profile = getattr(self.client, "classifier_profile", None)
        if profile is None or not profile.is_usable:
            raise ClassifierUnavailableError(
                f"Client {self.client.id} has no usable classifier profile; "
                f"upload a chart of accounts to provision one."
            )

        self.enrich_check_descriptions()

        transactions = list(
            PeriodTransaction.objects.filter(document=self.document)
            .select_related("ledger_account")
            .order_by("page_number", "line_number")
        )
        if not transactions:
            logger.info(f"No transactions to classify on document {self.document.id}")
            return 0

        logger.info(f"Classifying {len(transactions)} transactions")

        source = self.document.document_source
        classifier = GLClassifier(
            vector_store_ids=[profile.vector_store_id],
            model=profile.model_name,
            response_schema=profile.response_schema,
            special_rules=source.extraction_notes if source else "",
        )

        classified_pages = classifier.classify_extracted_data(
            self._as_classifier_input(transactions)
        )

        return self._apply(transactions, classified_pages or {}, LedgerAccount)

    def _as_classifier_input(self, transactions: list) -> dict:
        """Shape transactions as ``{page: {"line_items": {line: {...}}}}``."""
        pages: dict = {}

        for txn in transactions:
            amount = float(txn.amount) if txn.amount is not None else None
            is_debit = txn.direction == PeriodTransaction.Direction.DEBIT

            page = pages.setdefault(txn.page_number, {"line_items": {}})
            page["line_items"][txn.line_number] = {
                "id": txn.line_number,
                "description": txn.description or "",
                "debit_amount": amount if is_debit else None,
                "credit_amount": None if is_debit else amount,
                "transaction_type": txn.direction,
            }

        return pages

    def _apply(self, transactions: list, classified_pages: dict, LedgerAccount) -> int:
        """
        Write the classifier's account numbers back, resolving each to a real
        ledger account for this client. Already-classified rows are left alone.
        """
        by_position = {(t.page_number, t.line_number): t for t in transactions}
        accounts = {
            a.account_number: a
            for a in LedgerAccount.objects.filter(client=self.client, is_active=True)
        }

        updated = []
        now = timezone.now()

        for page_number, page in classified_pages.items():
            items = page.values() if isinstance(page, dict) else page

            for item in items:
                try:
                    line_number = int(item.get("id", 0))
                except (TypeError, ValueError):
                    logger.warning(f"Classifier returned an unusable line id: {item!r}")
                    continue

                target = by_position.get((int(page_number), line_number))
                if target is None or target.ledger_account_id:
                    continue

                account = accounts.get(str(item.get("gl_account") or "").strip())
                if account is None:
                    continue

                target.ledger_account = account
                target.classified_at = now
                updated.append(target)

        if updated:
            PeriodTransaction.objects.bulk_update(
                updated, ["ledger_account", "classified_at"]
            )

        logger.info(f"Classified {len(updated)} transactions on document {self.document.id}")
        return len(updated)
