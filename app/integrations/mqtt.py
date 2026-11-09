"""MQTT transport with a thread-safe bridge into asyncio."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime

import paho.mqtt.client as mqtt

log = logging.getLogger(__name__)


class MqttTransport:
    def __init__(self, host: str, port: int, client_id: str = "pia-assistant"):
        self.host = host
        self.port = port
        self.queue: asyncio.Queue[tuple[str, dict]] = asyncio.Queue()
        self.connected = asyncio.Event()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=True)
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(1, 15)
        self.last_sent = 0.0

    def start(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()

    def _on_connect(self, client, _userdata, _flags, reason_code, _properties=None):
        log.info("mqtt connected (%s)", reason_code)
        client.subscribe("planta/#", qos=1)
        if self.loop:
            self.loop.call_soon_threadsafe(self.connected.set)

    def _on_message(self, _client, _userdata, message):
        try:
            payload = json.loads(message.payload)
        except json.JSONDecodeError:
            log.warning("invalid JSON on %s", message.topic)
            return
        if self.loop:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, (message.topic, payload))

    def publish(self, topic: str, payload: dict, qos: int = 1) -> None:
        self.client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=qos)
        self.last_sent = datetime.now().timestamp()

    async def messages(self) -> AsyncIterator[tuple[str, dict]]:
        while True:
            topic, payload = await self.queue.get()
            yield topic, payload

    async def wait_connected(self, timeout: float = 30) -> bool:
        try:
            await asyncio.wait_for(self.connected.wait(), timeout)
            return True
        except TimeoutError:
            return False

    def stop(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()
