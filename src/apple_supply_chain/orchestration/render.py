"""Render the ASL definition with concrete Lambda ARNs (LocalStack / manual deploys).

Terraform does the same substitution with ``templatefile()``; function names follow
``<prefix>-<placeholder without _arn, underscores as hyphens>``, e.g.
``asc-dev-extract-sec-edgar``.
"""

from __future__ import annotations

import json
import re

from apple_supply_chain.lambdas.handlers import FUNCTIONS
from apple_supply_chain.orchestration.local_sfn import load_definition


def function_name(placeholder: str, prefix: str) -> str:
    return f"{prefix}-{placeholder.removesuffix('_arn').replace('_', '-')}"


def render_definition(account_id: str, region: str, prefix: str) -> str:
    text = json.dumps(load_definition(), indent=2)

    def sub(m: re.Match) -> str:
        key = m.group(1)
        if key not in FUNCTIONS:
            raise KeyError(f"unknown placeholder {key}")
        return f"arn:aws:lambda:{region}:{account_id}:function:{function_name(key, prefix)}"

    return re.sub(r"\$\{(\w+)\}", sub, text)
