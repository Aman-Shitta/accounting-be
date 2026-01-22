"""
Document Rectification Module

This module provides AI-powered rectification of extracted document data
using Google Gemini to verify and correct OCR/extraction errors.

Rectifiers:
- DocumentRectifier: Original rectifier that verifies amounts visually one by one
- DocumentRectifierV1: V1 rectifier that extracts independently and compares/merges
"""

from .rectify import DocumentRectifier
from .rectify_v1 import DocumentRectifierV1, get_rectifier_v1

__all__ = ['DocumentRectifier', 'DocumentRectifierV1', 'get_rectifier_v1']
