"""One-off diagnostic: does switch_electrical_power accept a per-endpoint target?

Not part of the integration; run manually, same credentials as enki_api_live.py.
Toggles electrical power on a single node's endpoints, one field-name candidate
at a time, and asks you to type what you physically observed after each step.
Prints ONE compact summary table at the end -- that's the only thing you need
to copy/paste back.

Usage:
    python tools/probe_endpoint_write.py --user EMAIL --password PASSWORD --node-id NODE_ID
    python tools/probe_endpoint_write.py ... --field id   # try a different field name
    python tools/probe_endpoint_write.py ... --wait 5     # seconds between action and re-check
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import os
import sys
import types
from pathlib import Path
from typing import Any


def _load_enki_api_class():
    component_dir = Path(__file__).resolve().parents[1] / "custom_components" / "enki"
    package_name = "_enki_tools_runtime"

    if package_name not in sys.modules:
        package = types.ModuleType(package_name)
        package.__path__ = [str(component_dir)]
        sys.modules[package_name] = package

    const_module_name = f"{package_name}.const"
    if const_module_name not in sys.modules:
        const_spec = importlib.util.spec_from_file_location(
            const_module_name, component_dir / "const.py"
        )
        const_module = importlib.util.module_from_spec(const_spec)
        sys.modules[const_module_name] = const_module
        const_spec.loader.exec_module(const_module)

    api_module_name = f"{package_name}.api"
    api_spec = importlib.util.spec_from_file_location(
        api_module_name, component_dir / "api.py"
    )
    api_module = importlib.util.module_from_spec(api_spec)
    sys.modules[api_module_name] = api_module
    api_spec.loader.exec_module(api_module)

    return api_module.API, sys.modules[const_module_name]


def _fmt_endpoints(endpoints: list[dict[str, Any]]) -> str:
    parts = []
    for e in endpoints:
        if not isinstance(e, dict):
            continue
        lrv = e.get("lastReportedValue")
        power = lrv if isinstance(lrv, str) else (lrv.get("power") if isinstance(lrv, dict) else None)
        parts.append(f"{e.get('id')}={power}")
    return "[" + " ".join(parts) + "]"


async def _run(user: str, password: str, node_id: str, field: str, wait: float) -> None:
    api_cls, const = _load_enki_api_class()
    api = api_cls(user, password)

    if await api.connect() is not True:
        raise RuntimeError("Login failed")

    home_id = None
    for hid in await api.get_homes():
        for device in await api.get_items_in_section_for_home(hid):
            if device.get("nodeId") == node_id:
                home_id = hid
                break
        if home_id:
            break
    if not home_id:
        raise RuntimeError(f"Could not find home_id for node {node_id}")

    async def get_endpoints() -> list[dict[str, Any]]:
        resp = await api.query_endpoint(home_id, node_id, const.ENKI_CHECK_ELECTRICAL_POWER)
        endpoints = resp.get("endpoints", [])
        return endpoints if isinstance(endpoints, list) else []

    def power_of(endpoints: list[dict[str, Any]], target_id: Any) -> str | None:
        for e in endpoints:
            if isinstance(e, dict) and e.get("id") == target_id:
                lrv = e.get("lastReportedValue")
                return lrv if isinstance(lrv, str) else (lrv.get("power") if isinstance(lrv, dict) else None)
        return None

    endpoints = await get_endpoints()
    if not endpoints:
        print("No 'endpoints' array in check_electrical_power response -- nothing to target.")
        return

    endpoint_ids = [e.get("id") for e in endpoints if isinstance(e, dict) and e.get("id") is not None]
    print(f"field={field!r}  wait={wait}s  endpoint_ids={endpoint_ids}")
    print(f"BEFORE {_fmt_endpoints(endpoints)}\n")

    rows: list[str] = []
    for target_id in endpoint_ids:
        current = power_of(endpoints, target_id)
        new_value = "OFF" if current == "ON" else "ON"
        payload = {"value": new_value, field: target_id}

        before_str = _fmt_endpoints(endpoints)
        print(f">>> target={target_id} field={field} value={new_value}  (was {current})")
        try:
            await api.query_endpoint(home_id, node_id, const.ENKI_SWITCH_ELECTRICAL_POWER, payload)
        except Exception as exc:  # noqa: BLE001
            print(f"    request failed: {exc}\n")
            rows.append(f"target={target_id} field={field} -> REQUEST FAILED: {exc}")
            continue

        await asyncio.sleep(wait)
        endpoints = await get_endpoints()
        after_str = _fmt_endpoints(endpoints)
        print(f"    before={before_str} after={after_str}")

        observed = input("    What did you SEE physically change? [A/B/AB/FAN/NONE/other]: ").strip() or "?"
        rows.append(
            f"target={target_id} field={field} value={new_value} | before={before_str} after={after_str} | observed={observed}"
        )
        print()

    print("=" * 20 + " SUMMARY (copy from here) " + "=" * 20)
    print(f"node={node_id} field={field!r} wait={wait}s")
    for row in rows:
        print(row)
    print("=" * 67)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.getenv("ENKI_USER"))
    parser.add_argument("--password", default=os.getenv("ENKI_PASSWORD"))
    parser.add_argument("--node-id", required=True, help="nodeId of the device to probe")
    parser.add_argument(
        "--field",
        default="endpointId",
        choices=["endpointId", "endpoint", "id", "endpoint_id"],
        help="candidate field name to try in the switch_electrical_power payload (default: endpointId)",
    )
    parser.add_argument("--wait", type=float, default=4.0, help="seconds to wait before re-checking state (default: 4)")
    args = parser.parse_args()

    if not args.user or not args.password:
        print("Missing credentials.")
        return 2

    asyncio.run(_run(args.user, args.password, args.node_id, args.field, args.wait))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
