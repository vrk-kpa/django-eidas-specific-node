"""
Development settings for eidas_node Django app.

DO NOT USE IN PRODUCTION!

See https://docs.djangoproject.com/en/2.2/howto/deployment/checklist/
"""

from typing import Dict, Any

from eidas_node.connector.settings import DEFAULT_COUNTRIES
from eidas_node.tests.constants import KEY_FILE, CERT_FILE

SECRET_KEY = '5x-fiyyunqio&)a+8%$0fqvqpc1s18n^xj21ftc-ojpu2)jmce'
DEBUG = True
ALLOWED_HOSTS = ['*']

INSTALLED_APPS = (
    'django.contrib.staticfiles',
    'eidas_node.connector.apps.ConnectorConfig',
)
MIDDLEWARE = (
    'django.middleware.common.CommonMiddleware',
)
# Use 'eidas_node.connector.urls' in production.
ROOT_URLCONF = 'eidas_node.connector.demo.urls'
STATIC_URL = '/static/'
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.contrib.messages.context_processors.messages',
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.template.context_processors.i18n',
            ]
        }
    }
]

# eIDAS Proxy Service
CONNECTOR_REQUEST_TOKEN = {
    'HASH_ALGORITHM': 'sha256',
    'SECRET': 'mySecretConnectorRequest',
    'ISSUER': 'specificCommunicationDefinitionConnectorRequest',
}  # type: Dict[str, Any]

CONNECTOR_RESPONSE_TOKEN = {
    'HASH_ALGORITHM': 'sha256',
    'SECRET': 'mySecretConnectorResponse',
    'ISSUER': 'specificCommunicationDefinitionConnectorResponse',
    'LIFETIME': 10,  # minutes
}  # type: Dict[str, str]

CONNECTOR_SERVICE_PROVIDER = {
    'ENDPOINT': '/DemoServiceProviderResponse',
    'REQUEST_ISSUER': 'REQUEST_ISSUER',
    'RESPONSE_ISSUER': 'RESPONSE_ISSUER',
    'RESPONSE_SIGNATURE': {
        'KEY_FILE': KEY_FILE,
        'CERT_FILE': CERT_FILE,
    },
    'RESPONSE_KMS_SIGNATURE': {
        'KMS_ENABLED': bool(False),        
        'KMS_KEY_ALIAS': '',
        'CERT_FILE': '',
    },
}  # type: Dict[str, str]

CONNECTOR_LIGHT_STORAGE = {
    'BACKEND': 'eidas_node.storage.ignite.IgniteStorage',
    'OPTIONS': {
        'host': 'pokuston-m-01.office.nic.cz',
        'port': 10800,
        'request_cache_name': 'specificNodeConnectorRequestCache',
        'response_cache_name': 'nodeSpecificConnectorResponseCache',
    }
}  # type: Dict[str, Any]

CONNECTOR_EIDAS_NODE = {
    'CONNECTOR_REQUEST_URL': 'http://pokuston.office.nic.cz:8888/EidasNode/SpecificConnectorRequest',
    'REQUEST_ISSUER': 'connector-request-issuer',
}  # type: Dict[str, str]

# If your test country is not in eidas_node.connector.settings.DEFAULT_COUNTRIES, you can add it like this:
CONNECTOR_SELECTOR_COUNTRIES = [('CA', 'Test Country')] + DEFAULT_COUNTRIES

# Logging
LOGGING = {
    'version': 1,
    'formatters': {
        'verbose': {'format': '%(asctime)s %(levelname)-8s %(module)s:%(funcName)s:%(lineno)s %(message)s'},
    },
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        '': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
           'handlers': ['console'],
           'level': 'DEBUG',
           'propagate': False,
        },
        'django': {
           'handlers': ['console'],
           'level': 'INFO',
           'propagate': False,
        },
        'eidas_node.connector': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'eidas_node.storage': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}
