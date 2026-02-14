"""
Classification Queue Model

Stores pending GL classification requests to be processed sequentially
per assistant by Celery Beat.
"""

import uuid
from django.db import models
from django.utils import timezone

class ClassificationQueue(models.Model):
    """
    Queue for GL classification tasks.
    
    Tasks are processed one at a time per assistant to avoid
    concurrent access to the same OpenAI assistant.
    """
    
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        PROCESSING = 'processing', 'Processing'
        COMPLETED = 'completed', 'Completed'
        FAILED = 'failed', 'Failed'
    
    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False
    )
    
    document = models.ForeignKey(
        'account.MonthlyAccountingDocument',
        on_delete=models.CASCADE,
        related_name='classification_queue_items'
    )
    
    client_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Client ID - used for grouping tasks per client"
    )
    
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True
    )
    
    priority = models.IntegerField(
        default=0,
        help_text="Higher priority items are processed first"
    )
    
    error_message = models.TextField(
        blank=True,
        null=True
    )
    
    retry_count = models.IntegerField(default=0)
    max_retries = models.IntegerField(default=3)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        db_table = 'classification_queue'
        ordering = ['-priority', 'created_at']
        verbose_name = 'Classification Queue Item'
        verbose_name_plural = 'Classification Queue Items'
        indexes = [
            models.Index(fields=['client_id', 'status', 'created_at']),
        ]
    
    def __str__(self):
        return f"Classification for {self.document_id} ({self.status})"
    
    @classmethod
    def enqueue(cls, document, client_id: str, priority: int = 0):
        """
        Add a document to the classification queue.
        
        Args:
            document: MonthlyAccountingDocument instance
            client_id: Client ID for grouping tasks
            priority: Higher values processed first
            
        Returns:
            ClassificationQueue instance
        """
        # Check if already queued (pending or processing)
        existing = cls.objects.filter(
            document=document,
            status__in=[cls.Status.PENDING, cls.Status.PROCESSING]
        ).first()
        
        if existing:
            return existing
        
        return cls.objects.create(
            document=document,
            client_id=client_id,
            priority=priority
        )
    
    @classmethod
    def get_next_for_client(cls, client_id: str):
        """
        Get the next pending item for a client.
        
        Returns None if there's already a processing item for this client.
        
        Args:
            client_id: Client ID
            
        Returns:
            ClassificationQueue instance or None
        """
        # Check if there's already a processing item for this client
        processing = cls.objects.filter(
            client_id=client_id,
            status=cls.Status.PROCESSING
        ).exists()
        
        if processing:
            return None
        
        # Get next pending item
        return cls.objects.filter(
            client_id=client_id,
            status=cls.Status.PENDING
        ).order_by('-priority', 'created_at').first()
    
    @classmethod
    def get_all_pending_clients(cls):
        """
        Get list of client IDs that have pending items.
        
        Returns:
            List of client_id strings
        """
        return list(
            cls.objects.filter(status=cls.Status.PENDING)
            .values_list('client_id', flat=True)
            .distinct()
        )
    
    def mark_processing(self):
        """Mark this item as processing."""
        self.status = self.Status.PROCESSING
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at', 'updated_at'])
    
    def mark_completed(self):
        """Mark this item as completed."""
        self.status = self.Status.COMPLETED
        self.completed_at = timezone.now()
        self.save(update_fields=['status', 'completed_at', 'updated_at'])
    
    def mark_failed(self, error_message: str):
        """
        Mark this item as failed.
        
        If retries remaining, set back to pending for retry.
        """
        self.retry_count += 1
        self.error_message = error_message
        
        if self.retry_count < self.max_retries:
            # Retry later
            self.status = self.Status.PENDING
        else:
            # Max retries reached
            self.status = self.Status.FAILED
            self.completed_at = timezone.now()
        
        self.save(update_fields=[
            'status', 'retry_count', 'error_message', 
            'completed_at', 'updated_at'
        ])
