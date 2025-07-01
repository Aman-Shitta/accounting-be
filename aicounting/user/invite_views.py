from aicounting.response import create_api_response

from rest_framework.views import APIView

from user.invite_serializers import CustomerInviteSerializer
# Create your views here.
from rest_framework import status

class CustomerInviteView(APIView):
    def post(self, request):

        serializer = CustomerInviteSerializer(data=request.data)

        if not serializer.is_valid():
            return create_api_response(**{
                "status": status.HTTP_400_BAD_REQUEST,
                "message": "Invalid data",
                "errors": serializer.errors
            })

        customer, invite_token = serializer.save()

        invite_link = f"https://localhost:8000/invite/accept/?token={invite_token}"

        return create_api_response(**{
            "status_code": status.HTTP_201_CREATED,
            "message": "Customer invited successfully",
            "data": {
                "invite_link": invite_link,
                "customer_id": customer.customer_id,
                "customer_name": customer.customer_name
            }
       })