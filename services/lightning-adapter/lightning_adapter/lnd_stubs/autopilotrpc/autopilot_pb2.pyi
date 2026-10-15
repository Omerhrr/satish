from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class StatusRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class StatusResponse(_message.Message):
    __slots__ = ("active",)
    ACTIVE_FIELD_NUMBER: _ClassVar[int]
    active: bool
    def __init__(self, active: _Optional[bool] = ...) -> None: ...

class ModifyStatusRequest(_message.Message):
    __slots__ = ("enable",)
    ENABLE_FIELD_NUMBER: _ClassVar[int]
    enable: bool
    def __init__(self, enable: _Optional[bool] = ...) -> None: ...

class ModifyStatusResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class QueryScoresRequest(_message.Message):
    __slots__ = ("pubkeys", "ignore_local_state")
    PUBKEYS_FIELD_NUMBER: _ClassVar[int]
    IGNORE_LOCAL_STATE_FIELD_NUMBER: _ClassVar[int]
    pubkeys: _containers.RepeatedScalarFieldContainer[str]
    ignore_local_state: bool
    def __init__(self, pubkeys: _Optional[_Iterable[str]] = ..., ignore_local_state: _Optional[bool] = ...) -> None: ...

class QueryScoresResponse(_message.Message):
    __slots__ = ("results",)
    class HeuristicResult(_message.Message):
        __slots__ = ("heuristic", "scores")
        class ScoresEntry(_message.Message):
            __slots__ = ("key", "value")
            KEY_FIELD_NUMBER: _ClassVar[int]
            VALUE_FIELD_NUMBER: _ClassVar[int]
            key: str
            value: float
            def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
        HEURISTIC_FIELD_NUMBER: _ClassVar[int]
        SCORES_FIELD_NUMBER: _ClassVar[int]
        heuristic: str
        scores: _containers.ScalarMap[str, float]
        def __init__(self, heuristic: _Optional[str] = ..., scores: _Optional[_Mapping[str, float]] = ...) -> None: ...
    RESULTS_FIELD_NUMBER: _ClassVar[int]
    results: _containers.RepeatedCompositeFieldContainer[QueryScoresResponse.HeuristicResult]
    def __init__(self, results: _Optional[_Iterable[_Union[QueryScoresResponse.HeuristicResult, _Mapping]]] = ...) -> None: ...

class SetScoresRequest(_message.Message):
    __slots__ = ("heuristic", "scores")
    class ScoresEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    HEURISTIC_FIELD_NUMBER: _ClassVar[int]
    SCORES_FIELD_NUMBER: _ClassVar[int]
    heuristic: str
    scores: _containers.ScalarMap[str, float]
    def __init__(self, heuristic: _Optional[str] = ..., scores: _Optional[_Mapping[str, float]] = ...) -> None: ...

class SetScoresResponse(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...
