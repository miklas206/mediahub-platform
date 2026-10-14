"""Claim an owned Plex server using its existing protected RAM configuration."""

import asyncio
import contextlib

from mediahub.errors import DomainError

from agent.install_files import read_json


async def status(runtime):
    policy = runtime.control.policy()
    claimed = None
    try:
        identity = await runtime.control.plex_get(policy, "/identity")
        claimed = {"0": False, "1": True}.get(identity.get("claimed"))
    except DomainError:
        pass
    return {
        "installed": True,
        "claimed": claimed,
        "localUrl": policy.apiUrl,
        "operation": runtime.account_operation,
    }


async def queue(runtime, body):
    token = body.claimToken.get_secret_value()
    if not token.startswith("claim-") or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in token
    ):
        raise DomainError("plex_claim_invalid", "Get a fresh claim token from Plex", 422)
    if runtime.control.lock.locked() or any(
        task and not task.done()
        for task in (runtime.install_task, runtime.update_task, runtime.account_task)
    ):
        raise DomainError("operation_busy", "Another Plex operation is running", 409)
    policy = runtime.control.policy()
    await runtime.control.inspect(policy)
    if runtime.control.lock.locked() or any(
        task and not task.done()
        for task in (runtime.install_task, runtime.update_task, runtime.account_task)
    ):
        raise DomainError("operation_busy", "Another Plex operation is running", 409)
    runtime.account_operation = {"state": "running", "message": "Linking Plex to your account"}
    runtime.account_task = asyncio.create_task(run(runtime, body))
    return {"state": "accepted", "message": runtime.account_operation["message"]}


async def run(runtime, body):
    helper = None
    install_policy = None
    try:
        async with runtime.control.lock:
            policy = runtime.control.policy()
            current = await runtime.control.inspect(policy)
            if not current["State"].get("Running"):
                raise DomainError("plex_stopped", "Start Plex before linking your account", 409)
            identity = await runtime.control.plex_get(policy, "/identity")
            if identity.get("claimed") == "1":
                runtime.account_operation = {
                    "state": "succeeded",
                    "message": "Plex is linked to an account",
                }
                return
            if identity.get("claimed") != "0":
                raise DomainError(
                    "plex_claim_unknown", "Plex account status could not be verified", 409
                )
            if runtime.shared_vpn and not await runtime.shared_vpn.ready("plex", current):
                raise DomainError(
                    "vpn_relay_unverified", "VPN relay is unavailable; Plex start blocked", 409
                )
            if not await runtime.control.storage_verified(policy):
                raise DomainError(
                    "storage_unavailable", "Media storage is unavailable; Plex start blocked", 409
                )
            await runtime.stop(policy)
            install_policy = runtime.policy()
            helper = await runtime.helper(
                install_policy, read_json(runtime.state_dir / "plex-plan.json")
            )
            # Only the approved tmpfs config gets the short-lived secret. It is
            # absent from Docker environment/arguments, state receipts and logs.
            await runtime.archive_write(
                helper,
                {
                    "Library/Application Support/Plex Media Server/Preferences.xml": runtime.vault.get(
                        policy.installationId
                    ),
                    ".claim": body.claimToken.get_secret_value().encode(),
                },
                install_policy.uid,
                install_policy.gid,
            )
            vpn_port = await runtime.vpn.prepare(policy) if policy.vpnEnabled else None
            await runtime.request("POST", "/containers/" + policy.container + "/start")
            if policy.vpnEnabled:
                await runtime.vpn.activate(policy, vpn_port)
            for _ in range(45):
                try:
                    identity = await runtime.control.plex_get(policy, "/identity")
                    if identity.get("claimed") == "1":
                        await runtime.checkpoint(policy)
                        runtime.account_operation = {
                            "state": "succeeded",
                            "message": "Plex is linked to your account",
                        }
                        return
                except DomainError:
                    pass
                await asyncio.sleep(1)
            raise DomainError(
                "plex_claim_unverified",
                "Plex did not confirm account linking. Get a fresh claim token and retry.",
                409,
            )
    except DomainError as error:
        runtime.account_operation = {"state": "failed", "message": error.message}
    except Exception:
        runtime.account_operation = {
            "state": "failed",
            "message": "Plex account linking failed; media and configuration were preserved",
        }
    finally:
        if helper:
            with contextlib.suppress(DomainError):
                await runtime.archive_write(
                    helper, {".claim": b""}, install_policy.uid, install_policy.gid
                )
            await runtime.remove_helper(helper)
