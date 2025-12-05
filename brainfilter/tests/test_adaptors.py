# stdlib
from typing import List, Mapping, Tuple, Dict, Set, Sequence, TypedDict
from collections import abc
from fractions import Fraction
from numbers import Complex, Number, Integral, Real, Rational

# externals
import pytest

# internals
from brainfilter.adaptors import (
    Adaptor, get_adaptor, register_adaptor, ADAPTORS,
    AnyAdaptor, ObjectAdaptor, IntAdaptor, FloatAdaptor, FractionAdaptor,
    StrAdaptor, BoolAdaptor, ComplexAdaptor, ListAdaptor, TupleAdaptor,
    DictAdaptor, SetAdaptor, TypedDictAdaptor, NumpyArrayAdaptor,
    DataFrameAdaptor, SeriesAdaptor
)

# optionals
try:
    import numpy as np
except ImportError:
    np = None

try:
    import pandas as pd
except ImportError:
    pd = None


class TestEdgeCases:
    def test_adaptor_with_none_value(self):
        adaptor = AnyAdaptor()
        assert adaptor(None) is None

    def test_int_adaptor_invalid_string(self):
        adaptor = IntAdaptor(int)
        with pytest.raises(ValueError):
            adaptor("not_a_number")

    def test_float_adaptor_invalid_string(self):
        adaptor = FloatAdaptor(float)
        with pytest.raises(ValueError):
            adaptor("not_a_float")

    def test_fraction_adaptor_invalid_string(self):
        adaptor = FractionAdaptor(Fraction)
        with pytest.raises(ValueError):
            adaptor("not_a_fraction")

    def test_complex_adaptor_invalid_string(self):
        adaptor = ComplexAdaptor(complex)
        with pytest.raises(ValueError):
            adaptor("not_a_complex")

    def test_bool_adaptor_type_error(self):
        adaptor = BoolAdaptor(bool)
        # bool() accepts most types, but we test the adaptor works
        assert adaptor([]) is False
        assert adaptor([1]) is True

    def test_list_adaptor_invalid_item_type(self):
        adaptor = ListAdaptor(List[int])
        with pytest.raises(ValueError):
            adaptor(["1", "invalid", "3"])

    def test_tuple_adaptor_invalid_item_type(self):
        adaptor = TupleAdaptor(Tuple[int, str, float])
        with pytest.raises((ValueError, TypeError)):
            adaptor([1, "test", "not_a_float"])

    def test_dict_adaptor_invalid_key_type(self):
        adaptor = DictAdaptor(Dict[int, str])
        with pytest.raises(ValueError):
            adaptor({"invalid": "value"})

    def test_dict_adaptor_invalid_value_type(self):
        adaptor = DictAdaptor(Dict[str, int])
        with pytest.raises(ValueError):
            adaptor({"key": "not_an_int"})

    def test_set_adaptor_invalid_item_type(self):
        adaptor = SetAdaptor(Set[int])
        with pytest.raises(ValueError):
            adaptor(["1", "invalid", "3"])

    def test_int_adaptor_type_object(self):
        adaptor = IntAdaptor(int)
        with pytest.raises(TypeError):
            adaptor(int)

    def test_list_adaptor_not_iterable(self):
        adaptor = ListAdaptor(list)
        with pytest.raises(TypeError):
            adaptor(42)


class TestAdaptorRegistration:
    def test_register_adaptor(self):
        foo = type("Foo", (), {})

        @register_adaptor(foo)
        class FooAdaptor(Adaptor):
            foo

        assert foo in ADAPTORS
        assert ADAPTORS[foo] is FooAdaptor

    def test_get_adaptor_direct(self):
        assert get_adaptor(int) is IntAdaptor
        assert get_adaptor(float) is FloatAdaptor
        assert get_adaptor(str) is StrAdaptor

    def test_get_adaptor_abstract(self):
        assert get_adaptor(Integral) is IntAdaptor
        assert get_adaptor(Real) is FloatAdaptor
        assert get_adaptor(Number) is FloatAdaptor

    def test_get_adaptor_not_found(self):
        # All types are at least instances of object, so the
        # ObjectAdaptor should be returned.
        bar = type("Bar", (), {})
        assert get_adaptor(bar) is ObjectAdaptor


class TestAnyAdaptor:
    def test_adaptor_creation(self):
        adaptor = AnyAdaptor()
        assert isinstance(adaptor, AnyAdaptor)

    def test_passthrough(self):
        adaptor = AnyAdaptor()
        assert adaptor(42) == 42
        assert adaptor("test") == "test"
        assert adaptor([1, 2, 3]) == [1, 2, 3]


