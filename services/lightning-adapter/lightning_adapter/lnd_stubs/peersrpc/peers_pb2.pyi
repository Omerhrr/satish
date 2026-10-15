import lightning_pb2 as _lightning_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class UpdateAction(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    ADD: _ClassVar[UpdateAction]
    REMOVE: _ClassVar[UpdateAction]

class FeatureSet(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    SET_INIT: _ClassVar[FeatureSet]
    SET_LEGACY_GLOBAL: _ClassVar[FeatureSet]
    SET_NODE_ANN: _ClassVar[FeatureSet]
    SET_INVOICE: _ClassVar[FeatureSet]
    SET_INVOICE_AMP: _ClassVar[FeatureSet]
ADD: UpdateAction
REMOVE: UpdateAction
SET_INIT: FeatureSet
SET_LEGACY_GLOBAL: FeatureSet
SET_NODE_ANN: FeatureSet
SET_INVOICE: FeatureSet
SET_INVOICE_AMP: FeatureSet

class UpdateAddressAction(_message.Message):
    __slots__ = ("action", "address")
    ACTION_FIELD_NUMBER: _ClassVar[int]
    ADDRESS_FIELD_NUMBER: _ClassVar[int]
    action: UpdateAction
    address: str
    def __init__(self, action: _Optional[_Union[UpdateAction, str]] = ..., address: _Optional[str] = ...) -> None: ...

class UpdateFeatureAction(_message.Message):
    __slots__ = ("action", "feature_bit")
    ACTION_FIELD_NUMBER: _ClassVar[int]
    FEATURE_BIT_FIELD_NUMBER: _ClassVar[int]
    action: UpdateAction
    feature_bit: _lightning_pb2.FeatureBit
    def __init__(self, action: _Optional[_Union[UpdateAction, str]] = ..., feature_bit: _Optional[_Union[_lightning_pb2.FeatureBit, str]] = ...) -> None: ...

class NodeAnnouncementUpdateRequest(_message.Message):
    __slots__ = ("feature_updates", "color", "alias", "address_updates")
    FEATURE_UPDATES_FIELD_NUMBER: _ClassVar[int]
    COLOR_FIELD_NUMBER: _ClassVar[int]
    ALIAS_FIELD_NUMBER: _ClassVar[int]
    ADDRESS_UPDATES_FIELD_NUMBER: _ClassVar[int]
    feature_updates: _containers.RepeatedCompositeFieldContainer[UpdateFeatureAction]
    color: str
    alias: str
    address_updates: _containers.RepeatedCompositeFieldContainer[UpdateAddressAction]
    def __init__(self, feature_updates: _Optional[_Iterable[_Union[UpdateFeatureAction, _Mapping]]] = ..., color: _Optional[str] = ..., alias: _Optional[str] = ..., address_updates: _Optional[_Iterable[_Union[UpdateAddressAction, _Mapping]]] = ...) -> None: ...

class NodeAnnouncementUpdateResponse(_message.Message):
    __slots__ = ("ops",)
    OPS_FIELD_NUMBER: _ClassVar[int]
    ops: _containers.RepeatedCompositeFieldContainer[_lightning_pb2.Op]
    def __init__(self, ops: _Optional[_Iterable[_Union[_lightning_pb2.Op, _Mapping]]] = ...) -> None: ...
