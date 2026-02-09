# Third-party imports
from django.db import models

# Local imports
from .dim_aic_client_model import DimAICClient


class DimAICAssistant(models.Model):
    """
    Model to store OpenAI Assistant configurations and metadata for each client.
    """
    
    client = models.OneToOneField(
        DimAICClient,
        on_delete=models.CASCADE,
        related_name="assistant",
        verbose_name="Client"
    )
    
    assistant_id = models.CharField(
        max_length=255,
        verbose_name="OpenAI Assistant ID",
        help_text="The OpenAI Assistant ID for this client"
    )
    
    vector_store_id = models.CharField(
        max_length=255,
        verbose_name="Vector Store ID",
        help_text="The OpenAI Vector Store ID containing client's documents"
    )
    
    assistant_name = models.CharField(
        max_length=255,
        verbose_name="Assistant Name"
    )
    
    model_name = models.CharField(
        max_length=100,
        default="gpt-4o",
        verbose_name="OpenAI Model"
    )
    
    temperature = models.FloatField(
        default=1.0,
        verbose_name="Temperature",
        help_text="Controls randomness in responses (0.0 to 2.0)"
    )
    
    top_p = models.FloatField(
        default=1.0,
        verbose_name="Top P",
        help_text="Controls diversity of responses (0.0 to 1.0)"
    )
    
    response_schema = models.JSONField(
        verbose_name="Response Format Schema",
        help_text="JSON schema response format"
    )
    
    special_rules = models.TextField(
        blank=True,
        null=True,
        verbose_name="Special Rules",
        help_text="Additional client-specific rules for the assistant"
    )
    
    is_active = models.BooleanField(
        default=True,
        verbose_name="Is Active"
    )
    
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Created At"
    )
    
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At"
    )
    
    class Meta:
        db_table = 'assistant'
        verbose_name = "Assistant"
        verbose_name_plural = "Assistants"
    
    def __str__(self):
        return f"Assistant for {self.client.client_name}"
