from rest_framework.response import Response


def create_api_response(status_code, message, data=None, errors=None, **kwargs):
    """
    Creates a consistent API response with proper error handling.

    Args:
        status_code (int): HTTP status code.
        message (str): User-friendly message string.
        data (dict/list, optional): Response data for successful requests.
        errors (dict, optional): Field-level validation errors.
        **kwargs: Additional key-value pairs to include in response.

    Returns:
        Response: Django REST framework Response object.
        
    Response Format:
        {
            "status": "success" or "error",
            "status_code": int,
            "message": str,
            "data": dict/list (for successful responses),
            "errors": {
                "field_name": ["error1", "error2"],
                ...
            } (for validation errors)
        }
    """
    response = {
        "status": get_status_from_code(status_code),
        "status_code": status_code,
        "message": message,
    }

    # Add data for successful responses or when explicitly provided
    if data is not None:
        response["data"] = data
    
    # Add structured field errors if provided
    if errors is not None:
        response["errors"] = format_serializer_errors(errors)

    # Add any additional kwargs
    for k, v in kwargs.items():
        response[k] = v

    return Response(response, status=status_code)


def format_serializer_errors(errors):
    """
    Format Django REST Framework serializer errors into a consistent structure.
    
    Args:
        errors (dict): Serializer errors from serializer.errors
        
    Returns:
        dict: Formatted errors with field names as keys and error lists as values
        
    Example:
        Input: {'email': [ErrorDetail(string='This field is required.', code='required')]}
        Output: {'email': ['This field is required.']}
    """
    formatted_errors = {}
    
    if isinstance(errors, dict):
        for field, error_list in errors.items():
            if isinstance(error_list, list):
                # Convert ErrorDetail objects to strings
                formatted_errors[field] = [str(error) for error in error_list]
            elif isinstance(error_list, dict):
                # Handle nested errors (e.g., from nested serializers)
                formatted_errors[field] = format_serializer_errors(error_list)
            else:
                formatted_errors[field] = [str(error_list)]
    elif isinstance(errors, list):
        # Handle non-field errors
        formatted_errors["non_field_errors"] = [str(error) for error in errors]
    else:
        formatted_errors["non_field_errors"] = [str(errors)]
    
    return formatted_errors


def get_status_from_code(status_code):
    """
    Maps HTTP status codes to 'success' or 'error'.

    Args:
        status_code (int): The HTTP status code.

    Returns:
        str: 'success' for 2xx, 'error' otherwise.
    """
    if 200 <= status_code < 300:
        return "success"
    elif 400 <= status_code < 600:
        return "error"
    return "error"
