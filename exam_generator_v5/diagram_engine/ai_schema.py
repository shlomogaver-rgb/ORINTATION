"""Native structured output for PASS 2 (diagram recognition).

The model returns a TYPED object whose schema is derived automatically from DiagramSpec, made Gemini-safe:
dict[str, X] fields become lists of {key, value}; engine-owned fields (evidence, symbols, versions, hashes) are
excluded; Any is never exposed. `to_spec()` maps the typed answer back to DiagramSpec - no JSON string is parsed."""
from __future__ import annotations

import typing
from functools import lru_cache
from typing import Any, Union

from pydantic import BaseModel, ConfigDict, Field, create_model

from .schemas import DiagramSpec

EXCLUDED = {"evidence", "symbols", "source_image_hash", "parser_version", "schema_version", "warnings"}


class _AI(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _kv_model(value_type: Any) -> type[BaseModel]:
    name = f"KV_{getattr(value_type, '__name__', 'val')}"
    return create_model(name, __base__=_AI, key=(str, ...), value=(value_type, ...))


def _convert(tp: Any) -> Any:
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return ai_model(tp)
    if origin in (list, typing.List):
        return list[_convert(args[0])] if args else list[str]
    if origin in (dict, typing.Dict):
        return list[_kv_model(_convert(args[1]))]
    if origin in (Union, getattr(__import__("types"), "UnionType", Union)):
        conv = tuple(_convert(a) for a in args)
        return Union[conv] if len(conv) > 1 else conv[0]
    if tp is Any:
        return str
    return tp


@lru_cache(maxsize=None)
def ai_model(model: type[BaseModel]) -> type[BaseModel]:
    fields = {}
    for name, f in model.model_fields.items():
        if model is DiagramSpec and name in EXCLUDED:
            continue
        default = f.default if not f.is_required() else ...
        if f.default_factory is not None:
            fields[name] = (_convert(f.annotation), Field(default_factory=f.default_factory))
        else:
            fields[name] = (_convert(f.annotation), default)
    return create_model(f"AI{model.__name__}", __base__=_AI, **fields)


AIDiagramSpec = ai_model(DiagramSpec)


def _back(value: Any, tp: Any) -> Any:
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if value is None:
        return None
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return {k: _back(v, tp.model_fields[k].annotation) for k, v in value.items() if k in tp.model_fields}
    if origin in (dict, typing.Dict):
        return {kv["key"]: _back(kv["value"], args[1]) for kv in value}
    if origin in (list, typing.List) and args:
        return [_back(v, args[0]) for v in value]
    if origin in (Union, getattr(__import__("types"), "UnionType", Union)):
        for a in args:
            if a is type(None):
                continue
            if isinstance(a, type) and issubclass(a, BaseModel) and isinstance(value, dict):
                return _back(value, a)
            if typing.get_origin(a) in (dict, list) and isinstance(value, list):
                return _back(value, a)
        return value
    return value


def to_spec(ai: BaseModel | dict) -> DiagramSpec:
    data = ai.model_dump() if isinstance(ai, BaseModel) else ai
    return DiagramSpec.model_validate(_back(data, DiagramSpec))


def to_ai_dict(spec: DiagramSpec) -> dict:
    """Inverse mapping (tests / mocks): DiagramSpec -> the AI-schema shape."""
    def fwd(value: Any, tp: Any) -> Any:
        origin, args = typing.get_origin(tp), typing.get_args(tp)
        if value is None:
            return None
        if isinstance(tp, type) and issubclass(tp, BaseModel):
            return {k: fwd(getattr(value, k), f.annotation) for k, f in tp.model_fields.items()
                    if not (tp is DiagramSpec and k in EXCLUDED)}
        if origin in (dict, typing.Dict):
            return [{"key": k, "value": fwd(v, args[1])} for k, v in value.items()]
        if origin in (list, typing.List) and args:
            return [fwd(v, args[0]) for v in value]
        if origin in (Union, getattr(__import__("types"), "UnionType", Union)):
            for a in args:
                if a is not type(None) and ((isinstance(a, type) and issubclass(a, BaseModel) and isinstance(value, BaseModel))
                                            or typing.get_origin(a) in (dict, list)):
                    return fwd(value, a)
            return value
        return value
    return fwd(spec, DiagramSpec)


def schema_is_gemini_safe(schema: dict) -> list[str]:
    """Problems that Gemini's response_schema rejects: free-form objects (additionalProperties) and untyped values."""
    bad: list[str] = []

    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" not in node and "$ref" not in node:
                bad.append(path + ": free-form object")
            if node.get("additionalProperties") not in (None, False):
                bad.append(path + ": additionalProperties")
            for k, v in node.items():
                walk(v, f"{path}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
    walk(schema, "")
    return bad
