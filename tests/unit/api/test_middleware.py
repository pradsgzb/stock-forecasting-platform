import asyncio

from stock_predictor.api.middleware import InMemoryRateLimitMiddleware


async def _ok_app(scope, receive, send) -> None:
    del scope, receive
    await send({"type": "http.response.start", "status": 204, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def _receive() -> dict[str, object]:
    return {"type": "http.request", "body": b"", "more_body": False}


async def _exercise_client(middleware: InMemoryRateLimitMiddleware, address: str) -> None:
    messages: list[dict[str, object]] = []

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    await middleware(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
            "client": (address, 1234),
        },
        _receive,
        send,
    )
    assert messages[0]["status"] == 204


def test_rate_limiter_bounds_client_tracking_state() -> None:
    middleware = InMemoryRateLimitMiddleware(
        _ok_app,
        requests=10,
        window_seconds=60,
        maximum_clients=2,
    )

    asyncio.run(_exercise_client(middleware, "192.0.2.1"))
    asyncio.run(_exercise_client(middleware, "192.0.2.2"))
    asyncio.run(_exercise_client(middleware, "192.0.2.3"))

    assert tuple(middleware._seen) == ("192.0.2.2", "192.0.2.3")


def test_rate_limiter_rejects_invalid_capacity() -> None:
    try:
        InMemoryRateLimitMiddleware(
            _ok_app,
            requests=1,
            window_seconds=60,
            maximum_clients=0,
        )
    except ValueError as exc:
        assert "positive" in str(exc)
    else:
        raise AssertionError("Expected invalid maximum client count to be rejected")