class TestIntAdaptor:
    def test_int_adaptor(self):
        adaptor = IntAdaptor(int)
        assert adaptor(42) == 42
        assert adaptor(42.0) == 42
        assert adaptor("42") == 42

    def test_integral_hint(self):
        adaptor = IntAdaptor(Integral)
        assert adaptor(42) == 42

    def test_invalid_hint(self):
        with pytest.raises(TypeError):
            IntAdaptor(str)


class TestFloatAdaptor:
    def test_float_adaptor(self):
        adaptor = FloatAdaptor(float)
        assert adaptor(42.0) == 42.0
        assert adaptor(42) == 42.0
        assert adaptor("42.5") == 42.5

    def test_real_hint(self):
        adaptor = FloatAdaptor(Real)
        assert adaptor(42) == 42.0

    def test_invalid_hint(self):
        with pytest.raises(TypeError):
            FloatAdaptor(str)


class TestFractionAdaptor:
    def test_fraction_adaptor(self):
        adaptor = FractionAdaptor(Fraction)
        assert adaptor(Fraction(1, 2)) == Fraction(1, 2)
        assert adaptor(0.5) == Fraction(1, 2)

    def test_rational_hint(self):
        adaptor = FractionAdaptor(Rational)
        result = adaptor(Fraction(1, 3))
        assert result == Fraction(1, 3)


class TestStrAdaptor:
    def test_str_adaptor(self):
        adaptor = StrAdaptor(str)
        assert adaptor("test") == "test"
        assert adaptor(42) == "42"

    def test_invalid_hint(self):
        with pytest.raises(TypeError):
            StrAdaptor(int)


class TestBoolAdaptor:
    def test_bool_adaptor(self):
        adaptor = BoolAdaptor(bool)
        assert adaptor(True) is True
        assert adaptor(False) is False
        assert adaptor(1) is True
        assert adaptor(0) is False


class TestComplexAdaptor:
    def test_complex_adaptor(self):
        adaptor = ComplexAdaptor(complex)
        assert adaptor(1+2j) == 1+2j
        assert adaptor(1) == 1+0j
        assert adaptor("1+2j") == 1+2j

    def test_complex_hint(self):
        adaptor = ComplexAdaptor(Complex)
        assert adaptor(1+2j) == 1+2j


class TestListAdaptor:
    def test_list_adaptor(self):
        adaptor = ListAdaptor(list)
        assert adaptor([1, 2, 3]) == [1, 2, 3]
        assert adaptor((1, 2, 3)) == [1, 2, 3]

    def test_list_with_item_hint(self):
        adaptor = ListAdaptor(List[int])
        assert adaptor([1, 2, 3]) == [1, 2, 3]
        assert adaptor(["1", "2", "3"]) == [1, 2, 3]

    def test_sequence_hint(self):
        adaptor = ListAdaptor(Sequence)
        assert adaptor([1, 2, 3]) == [1, 2, 3]

    def test_abc_iterable(self):
        adaptor = ListAdaptor(abc.Iterable)
        result = adaptor((x for x in [1, 2, 3]))
        assert list(result) == [1, 2, 3]

    def test_invalid_hint(self):
        with pytest.raises(TypeError):
            ListAdaptor(int)


class TestTupleAdaptor:
    def test_tuple_adaptor(self):
        adaptor = TupleAdaptor(tuple)
        assert adaptor((1, 2, 3)) == (1, 2, 3)
        assert adaptor([1, 2, 3]) == (1, 2, 3)

    def test_tuple_fixed_length(self):
        adaptor = TupleAdaptor(Tuple[int, str, float])
        result = adaptor([1, "test", 3.14])
        assert result == (1, "test", 3.14)
        assert isinstance(result[1], str)

    def test_tuple_variable_length(self):
        adaptor = TupleAdaptor(Tuple[int, ...])
        result = adaptor(["1", "2", "3"])
        assert result == (1, 2, 3)

    def test_tuple_length_mismatch(self):
        adaptor = TupleAdaptor(Tuple[int, str])
        with pytest.raises(TypeError):
            adaptor([1, 2, 3])

    def test_invalid_hint(self):
        with pytest.raises(TypeError):
            TupleAdaptor(list)


class TestDictAdaptor:
    def test_dict_adaptor(self):
        adaptor = DictAdaptor(dict)
        assert adaptor({"a": 1}) == {"a": 1}

    def test_dict_with_hints(self):
        adaptor = DictAdaptor(Dict[str, int])
        result = adaptor({"a": "1", "b": "2"})
        assert result == {"a": 1, "b": 2}

    def test_mapping_hint(self):
        adaptor = DictAdaptor(Mapping)
        assert adaptor({"a": 1}) == {"a": 1}

    def test_abc_mapping(self):
        adaptor = DictAdaptor(abc.Mapping)
        assert adaptor({"a": 1}) == {"a": 1}

    def test_invalid_hint(self):
        with pytest.raises(TypeError):
            DictAdaptor(list)


