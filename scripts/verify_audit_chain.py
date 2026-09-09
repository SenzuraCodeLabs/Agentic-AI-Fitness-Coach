"""Verify the audit hash chain from the command line.

Run without the service to check that no audit record has been altered:

    python scripts/verify_audit_chain.py
"""

from __future__ import annotations

import asyncio
import sys

from services.agent1_gatekeeper.pipeline.l8_envelope import verify_chain
from shared.db import close_client


async def main() -> int:
    result = await verify_chain()
    await close_client()

    if result["valid"]:
        print(f"chain OK: {result['records_checked']} records")
        print(f"head hash: {result['head_hash'][:32]}...")
        return 0

    print("CHAIN BROKEN")
    print(f"  reason: {result['reason']}")
    print(f"  at seq: {result.get('at_seq')}")
    print(f"  records checked before the break: {result['records_checked']}")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
