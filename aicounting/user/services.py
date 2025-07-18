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


def create_user_for_customer(request_user, customer_name, email, street='', city='', state_abrevation='', zip_code=None):
    """
    Create a customer invite with non-verified state.
    Returns error if customer already exists.
    """
    User = get_user_model()

    # Check if customer already exists
    existing_customer = DimAICCustomer.objects.filter(
        system_user__email=email
    ).first()

    if existing_customer:
        return None, f"Customer with email {email} already exists."

    # Check if user already exists
    existing_user = User.objects.filter(email=email).first()
    if existing_user:
        return None, f"User with email {email} already exists."

    # Create user with non-verified state
    user = User.objects.create(
        email=email,
        username=email,
        is_active=False,  # Non-verified state
        first_name='',
        last_name=''
    )

    # Create customer record with non-verified state
    customer = DimAICCustomer.objects.create(
        system_user=user,
        customer_name=customer_name,
        street=street,
        city=city,
        state_abrevation=state_abrevation,
        zip_code=zip_code or 0,
        input_user=request_user,
        # Add any additional fields for verification status if needed
    )

    return customer, None