class TestSetAdaptor:
    def test_set_adaptor(self):
        adaptor = SetAdaptor(set)
        assert adaptor({1, 2, 3}) == {1, 2, 3}
        assert adaptor([1, 2, 2, 3]) == {1, 2, 3}

    def test_set_with_item_hint(self):
        adaptor = SetAdaptor(Set[int])
        result = adaptor(["1", "2", "3"])
        assert result == {1, 2, 3}

    def test_invalid_hint(self):
        with pytest.raises(TypeError):
            SetAdaptor(int)


class TestAdaptorFactory:
    def test_adaptor_factory_int(self):
        adaptor = Adaptor(int)
        assert isinstance(adaptor, IntAdaptor)

    def test_adaptor_factory_list(self):
        adaptor = Adaptor(List[int])
        assert isinstance(adaptor, ListAdaptor)

    def test_adaptor_factory_dict(self):
        adaptor = Adaptor(Dict[str, int])
        assert isinstance(adaptor, DictAdaptor)

    def test_adaptor_repr(self):
        adaptor = IntAdaptor(int)
        assert "IntAdaptor" in repr(adaptor)

    def test_adaptor_str(self):
        adaptor = IntAdaptor(int)
        assert "IntAdaptor" in str(adaptor)


class TestTypedDictAdaptor:
    def test_typeddict_adaptor(self):

        class Person(TypedDict):
            name: str
            age: int

        adaptor = TypedDictAdaptor(Person)
        result = adaptor({"name": "Alice", "age": "30"})
        assert result == {"name": "Alice", "age": 30}
        assert isinstance(result, dict)

    def test_typeddict_unexpected_key(self):

        class Person(TypedDict):
            name: str
            age: int

        adaptor = TypedDictAdaptor(Person)
        with pytest.raises(KeyError):
            adaptor({"name": "Alice", "age": 30, "extra": "field"})

    def test_typeddict_missing_key(self):

        class Person(TypedDict):
            name: str
            age: int

        adaptor = TypedDictAdaptor(Person)
        with pytest.raises(KeyError):
            adaptor({"name": "Alice"})


class TestNumpyArrayAdaptor:
    @pytest.mark.skipif(not np, reason="numpy not available")
    def test_numpy_array_adaptor(self):

        adaptor = NumpyArrayAdaptor(np.ndarray)
        result = adaptor([1, 2, 3])
        assert isinstance(result, np.ndarray)
        assert np.array_equal(result, np.array([1, 2, 3]))

    @pytest.mark.skipif(not np, reason="numpy not available")
    def test_numpy_array_from_list(self):

        adaptor = NumpyArrayAdaptor(np.ndarray)
        result = adaptor([[1, 2], [3, 4]])
        assert isinstance(result, np.ndarray)
        assert result.shape == (2, 2)

    @pytest.mark.skipif(not np, reason="numpy not available")
    def test_numpy_array_already_array(self):

        adaptor = NumpyArrayAdaptor(np.ndarray)
        arr = np.array([1, 2, 3])
        result = adaptor(arr)
        assert isinstance(result, np.ndarray)
        assert np.array_equal(result, arr)


class TestPandasDataFrameAdaptor:
    @pytest.mark.skipif(not pd, reason="pandas not available")
    def test_dataframe_adaptor(self):

        adaptor = DataFrameAdaptor(pd.DataFrame)
        result = adaptor({"a": [1, 2], "b": [3, 4]})
        assert isinstance(result, pd.DataFrame)
        assert list(result.columns) == ["a", "b"]

    @pytest.mark.skipif(not pd, reason="pandas not available")
    def test_dataframe_already_dataframe(self):

        adaptor = DataFrameAdaptor(pd.DataFrame)
        df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
        result = adaptor(df)
        assert isinstance(result, pd.DataFrame)
        assert result.equals(df)


class TestPandasSeriesAdaptor:
    @pytest.mark.skipif(not pd, reason="pandas not available")
    def test_series_adaptor(self):

        adaptor = SeriesAdaptor(pd.Series)
        result = adaptor([1, 2, 3])
        assert isinstance(result, pd.Series)
        assert list(result) == [1, 2, 3]

    @pytest.mark.skipif(not pd, reason="pandas not available")
    def test_series_already_series(self):

        adaptor = SeriesAdaptor(pd.Series)
        series = pd.Series([1, 2, 3])
        result = adaptor(series)
        assert isinstance(result, pd.Series)
        assert result.equals(series)
