"""
Centralized Persistence Layer for Extraction Results

Provides dedicated saver classes so pipeline implementations
focus purely on extraction logic, not database operations.
"""

from .attribute_saver import AttributeSaver
from .bank_statement_saver import BankStatementSaver

__all__ = ["BankStatementSaver", "AttributeSaver"]
