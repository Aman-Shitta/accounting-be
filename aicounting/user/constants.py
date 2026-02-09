"""
Constants for user app API responses.
Contains standardized messages for different views to ensure consistent user-facing messages.
"""

# Client View Messages
ClientCreateViewMessages = {
    "success": "Client created successfully.",
    "error": "Failed to create client. Please check the provided information and try again.",
    "validation_error": "Please correct the errors in the form and try again.",
    "server_error": "An unexpected error occurred. Please try again later.",
}

ClientUpdateViewMessages = {
    "success": "Client information updated successfully.",
    "error": "Failed to update client information. Please try again.",
    "validation_error": "Please correct the errors in the form and try again.",
    "not_found": "Client not found.",
    "server_error": "An unexpected error occurred. Please try again later.",
}

ClientRetrieveViewMessages = {
    "success": "Client information retrieved successfully.",
    "not_found": "Client not found.",
    "error": "Failed to retrieve client information.",
}

ClientListViewMessages = {
    "success": "Client list retrieved successfully.",
    "error": "Failed to retrieve client list.",
}


ClientDocumentUploadMessages = {
    "success": "Document uploaded successfully.",
    "error": "Failed to upload document. Please try again.",
    "validation_error": "Invalid document. Please check the file and try again.",
}

# Accountant View Messages
AccountantInviteViewMessages = {
    "success": "Invitation sent successfully. The accountant will receive an email to complete registration.",
    "error": "Failed to send invitation. Please try again.",
    "validation_error": "Please correct the errors in the form and try again.",
    "already_exists": "An accountant with this email already exists.",
    "azure_error": "Failed to send invitation through Azure. Please try again later.",
}

AccountantListViewMessages = {
    "success": "Accountant list retrieved successfully.",
    "error": "Failed to retrieve accountant list.",
}


AzureInviteViewMessages = {
    "success": "Invitation sent successfully. The user will receive an email to complete registration.",
    "error": "Failed to send invitation. Please try again.",
    "validation_error": "Please correct the errors in the form and try again.",
    "already_exists": "A user with this email already exists.",
    "azure_error": "Failed to send invitation through Azure. Please try again later.",
}

    
# Contact View Messages
ContactCreateViewMessages = {
    "success": "Contact created successfully.",
    "error": "Failed to create contact. Please try again.",
    "validation_error": "Please correct the errors in the form and try again.",
}

