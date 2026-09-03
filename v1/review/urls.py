from django.urls import path

from v1.review.views import (
    ReviewClaimView,
    ReviewDocumentView,
    ReviewQueueView,
    ReviewSubmitView,
)

urlpatterns = [
    path("documents/", ReviewQueueView.as_view(), name="queue"),
    path("documents/<uuid:pk>/", ReviewDocumentView.as_view(), name="document"),
    path("documents/<uuid:pk>/claim/", ReviewClaimView.as_view(), name="claim"),
    path("documents/<uuid:pk>/submit/", ReviewSubmitView.as_view(), name="submit"),
]
