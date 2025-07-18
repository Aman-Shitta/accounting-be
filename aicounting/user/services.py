# user/services.py

from django.contrib.auth import get_user_model
from user.models import DimAICCustomer, DimAICUser


def create_customer(request_user, customer_name, email, street='', city='', state_abrevation='', zip_code=None):
    User = get_user_model()
    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            "username": email,
            "is_active": False,
        }
    )
    if not created:
        return None, "User with this email already exists."

    customer = DimAICCustomer.objects.create(
        system_user=user,
        customer_name=customer_name,
        street=street,
        city=city,
        state_abrevation=state_abrevation,
        zip_code=zip_code or 0,
        input_user=request_user
    )
    return customer,

def create_user_for_customer(cust_id, email, first_name='', last_name=''):
    User = get_user_model()
    user, created = User.objects.get_or_create(
        email=email,
        defaults={
            "username": email,
            "is_active": False,
        }
    )
    if not created:
        return None, "User with this email already exists."

    try:
        customer = DimAICCustomer.objects.get(pk=cust_id)
    except DimAICCustomer.DoesNotExist:
        return None, "Customer does not exist."

    DimAICUser.objects.create(
        system_user=user,
        cust_id=customer,
        username=email,
        first_name=first_name,
        last_name=last_name,
        email=email,
    )
    return user
