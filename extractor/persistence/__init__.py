"""
Centralized Persistence Layer for Extraction Results

Provides dedicated saver classes so pipeline implementations
focus purely on extraction logic, not database operations.
"""

from .bank_statement_saver import BankStatementSaver
from .attribute_saver import AttributeSaver

__all__ = ["BankStatementSaver", "AttributeSaver"]
