from rest_framework.response import Response


def create_api_response(status_code, message, data=None, **kwargs):
    """
    Creates a consistent API response.

    Args:
        status_code (int): HTTP status code.
        message (str): Message string.
        data (dict, optional): Additional data to include.

    Returns:
        Response: Django REST framework Response object.
    """
    response = {
        "status": get_status_from_code(status_code),
        "status_code": status_code,
        "message": message,
    }

    # If data is a dict and looks like serializer errors, put under 'errors'
    if isinstance(data, dict):
        # If any value is a list or dict, treat as field errors
        if any(isinstance(v, (list, dict)) for v in data.values()):
            response["errors"] = data
        else:
            response["data"] = data
    elif data is not None:
        response["data"] = data

    for k, v in kwargs.items():
        response[k] = v

    return Response(response, status=status_code)


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
