"""One-off diagnostic: does switch_electrical_power accept a per-endpoint target?

Not part of the integration; run manually, same credentials as enki_api_live.py.
Toggles electrical power on a single node's endpoints using a few candidate
payload shapes and prints the resulting check_electrical_power response after
each attempt, so you can compare against what you physically observe (which
light/zone actually reacted).

Usage:
    python tools/probe_endpoint_write.py --user EMAIL --password PASSWORD --node-id NODE_ID
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
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


async def _run(user: str, password: str, node_id: str) -> None:
    api_cls, const = _load_enki_api_class()
    api = api_cls(user, password)

    connected = await api.connect()
    if connected is not True:
        raise RuntimeError("Login failed")

    # Find the home_id owning this node by scanning all homes' devices.
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

    print(f"home_id={home_id} node_id={node_id}\n")

    async def get_endpoints() -> list[dict[str, Any]]:
        resp = await api.query_endpoint(home_id, node_id, const.ENKI_CHECK_ELECTRICAL_POWER)
        endpoints = resp.get("endpoints", [])
        return endpoints if isinstance(endpoints, list) else []

    async def show_state(label: str) -> list[dict[str, Any]]:
        endpoints = await get_endpoints()
        print(f"--- {label} ---")
        print(json.dumps(endpoints, indent=2))
        print()
        return endpoints

    def endpoint_power(endpoints: list[dict[str, Any]], target_id: Any) -> str | None:
        for e in endpoints:
            if isinstance(e, dict) and e.get("id") == target_id:
                lrv = e.get("lastReportedValue")
                if isinstance(lrv, str):
                    return lrv
                if isinstance(lrv, dict):
                    return lrv.get("power")
        return None

    endpoints = await show_state("BEFORE any change")
    if not endpoints:
        print("No 'endpoints' array in check_electrical_power response — nothing to target.")
        return

    endpoint_ids = [e.get("id") for e in endpoints if isinstance(e, dict) and e.get("id") is not None]
    print(f"Found endpoint ids: {endpoint_ids}\n")

    field_name_candidates = ["endpointId", "endpoint", "id", "endpoint_id"]

    for target_id in endpoint_ids:
        for field in field_name_candidates:
            current = endpoint_power(endpoints, target_id)
            new_value = "OFF" if current == "ON" else "ON"
            payload = {"value": new_value, field: target_id}
            print(f">>> POST switch_electrical_power {payload}  (endpoint {target_id} currently {current})")
            try:
                await api.query_endpoint(
                    home_id, node_id, const.ENKI_SWITCH_ELECTRICAL_POWER, payload
                )
            except Exception as exc:  # noqa: BLE001
                print(f"    -> request failed: {exc}\n")
                continue
            await asyncio.sleep(2)
            endpoints = await show_state(f"AFTER targeting endpoint {target_id} via '{field}' ({new_value})")
            input("Press Enter once you noted which physical light (if any) changed... ")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=os.getenv("ENKI_USER"))
    parser.add_argument("--password", default=os.getenv("ENKI_PASSWORD"))
    parser.add_argument("--node-id", required=True, help="nodeId of the device to probe")
    args = parser.parse_args()

    if not args.user or not args.password:
        print("Missing credentials.")
        return 2

    asyncio.run(_run(args.user, args.password, args.node_id))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
