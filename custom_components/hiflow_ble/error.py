"""Errors for hiflow-ble."""

from homeassistant.exceptions import HomeAssistantError


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class PairingFailed(HomeAssistantError):
    """V0 pairing handshake failed — likely the S-Miles app is still bonded."""
