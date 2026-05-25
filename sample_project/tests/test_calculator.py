import pytest

from src.calculator import add, divide, modulo, multiply, power, subtract


def test_add():
    assert add(2, 3) == 5


def test_subtract():
    assert subtract(5, 2) == 3


def test_multiply():
    assert multiply(4, 3) == 12


def test_divide():
    assert divide(10, 2) == 5


def test_divide_by_zero():
    with pytest.raises(ZeroDivisionError):
        divide(1, 0)


def test_modulo():
    assert modulo(10, 3) == 1


def test_power():
    assert power(2, 10) == 1024
