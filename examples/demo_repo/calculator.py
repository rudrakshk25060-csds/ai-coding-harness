"""Demo repository - a simple calculator with a deliberate bug.

The calculate() function has a bug in the multiply operation.
The test_calculator.py file contains a test that catches this bug.
"""


def add(a, b):
    """Add two numbers."""
    return a + b


def subtract(a, b):
    """Subtract b from a."""
    return a - b


def multiply(a, b):
    """Multiply two numbers."""
    # BUG: This should be a * b, not a + b
    return a + b


def divide(a, b):
    """Divide a by b."""
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
