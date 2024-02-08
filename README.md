# homeassistant-kafka-multiple-topics

Extended the code found at: https://github.com/home-assistant/core/tree/dev/homeassistant/components/apache_kafka

All credits to the original creator, whoever you are, thanks a lot!


### Example usage:

in your configuration.yml:
```
apache_kafka_multiple_topics:
  ip_address: kafka-broker-service
  port: 9092
  topics: 
    - topic: test-topic-1   # caputures everything
    - topic: test-topic-2   # captures only sensor.sun_next_dusk
      filter:
        include_entities:
          - sensor.sun_next_dusk
```

__Note:__ Set a filter at the root level to apply it to all topics.

```
apache_kafka_multiple_topics:
  ip_address: kafka-broker-service
  port: 9092
  topics: 
    - topic: test-topic     # caputures everything except sensor.sun_next_dusk
    - topic: test-topic-2   # captures only sensor.sun_next_dawn
      filter:
        include_entities:
          - sensor.sun_next_dawn
  filter:
    exclude_entities:
      - sensor.sun_next_dusk
```
