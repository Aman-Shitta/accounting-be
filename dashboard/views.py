import logging


from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated

from aicounting.response import create_api_response
from authentication import authenticate
from authentication.permissions import IsCustomer, IsAccountant, IsReviewer

from dashboard import queries

from dashboard.query_helper import RawSQLMixin

logger = logging.getLogger(__name__)




class CustomerDashboardView(generics.GenericAPIView):
    """
    GET /api/v1/dashboard/customer/

    Returns aggregated metrics for the authenticated customer:
      - total_clients, total_accountants, total_gl_accounts
      - total_je_templates, total_input_files
      - monthly_accounting_by_status, document_status_summary
      - recent_monthly_accountings
    """
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsCustomer]

    def get(self, request, *args, **kwargs):
        try:
            raw_sql = RawSQLMixin()
            customer = request.user.customer_profile
            cid = [customer.id]

            # Scalar counts
            counts = {}
            counts.update(raw_sql._fetch_one(queries.CUSTOMER_TOTAL_CLIENTS, cid))
            counts.update(raw_sql._fetch_one(queries.CUSTOMER_TOTAL_ACCOUNTANTS, cid))
            counts.update(raw_sql._fetch_one(queries.CUSTOMER_TOTAL_GL_ACCOUNTS, cid))
            counts.update(raw_sql._fetch_one(queries.CUSTOMER_TOTAL_JE_TEMPLATES, cid))
            counts.update(raw_sql._fetch_one(queries.CUSTOMER_TOTAL_INPUT_FILES, cid))

            # Status breakdowns
            monthly_status = raw_sql._status_dict(
                raw_sql._fetch_all(queries.CUSTOMER_MONTHLY_ACCOUNTING_BY_STATUS, cid)
            )
            document_status = raw_sql._status_dict(
                raw_sql._fetch_all(queries.CUSTOMER_DOCUMENT_STATUS_SUMMARY, cid)
            )

            # Recent items
            recent = raw_sql._fetch_all(queries.CUSTOMER_RECENT_MONTHLY_ACCOUNTINGS, cid)
            # Convert datetime objects to ISO strings for JSON serialization
            for row in recent:
                if row.get("created_at"):
                    row["created_at"] = row["created_at"].isoformat()

            data = {
                **counts,
                "monthly_accounting_by_status": monthly_status,
                "document_status_summary": document_status,
                "recent_monthly_accountings": recent,
            }

            return create_api_response(
                status.HTTP_200_OK,
                "Customer dashboard data retrieved successfully.",
                data=data,
            )

        except Exception as e:
            logger.error(f"Error fetching customer dashboard: {e}", exc_info=True)
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while fetching dashboard data.",
                data={"error": str(e)},
            )


class AccountantDashboardView(generics.GenericAPIView):
    """
    GET /api/v1/dashboard/accountant/

    Returns aggregated metrics for the authenticated accountant:
      - assigned_clients_count, total_documents, pending_uploads
      - document_status_breakdown, monthly_accounting_by_status
      - recent_documents
    """
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAccountant]

    def get(self, request, *args, **kwargs):
        try:
            from user.models import DimAICAccountant
            raw_sql = RawSQLMixin()
            accountant = request.user.accountant_profile
            aid = [accountant.id]

            # Scalar counts
            counts = {}
            counts.update(raw_sql._fetch_one(queries.ACCOUNTANT_ASSIGNED_CLIENTS_COUNT, aid))
            counts.update(raw_sql._fetch_one(queries.ACCOUNTANT_TOTAL_DOCUMENTS, aid))
            counts.update(raw_sql._fetch_one(queries.ACCOUNTANT_PENDING_UPLOADS, aid))

            # Status breakdowns
            doc_status = raw_sql._status_dict(
                raw_sql._fetch_all(queries.ACCOUNTANT_DOCUMENT_STATUS_BREAKDOWN, aid)
            )
            monthly_status = raw_sql._status_dict(
                raw_sql._fetch_all(queries.ACCOUNTANT_MONTHLY_ACCOUNTING_SUMMARY, aid)
            )

            # Recent items
            recent = raw_sql._fetch_all(queries.ACCOUNTANT_RECENT_DOCUMENTS, aid)
            for row in recent:
                if row.get("created_at"):
                    row["created_at"] = row["created_at"].isoformat()

            data = {
                **counts,
                "document_status_breakdown": doc_status,
                "monthly_accounting_by_status": monthly_status,
                "recent_documents": recent,
            }

            return create_api_response(
                status.HTTP_200_OK,
                "Accountant dashboard data retrieved successfully.",
                data=data,
            )

        except Exception as e:
            logger.error(f"Error fetching accountant dashboard: {e}", exc_info=True)
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while fetching dashboard data.",
                data={"error": str(e)},
            )


class ReviewerDashboardView(generics.GenericAPIView):
    """
    GET /api/v1/dashboard/reviewer/

    Returns aggregated metrics for the authenticated reviewer:
      - assigned_documents_count, pending_review_count
      - in_review_count, completed_reviews_count
      - document_status_breakdown
      - recent_assigned_documents
    """
    authentication_classes = [authenticate.JSONWebTokenAuthentication]
    permission_classes = [IsAuthenticated, IsReviewer]

    def get(self, request, *args, **kwargs):
        try:
            raw_sql = RawSQLMixin()
            reviewer = request.user.reviewer_profile
            rid = [reviewer.id]

            # Scalar counts
            counts = {}
            counts.update(raw_sql._fetch_one(queries.REVIEWER_ASSIGNED_DOCUMENTS_COUNT, rid))
            counts.update(raw_sql._fetch_one(queries.REVIEWER_PENDING_REVIEW_COUNT, rid))
            counts.update(raw_sql._fetch_one(queries.REVIEWER_IN_REVIEW_COUNT, rid))
            counts.update(raw_sql._fetch_one(queries.REVIEWER_COMPLETED_REVIEWS_COUNT, rid))

            # Status breakdown
            doc_status = raw_sql._status_dict(
                raw_sql._fetch_all(queries.REVIEWER_DOCUMENT_STATUS_BREAKDOWN, rid)
            )

            # Recent items
            recent = raw_sql._fetch_all(queries.REVIEWER_RECENT_ASSIGNED_DOCUMENTS, rid)
            for row in recent:
                if row.get("updated_at"):
                    row["updated_at"] = row["updated_at"].isoformat()

            data = {
                **counts,
                "document_status_breakdown": doc_status,
                "recent_assigned_documents": recent,
            }

            return create_api_response(
                status.HTTP_200_OK,
                "Reviewer dashboard data retrieved successfully.",
                data=data,
            )

        except Exception as e:
            logger.error(f"Error fetching reviewer dashboard: {e}", exc_info=True)
            return create_api_response(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                "An error occurred while fetching dashboard data.",
                data={"error": str(e)},
            )
