from datetime import UTC, datetime

import httpx
import pytest

from aic_backend.bootstrap.provider_builders import provider_builders
from aic_backend.infrastructure import InMemoryEventBus
from aic_backend.provider_runtime import (
    HealthCheckPolicy,
    ProviderFactory,
    ProviderHealthManager,
    ProviderLifecycleManager,
    ProviderRegistry,
    ProviderRequestContext,
    ProviderSelector,
    ProviderStatus,
    QualityScorer,
)
from aic_backend.provider_runtime.errors import (
    AuthenticationConfigurationError,
    InvalidRequestError,
    ProviderInvalidResponseError,
    ProviderRateLimitedError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    UserPermissionError,
)
from aic_backend.provider_runtime.models import (
    ProviderDefinition,
    ProviderInvocationRequest,
)
from aic_backend.provider_runtime.system import UtcClock
from aic_backend.providers.tushare import (
    TUSHARE_CALENDAR,
    TUSHARE_DAILY,
    TushareDailyProvider,
)


class FakeClient:
    def __init__(self, data: object) -> None:
        self.data = data
        self.body: object = None
        self.closed = False

    async def post(self, url: str, *, json: object, timeout: float) -> httpx.Response:
        del url, timeout
        self.body = json
        return httpx.Response(200, json=self.data, request=httpx.Request("POST", "https://x"))

    async def aclose(self) -> None:
        self.closed = True


class RaisingClient:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def post(self, url: str, *, json: object, timeout: float) -> httpx.Response:
        del url, json, timeout
        raise self.error


class InvalidJsonResponse(httpx.Response):
    def json(self, **kwargs: object) -> object:
        del kwargs
        raise ValueError("invalid json")


class FixedResponseClient:
    def __init__(self, response: httpx.Response) -> None:
        self.response = response

    async def post(self, url: str, *, json: object, timeout: float) -> httpx.Response:
        del url, json, timeout
        return self.response


class FixedIds:
    def new_id(self, prefix: str) -> str:
        return f"{prefix}_fixed"


def definition() -> ProviderDefinition:
    return ProviderDefinition(
        "tushare_pro",
        "providers.tushare_daily",
        True,
        100,
        frozenset({TUSHARE_DAILY}),
        {},
    )


def request() -> ProviderInvocationRequest:
    return ProviderInvocationRequest(
        "req-1",
        "tushare_pro",
        TUSHARE_DAILY,
        {"ts_code": "000001.SZ", "start_date": "20260102", "end_date": "20260102"},
        1000,
        datetime(2026, 1, 3, tzinfo=UTC),
    )


def test_factory_registration_is_explicit_and_capability_is_stable() -> None:
    provider = ProviderFactory(provider_builders()).create(definition())
    assert isinstance(provider, TushareDailyProvider)
    assert provider.metadata.provider_id == "tushare_pro"
    assert provider.capabilities == frozenset({TUSHARE_DAILY})


@pytest.mark.asyncio
async def test_lifecycle_health_and_selector_use_runtime_contracts() -> None:
    clock = UtcClock()
    registry = ProviderRegistry(clock)
    lifecycle = ProviderLifecycleManager(registry, InMemoryEventBus(), clock, FixedIds())
    provider = TushareDailyProvider(definition(), "secret", FakeClient({}))
    await lifecycle.register(provider)
    assert (await lifecycle.initialize("tushare_pro")).lifecycle_status is ProviderStatus.READY
    health = ProviderHealthManager(
        registry,
        lifecycle,
        clock,
        HealthCheckPolicy(timeout_ms=100, failure_threshold=2, recovery_threshold=1),
    )
    assert (await health.check_once("tushare_pro")).status.value == "healthy"
    selected = ProviderSelector(QualityScorer()).select(
        ProviderRequestContext("request_1", TUSHARE_DAILY, 1000),
        await registry.snapshot(),
        {},
        clock.now(),
    )
    assert selected.selected_provider_id == "tushare_pro"


@pytest.mark.asyncio
async def test_missing_token_is_safe() -> None:
    with pytest.raises(AuthenticationConfigurationError):
        await TushareDailyProvider(definition(), None, FakeClient({})).initialize()


@pytest.mark.asyncio
async def test_fixture_response_is_returned_without_token_leak() -> None:
    client = FakeClient(
        {
            "code": 0,
            "data": {"fields": ["ts_code", "trade_date"], "items": [["000001.SZ", "20260102"]]},
        }
    )
    provider = TushareDailyProvider(definition(), "secret-token", client)
    await provider.initialize()
    response = await provider.invoke(request())
    assert response.payload["rows"] == [{"ts_code": "000001.SZ", "trade_date": "20260102"}]
    assert "secret-token" not in repr(response)


