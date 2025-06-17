from rest_framework.response import Response


def create_api_response(status_code, message, data=None):
    """
    Creates a consistent API response.

    Args:
        status_code (int): HTTP status code.
        message (str): Message string.
        data (dict, optional): Additional data to include.

    Returns:
        Response: Django REST framework Response object.
    """
    # Sanitize data for nested errors if present
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, dict) and "error" in value:
                error = value.get("error", "Unknown error - Contact Admin")
                data[key] = {"error": error}

    response = {
        "status": get_status_from_code(status_code),
        "status_code": status_code,
        "message": message,
    }

    if data is not None:
        response["data"] = data

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
