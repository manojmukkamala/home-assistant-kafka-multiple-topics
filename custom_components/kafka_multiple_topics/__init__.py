"""Support for Apache Kafka Multiple Topics."""
from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Dict, List, Literal

from aiokafka import AIOKafkaProducer
import voluptuous as vol

from homeassistant.const import (
    CONF_IP_ADDRESS,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
    EVENT_STATE_CHANGED,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entityfilter import FILTER_SCHEMA, EntityFilter
from homeassistant.helpers.event import EventStateChangedData
from homeassistant.helpers.typing import ConfigType, EventType
from homeassistant.util import ssl as ssl_util

DOMAIN = "apache_kafka"

CONF_FILTER = "filter"
CONF_TOPICS = "topics"
CONF_SECURITY_PROTOCOL = "security_protocol"


TOPIC_SCHEMA = vol.Schema(
    {
        vol.Required("topic"): cv.string,
        vol.Optional(CONF_FILTER, default={}): FILTER_SCHEMA,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_IP_ADDRESS): cv.string,
                vol.Required(CONF_PORT): cv.port,
                vol.Required(CONF_TOPICS): vol.All(cv.ensure_list, [TOPIC_SCHEMA]),
                vol.Optional(CONF_FILTER, default={}): FILTER_SCHEMA,
                vol.Optional(CONF_SECURITY_PROTOCOL, default="PLAINTEXT"): vol.In(
                    ["PLAINTEXT", "SASL_SSL"]
                ),
                vol.Optional(CONF_USERNAME): cv.string,
                vol.Optional(CONF_PASSWORD): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Activate the Apache Kafka integration."""
    conf = config[DOMAIN]

    kafka = hass.data[DOMAIN] = KafkaManager(
        hass,
        conf[CONF_IP_ADDRESS],
        conf[CONF_PORT],
        conf[CONF_TOPICS],
        conf[CONF_FILTER],
        conf[CONF_SECURITY_PROTOCOL],
        conf.get(CONF_USERNAME),
        conf.get(CONF_PASSWORD),
    )

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, kafka.shutdown)

    await kafka.start()

    return True


class DateTimeJSONEncoder(json.JSONEncoder):
    """Encode python objects.

    Additionally add encoding for datetime objects as isoformat.
    """

    def default(self, o: Any) -> str:
        """Implement encoding logic."""
        if isinstance(o, datetime):
            return o.isoformat()
        return super().default(o)  # type: ignore[no-any-return]


class KafkaManager:
    """Define a manager to buffer events to Kafka."""

    def __init__(
        self,
        hass: HomeAssistant,
        ip_address: str,
        port: int,
        topics: List[Dict[str, Any]],
        entities_filter: EntityFilter,
        security_protocol: Literal["PLAINTEXT", "SASL_SSL"],
        username: str | None,
        password: str | None,
    ) -> None:
        """Initialize."""
        self._encoder = DateTimeJSONEncoder()
        self._entities_filter = entities_filter
        self._hass = hass
        ssl_context = ssl_util.client_context()
        self._producer = AIOKafkaProducer(
            bootstrap_servers=f"{ip_address}:{port}",
            compression_type="gzip",
            security_protocol=security_protocol,
            ssl_context=ssl_context,
            sasl_mechanism="PLAIN",
            sasl_plain_username=username,
            sasl_plain_password=password,
        )
        self._topics = topics

    def _encode_event(self, event: EventType[EventStateChangedData], topic_entities_filter: EntityFilter) -> bytes | None:
        """Translate events into a binary JSON payload."""
        state = event.data["new_state"]
        if (
            state is None
            or state.state in (STATE_UNKNOWN, "", STATE_UNAVAILABLE)
            or not self._entities_filter(state.entity_id)
            or not topic_entities_filter(state.entity_id)
        ):
            return None

        return json.dumps(obj=state.as_dict(), default=self._encoder.encode).encode(
            "utf-8"
        )

    async def start(self) -> None:
        """Start the Kafka manager."""
        self._hass.bus.async_listen(EVENT_STATE_CHANGED, self.write)  # type: ignore[arg-type]
        await self._producer.start()

    async def shutdown(self, _: Event) -> None:
        """Shut the manager down."""
        await self._producer.stop()

    async def write(self, event: EventType[EventStateChangedData]) -> None:
        """Write a binary payload to Kafka."""
        for topic_and_filters in self._topics:
            topic = topic_and_filters['topic']
            topic_entities_filter = topic_and_filters['filter']
            payload = self._encode_event(event, topic_entities_filter)

            if payload:
                await self._producer.send_and_wait(topic, payload)