@pytest.mark.asyncio
async def test_rate_limit_is_mapped() -> None:
    provider = TushareDailyProvider(
        definition(), "secret", FakeClient({"code": -1, "msg": "超过接口频率"})
    )
    await provider.initialize()
    with pytest.raises(ProviderRateLimitedError):
        await provider.invoke(request())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("message", "error_type"),
    [
        ("权限不足", UserPermissionError),
        ("invalid token", AuthenticationConfigurationError),
    ],
)
async def test_remote_errors_are_safely_mapped(message: str, error_type: type[Exception]) -> None:
    provider = TushareDailyProvider(
        definition(), "secret", FakeClient({"code": -1, "msg": message})
    )
    await provider.initialize()
    with pytest.raises(error_type) as captured:
        await provider.invoke(request())
    assert "secret" not in str(captured.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "error_type"),
    [
        (httpx.ReadTimeout("slow"), ProviderTimeoutError),
        (httpx.ConnectError("offline"), ProviderUnavailableError),
    ],
)
async def test_transport_errors_are_stable(error: Exception, error_type: type[Exception]) -> None:
    provider = TushareDailyProvider(definition(), "secret", RaisingClient(error))
    await provider.initialize()
    with pytest.raises(error_type):
        await provider.invoke(request())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        [],
        {"code": 0},
        {"code": 0, "data": {"fields": "bad", "items": []}},
        {"code": 0, "data": {"fields": ["a"], "items": [[1, 2]]}},
    ],
)
async def test_malformed_response_is_rejected(response: object) -> None:
    provider = TushareDailyProvider(definition(), "secret", FakeClient(response))
    await provider.initialize()
    with pytest.raises(ProviderInvalidResponseError):
        await provider.invoke(request())


@pytest.mark.asyncio
async def test_empty_response_is_distinct_and_request_requires_scope() -> None:
    provider = TushareDailyProvider(
        definition(), "secret", FakeClient({"code": 0, "data": {"fields": [], "items": []}})
    )
    await provider.initialize()
    assert (await provider.invoke(request())).payload == {"rows": []}
    invalid = ProviderInvocationRequest(
        "req-2",
        "tushare_pro",
        TUSHARE_DAILY,
        {},
        1000,
        datetime(2026, 1, 3, tzinfo=UTC),
    )
    with pytest.raises(InvalidRequestError):
        await provider.invoke(invalid)


def test_canonical_historical_parameters_are_translated_at_adapter_boundary() -> None:
    assert TushareDailyProvider._parameters(
        {
            "symbol": "600000",
            "market": "CN.SSE",
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
        }
    ) == {
        "ts_code": "600000.SH",
        "start_date": "20260101",
        "end_date": "20260131",
    }
    assert (
        TushareDailyProvider._parameters(
            {"symbol": "000001", "market": "CN.SZSE", "trade_date": "2026-01-02"}
        )["ts_code"]
        == "000001.SZ"
    )
    with pytest.raises(InvalidRequestError):
        TushareDailyProvider._parameters({"symbol": "1", "market": "CN.BJSE"})


@pytest.mark.asyncio
async def test_health_shutdown_float_conversion_and_invalid_json() -> None:
    client = FakeClient(
        {
            "code": 0,
            "data": {"fields": ["close"], "items": [[10.2]]},
        }
    )
    provider = TushareDailyProvider(definition(), "secret", client)
    assert (await provider.health_check()).status.value == "unhealthy"
    await provider.initialize()
    assert (await provider.health_check()).status.value == "healthy"
    assert (await provider.invoke(request())).payload["rows"] == [{"close": "10.2"}]
    await provider.shutdown()

    invalid = InvalidJsonResponse(200, request=httpx.Request("POST", "https://x"))
    broken = TushareDailyProvider(definition(), "secret", FixedResponseClient(invalid))
    await broken.initialize()
    with pytest.raises(ProviderInvalidResponseError):
        await broken.invoke(request())


@pytest.mark.asyncio
async def test_calendar_capability_is_separate_and_returns_calendar_rows() -> None:
    calendar_definition = ProviderDefinition(
        "tushare_pro",
        "providers.tushare_daily",
        True,
        100,
        frozenset({TUSHARE_DAILY, TUSHARE_CALENDAR}),
        {},
    )
    provider = TushareDailyProvider(
        calendar_definition,
        "secret",
        FakeClient(
            {
                "code": 0,
                "data": {
                    "fields": ["exchange", "cal_date", "is_open"],
                    "items": [["SSE", "20260817", "1"]],
                },
            }
        ),
    )
    await provider.initialize()
    response = await provider.invoke(
        ProviderInvocationRequest(
            "calendar-1",
            "tushare_pro",
            TUSHARE_CALENDAR,
            {"exchange": "SSE", "start_date": "2026-08-17", "end_date": "2026-08-17"},
            1000,
            datetime(2026, 8, 17, tzinfo=UTC),
        )
    )
    assert response.payload["rows"] == [{"exchange": "SSE", "cal_date": "20260817", "is_open": "1"}]
    assert TushareDailyProvider._calendar_parameters(
        {"exchange": "SZSE", "start_date": "2026-08-01", "end_date": "2026-08-31"}
    ) == {"exchange": "SZSE", "start_date": "20260801", "end_date": "20260831"}
