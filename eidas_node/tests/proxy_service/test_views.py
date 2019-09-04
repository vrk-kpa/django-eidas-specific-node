from base64 import b64decode, b64encode
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, TextIO, Tuple, cast
from unittest.mock import MagicMock, call, patch

from django.test import RequestFactory, SimpleTestCase
from django.urls import reverse
from freezegun import freeze_time

from eidas_node.errors import ParseError, SecurityError
from eidas_node.models import LightRequest, LightResponse, LightToken, Status
from eidas_node.proxy_service.views import IdentityProviderResponseView, ProxyServiceRequestView
from eidas_node.saml import Q_NAMES, SAMLResponse
from eidas_node.storage.ignite import IgniteStorage
from eidas_node.tests.test_models import LIGHT_REQUEST_DICT, LIGHT_RESPONSE_DICT
from eidas_node.tests.test_storage import IgniteMockMixin
from eidas_node.utils import dump_xml, parse_xml

DATA_DIR = Path(__file__).parent.parent / 'data'  # type: Path


class TestProxyServiceRequestView(IgniteMockMixin, SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.url = reverse('proxy-service-request')
        self.addCleanup(self.mock_ignite_cache())

    def get_token(self, issuer: str = None) -> Tuple[LightToken, str]:
        token = LightToken(id='request-token-id',
                           issuer=issuer or 'request-token-issuer',
                           created=datetime(2017, 12, 11, 14, 12, 5, 148000))
        encoded = token.encode('sha256', 'request-token-secret').decode('utf-8')
        return token, encoded

    def test_get_not_allowed(self):
        response = self.client.get(self.url)
        self.assertEquals(response.status_code, 405)
        self.assertNotIn(b'https://example.net/identity-provider-endpoint', response.content)

    def test_get_light_token_no_token(self):
        view = ProxyServiceRequestView()
        view.request = self.factory.post(self.url)
        with self.assertRaisesMessage(ParseError, 'Token has wrong number of parts'):
            view.get_light_token('test_token', 'request-token-issuer', 'sha256', 'request-token-secret')

    def test_get_light_token_expired(self):
        _token, encoded = self.get_token()
        view = ProxyServiceRequestView()
        view.request = self.factory.post(self.url, {'test_token': encoded})
        with self.assertRaisesMessage(SecurityError, 'Token has expired'):
            view.get_light_token('test_token', 'request-token-issuer', 'sha256', 'request-token-secret', 1)

    def test_get_light_token_success(self):
        orig_token, encoded = self.get_token()
        view = ProxyServiceRequestView()
        view.request = self.factory.post(self.url, {'test_token': encoded})
        token = view.get_light_token('test_token', 'request-token-issuer', 'sha256', 'request-token-secret', 0)
        self.assertEqual(token, orig_token)

    @freeze_time('2017-12-11 14:12:05')
    def test_get_light_token_wrong_issuer(self):
        _token, encoded = self.get_token('wrong-issuer')
        view = ProxyServiceRequestView()
        view.request = self.factory.post(self.url, {'test_token': encoded})

        with self.assertRaisesMessage(SecurityError, 'Invalid token issuer'):
            view.get_light_token('test_token', 'request-token-issuer', 'sha256', 'request-token-secret')

    def test_get_light_request_not_found(self):
        self.cache_mock.get.return_value = None
        token, encoded = self.get_token()

        view = ProxyServiceRequestView()
        view.request = self.factory.post(self.url, {'test_token': encoded})
        view.light_token = token
        view.storage = IgniteStorage('test.example.net', 1234, 'test-proxy-service-request-cache', '')

        with self.assertRaisesMessage(SecurityError, 'Request not found in light storage'):
            view.get_light_request()

    def test_get_light_request_success(self):
        orig_light_request = LightRequest(**LIGHT_REQUEST_DICT)
        self.cache_mock.get.return_value = dump_xml(orig_light_request.export_xml()).decode('utf-8')
        token, encoded = self.get_token()

        view = ProxyServiceRequestView()
        view.request = self.factory.post(self.url, {'test_token': encoded})
        view.light_token = token
        view.storage = IgniteStorage('test.example.net', 1234, 'test-proxy-service-request-cache', '')

        light_request = view.get_light_request()
        self.assertEqual(light_request, orig_light_request)
        self.maxDiff = None
        self.assertEqual(self.client_mock.mock_calls,
                         [call.connect('test.example.net', 1234),
                          call.get_cache('test-proxy-service-request-cache'),
                          call.get_cache().get('request-token-id')])

    @freeze_time('2017-12-11 14:12:05')
    def test_create_saml_request(self):
        light_request = LightRequest(**LIGHT_REQUEST_DICT)
        token, encoded = self.get_token()

        view = ProxyServiceRequestView()
        view.request = self.factory.post(self.url, {'test_token': encoded})
        view.light_token = token
        view.light_request = light_request

        saml_request = view.create_saml_request('https://test.example.net/saml/idp.xml')
        root = saml_request.document.getroot()
        self.assertEqual(root.get('ID'), 'T' + token.id)
        self.assertEqual(root.get('IssueInstant'), '2017-12-11T14:12:05.000Z')
        self.assertEqual(root.find(".//{}".format(Q_NAMES['saml2:Issuer'])).text,
                         'https://test.example.net/saml/idp.xml')

    @freeze_time('2017-12-11 14:12:05')
    def test_post_success(self):
        self.maxDiff = None
        request = LightRequest(**LIGHT_REQUEST_DICT)
        self.cache_mock.get.return_value = dump_xml(request.export_xml()).decode('utf-8')

        token, encoded = self.get_token()
        response = self.client.post(self.url, {'test_token': encoded})

        # Context
        self.assertIn('saml_request', response.context)
        self.assertEqual(response.context['identity_provider_endpoint'],
                         'https://test.example.net/identity-provider-endpoint')
        self.assertEqual(response.context['relay_state'], 'relay123')
        self.assertEqual(response.context['error'], None)

        # SAML Request
        saml_request_xml = b64decode(response.context['saml_request'].encode('utf-8')).decode('utf-8')
        self.assertIn(token.id, saml_request_xml)  # light_request.id replaced with token.id
        self.assertIn('<saml2:Issuer Format="urn:oasis:names:tc:SAML:2.0:nameid-format:entity">'
                      'https://test.example.net/saml/idp.xml</saml2:Issuer>', saml_request_xml)
        self.assertIn('Destination="http://testserver/IdentityProviderResponse"', saml_request_xml)

        # Rendering
        self.assertContains(response, 'Redirect to Identity Provider is in progress')
        self.assertContains(response, '<form action="https://test.example.net/identity-provider-endpoint"')
        self.assertContains(response, '<input type="hidden" name="SAMLRequest" value="{}"'.format(
            response.context['saml_request']))
        self.assertContains(response, '<input type="hidden" name="RelayState" value="relay123"/>')
        self.assertNotIn(b'An error occurred', response.content)

    def test_post_failure(self):
        response = self.client.post(self.url)
        self.assertNotIn(b'https://example.net/identity-provider-endpoint', response.content)
        self.assertContains(response,
                            'An error occurred during processing of Service Provider request.',
                            status_code=400)
        self.assertEqual(response.context['error'], 'Bad proxy service request.')
        self.assertNotIn('identity_provider_endpoint', response.context)
        self.assertNotIn('saml_request', response.context)
        self.assertNotIn('relay_state', response.context)


class TestIdentityProviderResponseView(IgniteMockMixin, SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.url = reverse('identity-provider-response')
        self.addCleanup(self.mock_ignite_cache())

    def test_get_not_allowed(self):
        response = self.client.get(self.url)
        self.assertEquals(response.status_code, 405)
        self.assertNotIn(b'https://example.net/EidasNode/SpecificProxyServiceResponse', response.content)

    def test_get_saml_response_no_data(self):
        view = IdentityProviderResponseView()
        view.request = self.factory.post(self.url)
        self.assertRaises(ParseError, view.get_saml_response, None)

    def test_get_saml_response_relay_state_optional(self):
        with cast(BinaryIO, (DATA_DIR / 'saml_response.xml').open('rb')) as f:
            saml_response_xml = f.read()

        view = IdentityProviderResponseView()
        view.request = self.factory.post(self.url, {'SAMLResponse': b64encode(saml_response_xml).decode('ascii')})
        saml_response = view.get_saml_response(None)
        self.assertIsNone(saml_response.relay_state)

    def test_get_saml_response_encrypted(self):
        with cast(BinaryIO, (DATA_DIR / 'saml_response_encrypted.xml').open('rb')) as f:
            saml_response_xml = f.read()

        with cast(TextIO, (DATA_DIR / 'saml_response_decrypted.xml').open('r')) as f2:
            decrypted_saml_response_xml = f2.read()

        view = IdentityProviderResponseView()
        view.request = self.factory.post(self.url, {'SAMLResponse': b64encode(saml_response_xml).decode('ascii'),
                                                    'RelayState': 'relay123'})
        saml_response = view.get_saml_response(str(DATA_DIR / 'key.pem'))
        self.assertEqual(saml_response.relay_state, 'relay123')
        self.assertXMLEqual(dump_xml(saml_response.document).decode('utf-8'), decrypted_saml_response_xml)

    def test_create_light_response_id_not_prefixed(self):
        view = IdentityProviderResponseView()
        view.request = self.factory.post(self.url)
        view.storage = IgniteStorage('test.example.net', 1234, 'test-proxy-service-request-cache', '')
        self.cache_mock.get.return_value = None

        with cast(TextIO, (DATA_DIR / 'saml_response.xml').open('r')) as f:
            data = f.read().replace('Ttest-saml-request-id', 'test-saml-request-id')
            view.saml_response = SAMLResponse(parse_xml(data), 'relay123')

        with self.assertRaisesMessage(SecurityError, 'Invalid in-response-to id'):
            view.create_light_response('test-light-response-issuer')

    def test_create_light_response_cannot_find_request(self):
        view = IdentityProviderResponseView()
        view.request = self.factory.post(self.url)
        view.storage = IgniteStorage('test.example.net', 1234, 'test-proxy-service-request-cache', '')
        self.cache_mock.get.return_value = None

        with cast(TextIO, (DATA_DIR / 'saml_response.xml').open('r')) as f:
            view.saml_response = SAMLResponse(parse_xml(f.read()), 'relay123')

        with self.assertRaisesMessage(SecurityError, 'Cannot pair light response and request'):
            view.create_light_response('test-light-response-issuer')

    def test_create_light_response_correct_id_and_issuer(self):
        self.maxDiff = None
        view = IdentityProviderResponseView()
        view.request = self.factory.post(self.url)
        view.storage = IgniteStorage('test.example.net', 1234, 'test-proxy-service-request-cache', '')
        orig_light_request = LightRequest(**LIGHT_REQUEST_DICT)
        orig_light_request.issuer = 'https://example.net/EidasNode/ConnectorMetadata'
        self.cache_mock.get.return_value = dump_xml(orig_light_request.export_xml()).decode('utf-8')

        with cast(TextIO, (DATA_DIR / 'saml_response.xml').open('r')) as f:
            view.saml_response = SAMLResponse(parse_xml(f.read()), 'relay123')

        light_response, light_request = view.create_light_response('test-light-response-issuer')
        self.assertEqual(light_response.id, 'test-saml-response-id')
        self.assertEqual(light_response.in_response_to_id, 'test-light-request-id')
        self.assertEqual(light_response.issuer, 'test-light-response-issuer')

        self.assertEqual(self.client_mock.mock_calls,
                         [call.connect('test.example.net', 1234),
                          call.get_cache('test-proxy-service-request-cache'),
                          call.get_cache().get('test-saml-request-id')])

    @freeze_time('2017-12-11 14:12:05')
    @patch('eidas_node.utils.uuid4', return_value='0uuid4')
    def test_create_light_token(self, uuid_mock: MagicMock):
        view = IdentityProviderResponseView()
        view.request = self.factory.post(self.url)
        light_response_data = LIGHT_RESPONSE_DICT.copy()
        light_response_data['status'] = Status(**light_response_data['status'])
        view.light_response = LightResponse(**light_response_data)

        token, encoded_token = view.create_light_token('test-token-issuer', 'sha256', 'test-secret')
        self.assertEqual(token.id, 'T0uuid4')
        self.assertEqual(token.issuer, 'test-token-issuer')
        self.assertEqual(token.created, datetime(2017, 12, 11, 14, 12, 5))
        self.assertEqual(view.light_response.id, 'T0uuid4')
        self.assertEqual(token.encode('sha256', 'test-secret').decode('ascii'), encoded_token)
        self.assertEqual(uuid_mock.mock_calls, [call()])

    @freeze_time('2017-12-11 14:12:05')
    @patch('eidas_node.utils.uuid4', return_value='0uuid4')
    def test_post_success(self, uuid_mock: MagicMock):
        light_request = LightRequest(**LIGHT_REQUEST_DICT)
        light_request.issuer = 'https://example.net/EidasNode/ConnectorMetadata'
        self.cache_mock.get.return_value = dump_xml(light_request.export_xml()).decode('utf-8')

        with cast(BinaryIO, (DATA_DIR / 'saml_response.xml').open('rb')) as f:
            saml_request_xml = f.read()

        response = self.client.post(self.url, {'SAMLResponse': b64encode(saml_request_xml).decode('ascii'),
                                               'RelayState': 'relay123'})

        # Context
        self.assertIn('token', response.context)
        self.assertEqual(response.context['token_parameter'], 'test_token')
        self.assertEqual(response.context['eidas_url'], 'https://test.example.net/SpecificProxyServiceResponse')
        self.assertEqual(response.context['error'], None)

        # Token
        encoded_token = response.context['token']
        token = LightToken.decode(encoded_token, 'sha256', 'response-token-secret')
        self.assertEqual(token.id, 'T0uuid4')
        self.assertEqual(token.issuer, 'response-token-issuer')
        self.assertEqual(token.created, datetime(2017, 12, 11, 14, 12, 5))

        # Storing light response
        light_response_data = LIGHT_RESPONSE_DICT.copy()
        light_response_data.update({
            'status': Status(**light_response_data['status']),
            'id': 'T0uuid4',
            'in_response_to_id': 'test-light-request-id',
            'issuer': 'https://test.example.net/node-proxy-service-response',
        })
        light_response = LightResponse(**light_response_data)
        self.assertEqual(self.client_class_mock.mock_calls, [call(timeout=66)])
        self.assertEqual(self.client_mock.mock_calls,
                         [call.connect('test.example.net', 1234),
                          call.get_cache('test-proxy-service-request-cache'),
                          call.get_cache().get('test-saml-request-id'),
                          call.get_cache('test-proxy-service-response-cache'),
                          call.get_cache().put('T0uuid4', dump_xml(light_response.export_xml()).decode('utf-8'))])

        # Rendering
        self.assertContains(response, 'Redirect to Service Provider is in progress')
        self.assertContains(response, '<form action="https://test.example.net/SpecificProxyServiceResponse"')
        self.assertContains(response, '<input type="hidden" name="test_token" value="{}"'.format(encoded_token))
        self.assertNotIn(b'An error occurred', response.content)

    def test_post_failure(self):
        response = self.client.post(self.url)
        self.assertNotIn(b'https://test.example.net/SpecificProxyServiceResponse', response.content)
        self.assertContains(response,
                            'An error occurred during processing of Identity Provider response.',
                            status_code=400)
        self.assertContains(response, 'An error occurred', status_code=400)
        self.assertEqual(response.context['error'], 'Bad proxy service request.')
        self.assertNotIn('eidas_url', response.context)
        self.assertNotIn('token', response.context)
        self.assertNotIn('token_parameter', response.context)