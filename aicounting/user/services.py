# user/services.py

import random
import string
from django.contrib.auth import get_user_model
from user.models import DimAICCustomer


def create_customer_and_user(customer_name, email, street='', city='', street_abrevation='', zip_code=None):
    User = get_user_model()

    user = User.objects.create_user(
        username=email,
        email=email,
        password=None,
        is_active=False
    )

    invite_token = ''.join(random.choices(string.ascii_letters + string.digits, k=32))

    customer = DimAICCustomer.objects.create(
        system_user=user,
        customer_name=customer_name,
        street=street,
        city=city,
        street_abrevation=street_abrevation,
        zip_code=zip_code or 0,
        invite_token=invite_token,
        input_user=None  # You can set this to request.user if admin is authenticated
    )

    return customer, invite_token
