import functools

import fixtures
from neutron_lib.plugins import directory

from neutron import context
from neutron.extensions import multiprovidernet as mpnet
from neutron.extensions import providernet as pnet
from neutron.plugins.ml2 import config
from neutron.tests.unit.db import test_db_base_plugin_v2 as test_plugin

PLUGIN_NAME = 'ml2'

class PluginConfFixture(fixtures.Fixture):
    """Plugin configuration shared across the unit and functional tests."""

    def __init__(self, plugin_name, parent_setup=None):
        super(PluginConfFixture, self).__init__()
        self.plugin_name = plugin_name
        self.parent_setup = parent_setup

    def _setUp(self):
        if self.parent_setup:
            self.parent_setup()


class Ml2ConfFixture(PluginConfFixture):

    def __init__(self, parent_setup=None):
        super(Ml2ConfFixture, self).__init__(PLUGIN_NAME, parent_setup)


class Ml2PluginV2TestCase(test_plugin.NeutronDbPluginV2TestCase):

    _mechanism_drivers = ['logger', 'test']
    l3_plugin = ('neutron.tests.unit.extensions.test_l3.'
                 'TestL3NatServicePlugin')

    def get_additional_service_plugins(self):
        """Subclasses can return a dictionary of service plugins to load."""
        return {}

    def setup_parent(self):
        """Perform parent setup with the common plugin configuration class."""
        service_plugins = {'l3_plugin_name': self.l3_plugin}
        service_plugins.update(self.get_additional_service_plugins())
        # Ensure that the parent setup can be called without arguments
        # by the common configuration setUp.
        parent_setup = functools.partial(
            super(Ml2PluginV2TestCase, self).setUp,
            plugin=PLUGIN_NAME,
            service_plugins=service_plugins,
        )
        self.useFixture(Ml2ConfFixture(parent_setup))
        self.port_create_status = 'DOWN'

    def setUp(self):
        # Enable the test mechanism driver to ensure that
        # we can successfully call through to all mechanism
        # driver apis.
        config.cfg.CONF.set_override('mechanism_drivers',
                                     self._mechanism_drivers,
                                     group='ml2')
        self.physnet = 'physnet1'
        self.vlan_range = '1:100'
        self.vlan_range2 = '200:300'
        self.physnet2 = 'physnet2'
        self.phys_vrange = ':'.join([self.physnet, self.vlan_range])
        self.phys2_vrange = ':'.join([self.physnet2, self.vlan_range2])
        config.cfg.CONF.set_override('network_vlan_ranges',
                                     [self.phys_vrange, self.phys2_vrange],
                                     group='ml2_type_vlan')
        self.setup_parent()
        self.driver = directory.get_plugin()
        self.context = context.get_admin_context()

class TestMl2NetworksV2(test_plugin.TestNetworksV2,
                        Ml2PluginV2TestCase):
    def setUp(self, plugin=None):
        config.cfg.CONF.set_override('type_drivers', ['local', 'flat', 'qinq', 'vlan', 'gre', 'vxlan', 'geneve'], group='ml2')
        print 'yoav damri'
        print config.cfg.CONF._groups
        print config.cfg.CONF._opts
        # config.cfg.CONF.set_override('network_qinq_ranges', ['1:100'], group='ml2_type_qinq')
        super(TestMl2NetworksV2, self).setUp()
        # provider networks
        self.pnets = [{'name': 'net1',
                       pnet.NETWORK_TYPE: 'qinq',
                       pnet.PHYSICAL_NETWORK: 'physnet1',
                       pnet.SEGMENTATION_ID: 1,
                       'tenant_id': 'tenant_one'},
                      {'name': 'net2',
                       pnet.NETWORK_TYPE: 'qinq',
                       pnet.PHYSICAL_NETWORK: 'physnet2',
                       pnet.SEGMENTATION_ID: 210,
                       'tenant_id': 'tenant_one'},
                      {'name': 'net3',
                       pnet.NETWORK_TYPE: 'qinq',
                       pnet.PHYSICAL_NETWORK: 'physnet2',
                       pnet.SEGMENTATION_ID: 220,
                       'tenant_id': 'tenant_one'}
                      ]
        # multiprovider networks
        self.mp_nets = [{'name': 'net4',
                         mpnet.SEGMENTS:
                             [{pnet.NETWORK_TYPE: 'vlan',
                               pnet.PHYSICAL_NETWORK: 'physnet2',
                               pnet.SEGMENTATION_ID: 1},
                              {pnet.NETWORK_TYPE: 'vlan',
                               pnet.PHYSICAL_NETWORK: 'physnet2',
                               pnet.SEGMENTATION_ID: 202}],
                         'tenant_id': 'tenant_one'}
                        ]
        self.nets = self.mp_nets + self.pnets

    def test_list_mpnetworks_with_segmentation_id(self):
        print ('gal is nets', self.nets)
        self._create_and_verify_networks(self.nets)

        # get all networks with seg_id=1 (including multisegment networks)
        lookup_vlan_id = 1
        networks = self._lookup_network_by_segmentation_id(lookup_vlan_id, 2)

        # get the mpnet
        networks = [n for n in networks['networks'] if mpnet.SEGMENTS in n]
        network = networks.pop()
        # verify attributes of the looked up item
        segments = network[mpnet.SEGMENTS]
        expected_segments = self.mp_nets[0][mpnet.SEGMENTS]
        self.assertEqual(len(expected_segments), len(segments))
        for expected, actual in zip(expected_segments, segments):
            self.assertEqual(expected, actual)