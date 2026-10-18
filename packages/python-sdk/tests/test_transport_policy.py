import pytest
from alxprgs_sso import SSOClient
from alxprgs_sso.exceptions import ConfigurationError


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://[::1]",
        "http://auth.example.test",
        "ftp://auth.example.test",
        "https://user:password@auth.example.test",  # pragma: allowlist secret -- synthetic rejected URL
        "https://auth.example.test/#fragment",
    ],
)
def test_default_transport_rejects_unsafe_url(url):
    with pytest.raises(ConfigurationError):
        SSOClient(url, "rp")


@pytest.mark.parametrize("url", ["http://localhost:8000", "http://127.0.0.1", "http://[::1]"])
def test_explicit_local_profile_allows_only_loopback(url):
    client = SSOClient(url, "rp", transport_profile="local")
    assert client.verify_ssl is True


@pytest.mark.parametrize("profile", ["strict", "local"])
def test_tls_verification_cannot_be_disabled(profile):
    with pytest.raises(ConfigurationError):
        SSOClient("https://auth.example.test", "rp", verify_ssl=False, transport_profile=profile)
    with pytest.raises(ConfigurationError):
        SSOClient("http://auth.example.test", "rp", transport_profile=profile)
