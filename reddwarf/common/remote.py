# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2012 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http: //www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from reddwarf.common import cfg
from novaclient.v1_1.client import Client
from swiftclient.client import Connection


CONF = cfg.CONF
COMPUTE_URL = CONF.nova_compute_url
PROXY_AUTH_URL = CONF.reddwarf_auth_url
VOLUME_URL = CONF.nova_volume_url
OBJECT_STORE_URL = CONF.swift_url


def create_dns_client(context):
    from reddwarf.dns.manager import DnsManager
    return DnsManager()


def create_guest_client(context, id):
    from reddwarf.guestagent.api import API
    return API(context, id)


def create_nova_client(context):
    client = Client(context.user, context.auth_token,
                    project_id=context.tenant, auth_url=PROXY_AUTH_URL)
    client.client.auth_token = context.auth_token
    client.client.management_url = "%s/%s/" % (COMPUTE_URL, context.tenant)

    return client


def create_nova_volume_client(context):
    # Quite annoying but due to a paste config loading bug.
    # TODO(hub-cap): talk to the openstack-common people about this
    client = Client(context.user, context.auth_token,
                    project_id=context.tenant, auth_url=PROXY_AUTH_URL)
    client.client.auth_token = context.auth_token
    client.client.management_url = "%s/%s/" % (VOLUME_URL, context.tenant)

    return client


def create_swift_client(context):
    client = Connection(preauthurl=OBJECT_STORE_URL + context.tenant,
                        preauthtoken=context.auth_token,
                        tenant_name=context.tenant)
    return client

# Override the functions above with fakes.
if CONF.remote_implementation == "fake":
    from reddwarf.tests.fakes.nova import fake_create_nova_client
    from reddwarf.tests.fakes.nova import fake_create_nova_volume_client
    from reddwarf.tests.fakes.guestagent import fake_create_guest_client
    from reddwarf.tests.fakes.swift import FakeSwiftClient

    def create_guest_client(context, id):
        return fake_create_guest_client(context, id)

    def create_nova_client(context):
        return fake_create_nova_client(context)

    def create_nova_volume_client(context):
        return fake_create_nova_volume_client(context)

    def create_swift_client(context):
        return FakeSwiftClient.Connection(context)
