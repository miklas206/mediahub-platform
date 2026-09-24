"""Serialized private rotation. Interrupted changes block automatic restart."""

import asyncio
import json
import uuid
from pathlib import Path

import httpx

from agent.install_files import save_json
from agent.ram_secrets import RuntimeSecrets
from agent.seedbox_provision import private_record


async def authenticated_client(base, credentials):
    client = httpx.AsyncClient(
        base_url=base, trust_env=False, timeout=5, headers={"Referer": base + "/"}
    )
    try:
        response = await client.post(
            "/api/v2/auth/login",
            data={
                "username": credentials.webUsername,
                "password": credentials.webPassword.get_secret_value(),
            },
        )
        if response.status_code not in {200, 204} or (
            response.status_code == 200 and response.text.strip() != "Ok."
        ):
            raise ValueError("Client authentication failed")
        return client
    except BaseException:
        await client.aclose()
        raise


async def rotate(control, store, credentials, kind):
    driver = control.driver
    policy, spec = driver.binding()
    root = Path(policy.workRoot)
    previous = store.load("seedbox-runtime")
    if kind == "client" and previous.webPassword == credentials.webPassword:
        raise ValueError("New client credential must differ")
    reference = "rotation-" + uuid.uuid4().hex
    store.stage(reference, credentials)
    path = root / "credential-rotation.json"
    save_json(path, {"state": "Applying", "kind": kind, "stagedReference": reference})
    control.lifecycle.state["desiredRunning"] = False
    control.lifecycle.persist()
    stage = "verify_current_runtime"
    try:
        await driver.storage_guard()
        await driver.device_guard()
        ip = await driver.verify_vpn()
        await driver.verify_torrent(ip)
        if kind == "vpn":
            await driver.stop_torrent()
            await driver.stop_vpn()
            store.replace("seedbox-runtime", private_record(credentials))
            RuntimeSecrets(root).materialize()
            await control.lifecycle.gated_start(restart_vpn=True)
        elif kind == "client":
            base = f"http://127.0.0.1:{spec.webPort}"
            stage = "authenticate_current_client"
            client = await authenticated_client(base, previous)
            try:
                stage = "apply_new_client_credential"
                response = await client.post(
                    "/api/v2/app/setPreferences",
                    data={
                        "json": json.dumps(
                            {
                                "web_ui_username": credentials.webUsername,
                                "web_ui_password": credentials.webPassword.get_secret_value(),
                            }
                        )
                    },
                )
                response.raise_for_status()
            finally:
                await client.aclose()
            stage = "verify_new_client_credential"
            client = await authenticated_client(base, credentials)
            await client.aclose()
            # Only a definite authentication rejection counts; network failure is not proof.
            stage = "verify_previous_credential_rejected"
            async with httpx.AsyncClient(
                base_url=base, trust_env=False, timeout=5, headers={"Referer": base + "/"}
            ) as probe:
                response = await probe.post(
                    "/api/v2/auth/login",
                    data={
                        "username": previous.webUsername,
                        "password": previous.webPassword.get_secret_value(),
                    },
                )
                if not (
                    response.status_code in {401, 403}
                    or (response.status_code == 200 and response.text.strip() == "Fails.")
                ):
                    raise ValueError("Previous credential rejection not verified")
            stage = "persist_verified_client_credential"
            store.replace("seedbox-runtime", private_record(credentials))
            RuntimeSecrets(root).materialize()
            await driver.verify_torrent(ip)
            if (await driver.forwarding.renew())["status"] != "healthy":
                raise ValueError("Forwarding not verified after rotation")
        else:
            raise ValueError("Unsupported rotation")
        save_json(
            path,
            {
                "state": "Healthy",
                "kind": kind,
                "stagedReference": reference,
                "previousCredentialRejected": kind == "client",
            },
        )
        control.lifecycle.state["desiredRunning"] = True
        control.lifecycle.persist()
    except (Exception, asyncio.CancelledError):
        control.lifecycle.state["desiredRunning"] = False
        control.lifecycle.persist()
        try:
            await driver.stop_torrent()
        finally:
            save_json(
                path,
                {
                    "state": "ManualIntervention",
                    "kind": kind,
                    "stagedReference": reference,
                    "failedStep": stage,
                },
            )
        raise
