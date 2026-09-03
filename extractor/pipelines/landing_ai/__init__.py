"""
LandingAI Extraction Pipeline

Extraction via LandingAI ADE → Rectification via Gemini.
This is the current production pipeline for bank statements and credit cards.
"""

from .pipeline import ExtractorPipeline

__all__ = ["ExtractorPipeline"]
