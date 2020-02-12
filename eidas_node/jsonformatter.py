""" Custom log formatter for adding 'tag' field."""

import json_log_formatter

class CustomJSONFormatter(json_log_formatter.JSONFormatter):
    def json_record(self, message, extra, record):
        parentExtra = super().json_record(message, extra, record)
        parentExtra['tag'] = "DJANGO.LOG"
        return parentExtra