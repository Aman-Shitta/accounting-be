# user/services.py

# System imports
import os

# Third-party imports
from django.contrib.auth import get_user_model

# Local imports
from user.models import DimAICAccountant, DimAICAssistant, DimAICClient, DimAICCustomer, DimAICReviewer
from user.utils import OpenAIAssistant


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


def create_user_for_accountant(request_user, customer, user_email, user_name, first_name='', last_name=''):
    """
    Create an accountant with non-verified state.
    Returns error if accountant already exists.
    """
    User = get_user_model()

    # Check if accountant already exists
    existing_accountant = DimAICAccountant.objects.filter(
        system_user__email=user_email
    ).first()

    if existing_accountant:
        return None, f"Accountant with email {user_email} already exists."

    # Check if user already exists
    existing_user = User.objects.filter(email=user_email).first()
    if existing_user:
        return None, f"User with email {user_email} already exists."

    # Create user with non-verified state
    user = User.objects.create(
        email=user_email,
        username=user_name,
        is_active=False,
        first_name=first_name,
        last_name=last_name
    )

    # Create accountant record with non-verified state
    accountant = DimAICAccountant.objects.create(
        system_user=user,
        customer=customer,
        input_user=request_user,
        username=user_name,
        first_name=first_name,
        last_name=last_name,
        email=user_email
    )

    return accountant, None


def create_user_for_reviewer(request_user, user_email):
    User = get_user_model()

    # Check if reviewer already exists
    existing_reviewer = DimAICReviewer.objects.filter(
        system_user__email=user_email
    ).first()

    if existing_reviewer:
        return None, f"Reviewer with email {user_email} already exists."

    # Check if user already exists
    existing_user = User.objects.filter(email=user_email).first()
    if existing_user:
        return None, f"User with email {user_email} already exists."

    # Create user with non-verified state
    user = User.objects.create(
        email=user_email,
        username=user_email,
        is_active=False,
    )

    # Create accountant record with non-verified state
    reviewer = DimAICReviewer.objects.create(
        system_user=user,
        email=user_email
    )

    return reviewer, None


class AssistantService:
    """
    Service class for managing OpenAI Assistants across different pipelines
    """

    @staticmethod
    def get_assistant_for_client(client_id: int):
        """
        Get an existing assistant configuration for a client

        Args:
            client_id (int): The AICClient primary key

        Returns:
            DimAICAssistant: The assistant configuration or None if not found
        """
        try:
            client = DimAICClient.objects.get(client_id=client_id)
            return DimAICAssistant.objects.get(client=client, is_active=True)
        except (DimAICClient.DoesNotExist, DimAICAssistant.DoesNotExist):
            return None

    @staticmethod
    def create_or_get_assistant(client_id: int, api_key: str, schema_path: str = None, special_rules: str = None):
        """
        Create a new assistant or get existing one for a client

        Args:
            client_id (int): The AICClient primary key
            api_key (str): OpenAI API key
            schema_path (str): Path to JSON schema file
            special_rules (str): Additional rules for the assistant

        Returns:
            tuple: (OpenAIAssistant instance, DimAICAssistant config)
        """
        # Check if assistant already exists
        existing_config = AssistantService.get_assistant_for_client(client_id)

        if existing_config:
            # Return existing assistant
            assistant = OpenAIAssistant(
                customer=existing_config.client.customer,
                api_key=api_key,
                special_rules=existing_config.special_rules,
                schema_path=existing_config.response_format_schema_path
            )
            assistant.client_id = client_id
            assistant.assistant_id = existing_config.assistant_id
            assistant.vector_store_id = existing_config.vector_store_id
            assistant.aic_client = existing_config.client

            return assistant, existing_config

        # Create new assistant
        assistant = OpenAIAssistant(
            api_key=api_key,
            special_rules=special_rules,
            schema_path=schema_path
        )

        # Initialize assistant for client
        config = assistant(client_id=client_id)

        return assistant, config

    @staticmethod
    def create_thread_and_process(client_id: int, api_key: str, message: str, schema_path: str = None):
        """
        Complete workflow: get assistant, create thread, send message, get response

        Args:
            client_id (int): The AICClient primary key
            api_key (str): OpenAI API key
            message (str): Message to send to assistant
            schema_path (str): Path to JSON schema file

        Returns:
            str: Assistant response or None if error
        """
        try:
            # Get or create assistant
            assistant, config = AssistantService.create_or_get_assistant(
                client_id=client_id,
                api_key=api_key,
                schema_path=schema_path
            )

            # Create thread
            thread = assistant.create_thread()
            if not thread:
                return None

            # Send message and get response
            response = assistant.send_message(thread.id, message)
            return response

        except Exception as e:
            logger.error(f"Error in processing: {e}")
            return None

    @staticmethod
    def update_assistant_rules(client_id: int, special_rules: str):
        """
        Update special rules for an existing assistant

        Args:
            client_id (int): The AICClient primary key
            special_rules (str): New special rules
        """
        config = AssistantService.get_assistant_for_client(client_id)
        if config:
            config.special_rules = special_rules
            config.save()
            return config
        return None

    @staticmethod
    def deactivate_assistant(client_id: int):
        """
        Deactivate an assistant for a client

        Args:
            client_id (int): The AICClient primary key
        """
        config = AssistantService.get_assistant_for_client(client_id)
        if config:
            config.is_active = False
            config.save()
            return True
        return False
