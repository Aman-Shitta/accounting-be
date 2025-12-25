"""
Document Rectification Module

This module provides AI-powered rectification of extracted document data
using Google Gemini to verify and correct OCR/extraction errors.
"""

from .rectify import DocumentRectifier

__all__ = ['DocumentRectifier']
