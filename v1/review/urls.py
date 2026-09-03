from rest_framework.routers import DefaultRouter

from v1.review.views import ReviewQueueViewSet

router = DefaultRouter()
router.register("documents", ReviewQueueViewSet, basename="review-document")

urlpatterns = router.urls
