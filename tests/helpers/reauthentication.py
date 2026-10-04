"""Explicit sensitive API requests complete password/MFA proof, with no bypass."""

import json

from app.services.reauthentication_service import payload_digest


async def authorized_request(
    client, method, path, *, password, headers, json_body=None, factor=None
):
    encoded = b"" if json_body is None else json.dumps(json_body).encode()
    proof = await client.post(
        "/api/v1/auth/reauthentication",
        headers=headers,
        json={
            "current_password": password,
            "action": f"{method.upper()} {path}",
            "payload_hash": payload_digest(encoded),
        },
    )
    assert proof.status_code == 200, proof.json()
    data = proof.json()
    if data["factor_required"]:
        assert factor is not None, "An actual required second factor must be supplied"
        if callable(factor):
            factor = factor(data)
        payload = {"authorization": data["authorization"], **factor}
        proof = await client.post(
            "/api/v1/auth/reauthentication/factor", headers=headers, json=payload
        )
        assert proof.status_code == 200, proof.json()
        data = proof.json()
    kwargs = {"headers": {**headers, "X-Reauthentication": data["authorization"]}}
    if json_body is not None:
        kwargs["json"] = json_body
    return await client.request(method, path, **kwargs)
