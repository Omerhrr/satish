from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ConfRequest(_message.Message):
    __slots__ = ("txid", "script", "num_confs", "height_hint", "include_block")
    TXID_FIELD_NUMBER: _ClassVar[int]
    SCRIPT_FIELD_NUMBER: _ClassVar[int]
    NUM_CONFS_FIELD_NUMBER: _ClassVar[int]
    HEIGHT_HINT_FIELD_NUMBER: _ClassVar[int]
    INCLUDE_BLOCK_FIELD_NUMBER: _ClassVar[int]
    txid: bytes
    script: bytes
    num_confs: int
    height_hint: int
    include_block: bool
    def __init__(self, txid: _Optional[bytes] = ..., script: _Optional[bytes] = ..., num_confs: _Optional[int] = ..., height_hint: _Optional[int] = ..., include_block: _Optional[bool] = ...) -> None: ...

class ConfDetails(_message.Message):
    __slots__ = ("raw_tx", "block_hash", "block_height", "tx_index", "raw_block")
    RAW_TX_FIELD_NUMBER: _ClassVar[int]
    BLOCK_HASH_FIELD_NUMBER: _ClassVar[int]
    BLOCK_HEIGHT_FIELD_NUMBER: _ClassVar[int]
    TX_INDEX_FIELD_NUMBER: _ClassVar[int]
    RAW_BLOCK_FIELD_NUMBER: _ClassVar[int]
    raw_tx: bytes
    block_hash: bytes
    block_height: int
    tx_index: int
    raw_block: bytes
    def __init__(self, raw_tx: _Optional[bytes] = ..., block_hash: _Optional[bytes] = ..., block_height: _Optional[int] = ..., tx_index: _Optional[int] = ..., raw_block: _Optional[bytes] = ...) -> None: ...

class Reorg(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ConfEvent(_message.Message):
    __slots__ = ("conf", "reorg")
    CONF_FIELD_NUMBER: _ClassVar[int]
    REORG_FIELD_NUMBER: _ClassVar[int]
    conf: ConfDetails
    reorg: Reorg
    def __init__(self, conf: _Optional[_Union[ConfDetails, _Mapping]] = ..., reorg: _Optional[_Union[Reorg, _Mapping]] = ...) -> None: ...

class Outpoint(_message.Message):
    __slots__ = ("hash", "index")
    HASH_FIELD_NUMBER: _ClassVar[int]
    INDEX_FIELD_NUMBER: _ClassVar[int]
    hash: bytes
    index: int
    def __init__(self, hash: _Optional[bytes] = ..., index: _Optional[int] = ...) -> None: ...

class SpendRequest(_message.Message):
    __slots__ = ("outpoint", "script", "height_hint")
    OUTPOINT_FIELD_NUMBER: _ClassVar[int]
    SCRIPT_FIELD_NUMBER: _ClassVar[int]
    HEIGHT_HINT_FIELD_NUMBER: _ClassVar[int]
    outpoint: Outpoint
    script: bytes
    height_hint: int
    def __init__(self, outpoint: _Optional[_Union[Outpoint, _Mapping]] = ..., script: _Optional[bytes] = ..., height_hint: _Optional[int] = ...) -> None: ...

class SpendDetails(_message.Message):
    __slots__ = ("spending_outpoint", "raw_spending_tx", "spending_tx_hash", "spending_input_index", "spending_height")
    SPENDING_OUTPOINT_FIELD_NUMBER: _ClassVar[int]
    RAW_SPENDING_TX_FIELD_NUMBER: _ClassVar[int]
    SPENDING_TX_HASH_FIELD_NUMBER: _ClassVar[int]
    SPENDING_INPUT_INDEX_FIELD_NUMBER: _ClassVar[int]
    SPENDING_HEIGHT_FIELD_NUMBER: _ClassVar[int]
    spending_outpoint: Outpoint
    raw_spending_tx: bytes
    spending_tx_hash: bytes
    spending_input_index: int
    spending_height: int
    def __init__(self, spending_outpoint: _Optional[_Union[Outpoint, _Mapping]] = ..., raw_spending_tx: _Optional[bytes] = ..., spending_tx_hash: _Optional[bytes] = ..., spending_input_index: _Optional[int] = ..., spending_height: _Optional[int] = ...) -> None: ...

class SpendEvent(_message.Message):
    __slots__ = ("spend", "reorg")
    SPEND_FIELD_NUMBER: _ClassVar[int]
    REORG_FIELD_NUMBER: _ClassVar[int]
    spend: SpendDetails
    reorg: Reorg
    def __init__(self, spend: _Optional[_Union[SpendDetails, _Mapping]] = ..., reorg: _Optional[_Union[Reorg, _Mapping]] = ...) -> None: ...

class BlockEpoch(_message.Message):
    __slots__ = ("hash", "height")
    HASH_FIELD_NUMBER: _ClassVar[int]
    HEIGHT_FIELD_NUMBER: _ClassVar[int]
    hash: bytes
    height: int
    def __init__(self, hash: _Optional[bytes] = ..., height: _Optional[int] = ...) -> None: ...
