"""
Transforms a Pydantic-generated JSON schema into the subset OpenAI/Groq's
strict json_schema mode accepts. Two independent problems get fixed here:

1. Pydantic doesn't set additionalProperties:false on nested object schemas
   by default — strict mode requires it on EVERY object in the tree.
2. Pydantic represents `X | None` as anyOf: [{$ref: X}, {type: null}] —
   strict mode rejects this (a $ref branch can't be disambiguated from a
   null branch) and instead wants X's schema INLINED with "null" added to
   its own type/enum, collapsing the anyOf entirely.

Shared by any provider using OpenAI-compatible strict structured outputs
(Groq, Cerebras) so the fix lives in one place.
"""

import copy


def make_strict_schema(schema: dict) -> dict:
    schema = copy.deepcopy(schema)
    defs = schema.get("$defs", {})
    _collapse_nullable_refs(schema, defs)
    _enforce_strict_objects(schema)
    return schema


def _resolve_ref(ref: str, defs: dict) -> dict:
    # refs look like "#/$defs/DegreeLevel"
    name = ref.rsplit("/", 1)[-1]
    return defs[name]


def _collapse_nullable_refs(node, defs: dict):
    if isinstance(node, dict):
        if "anyOf" in node:
            branches = node["anyOf"]
            null_branches = [b for b in branches if b.get("type") == "null"]
            other_branches = [b for b in branches if b.get("type") != "null"]

            if null_branches and len(other_branches) == 1:
                target = other_branches[0]
                if "$ref" in target:
                    target = copy.deepcopy(_resolve_ref(target["$ref"], defs))
                else:
                    target = copy.deepcopy(target)

                # merge the resolved target's keys into this node in place,
                # replacing the anyOf entirely
                del node["anyOf"]
                node.update(target)

                existing_type = node.get("type")
                if isinstance(existing_type, list):
                    if "null" not in existing_type:
                        existing_type.append("null")
                elif isinstance(existing_type, str):
                    node["type"] = [existing_type, "null"]
                else:
                    node["type"] = "null"

                if "enum" in node and None not in node["enum"]:
                    node["enum"] = node["enum"] + [None]
            # else: multiple non-null branches (a true union) — not present
            # in this schema today; left as-is if it ever shows up.

        for value in node.values():
            _collapse_nullable_refs(value, defs)
    elif isinstance(node, list):
        for item in node:
            _collapse_nullable_refs(item, defs)


def _enforce_strict_objects(node):
    if isinstance(node, dict):
        if node.get("type") == "object" or (
            isinstance(node.get("type"), list) and "object" in node["type"]
        ):
            node["additionalProperties"] = False
            if "properties" in node:
                node["required"] = list(node["properties"].keys())
        for value in node.values():
            _enforce_strict_objects(value)
    elif isinstance(node, list):
        for item in node:
            _enforce_strict_objects(item)
