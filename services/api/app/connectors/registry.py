"""Resolve `(layer, provider)` → concrete `Connector`.

The DB row on `connections` carries the layer, so the gateway can pick the
right implementation per call without the rest of the app caring.
"""
from .base import Connector, ConnectorLayer
from .composio import ComposioConnector
from .custom_mcp import CustomMCPConnector, CustomMCPSpec
from .hermes_native import SUPPORTED as NATIVE_SUPPORTED, HermesNativeConnector


def get_connector(
    layer: ConnectorLayer | str,
    provider: str,
    custom_spec: CustomMCPSpec | None = None,
) -> Connector:
    layer = ConnectorLayer(layer)
    if layer is ConnectorLayer.NATIVE:
        if provider not in NATIVE_SUPPORTED:
            raise ValueError(
                f"{provider!r} has no native Hermes plugin; "
                f"use composio or custom"
            )
        return HermesNativeConnector(provider)
    if layer is ConnectorLayer.COMPOSIO:
        return ComposioConnector(provider)
    if layer is ConnectorLayer.CUSTOM:
        if custom_spec is None:
            raise ValueError("custom connectors require a CustomMCPSpec")
        return CustomMCPConnector(provider, custom_spec)
    raise ValueError(f"unknown connector layer: {layer}")
