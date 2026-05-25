"""Tiny calculator (sample-project demo target)."""


def add(a: float, b: float) -> float:
    return a + b


def subtract(a: float, b: float) -> float:
    return a - b


def multiply(a: float, b: float) -> float:
    return a * b


def divide(a: float, b: float) -> float:
    if b == 0:
        raise ZeroDivisionError("divide by zero")
    return a / b


def modulo(a: int, b: int) -> int:
    if b == 0:
        raise ZeroDivisionError("modulo by zero")
    return a % b


def power(base: float, exp: float) -> float:
    return base ** exp
