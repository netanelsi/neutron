# Copyright (c) 2013 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import sys
import random
from neutron.plugins.ml2 import config

from neutron_lib import exceptions as exc
from oslo_config import cfg
from oslo_log import log

from neutron._i18n import _, _LE, _LI, _LW
from neutron.common import _deprecate
from neutron.db import api as db_api
from neutron.plugins.common import constants as p_const
from neutron.plugins.ml2 import driver_api as api
from neutron.plugins.ml2.drivers import helpers
from neutron.plugins.ml2.drivers import type_vlan
from neutron.common import exceptions as n_exc
from neutron.db import model_base
import sqlalchemy as sa

LOG = log.getLogger(__name__)

qinq_opts = [
    cfg.ListOpt('network_qinq_ranges',
                default=[],
                help=_("List of <physical_network>:<qinq_min>:<qinq_max> or "
                       "<physical_network> specifying physical_network names "
                       "usable for QINQ provider and tenant networks, as "
                       "well as ranges of QINQ tags on each available for "
                       "allocation to tenant networks."))
]

# cfg.register_opts(qinq_opts, "ml2_type_qinq")
cfg.CONF.register_opts(qinq_opts, "ml2_type_qinq")


class QinqAllocation(model_base.BASEV2):
    """Represent allocation state of a vlan_id on a physical network.

    If allocated is False, the vlan_id on the physical_network is
    available for allocation to a tenant network. If allocated is
    True, the vlan_id on the physical_network is in use, either as a
    tenant or provider network.

    When an allocation is released, if the vlan_id for the
    physical_network is inside the pool described by
    VlanTypeDriver.network_vlan_ranges, then allocated is set to
    False. If it is outside the pool, the record is deleted.
    """

    __tablename__ = 'ml2_qinq_allocations'
    __table_args__ = (
        sa.Index('ix_ml2_qinq_allocations_physical_network_allocated',
                 'physical_network', 'allocated'),
        model_base.BASEV2.__table_args__,)

    physical_network = sa.Column(sa.String(64), nullable=False,
                                 primary_key=True)
    qinq_id = sa.Column(sa.Integer, nullable=False, primary_key=True,
                        autoincrement=False)
    allocated = sa.Column(sa.Boolean, nullable=False)


class QinqTypeDriver(helpers.SegmentTypeDriver):
    """Manage state for QINQ networks with ML2.

    The VlanTypeDriver implements the 'vlan' network_type. VLAN
    network segments provide connectivity between VMs and other
    devices using any connected IEEE 802.1Q conformant
    physical_network segmented into virtual networks via IEEE 802.1Q
    headers. Up to 4094 VLAN network segments can exist on each
    available physical_network.
    """

    def __init__(self):
        LOG.info(_LI("Network QINQ ranges:"))
        config.cfg.CONF.set_override('network_qinq_ranges', ['1:300'], group='ml2_type_qinq')
        super(QinqTypeDriver, self).__init__(QinqAllocation)
        self._parse_network_qinq_ranges()
        self._parse_networks()

    def _parse_network_qinq_ranges(self):
        self.qinq_range = set()
        try:
            for entry in cfg.CONF.ml2_type_qinq.network_qinq_ranges:
                if entry.count(':') != 1:
                    raise n_exc.NetworkVlanRangeError(
                        vlan_range=entry,
                        error=_("Need exactly two values for qinq range"))
                qinq_min, qinq_max = entry.split(':')
                self.qinq_range.update(range(int(qinq_min), int(qinq_max)))
        except Exception:
            LOG.exception(_LE("Failed to parse network_ranges. "
                              "Service terminated!"))
            sys.exit(1)
        LOG.info(_LI("Network QINQ ranges: %s"), self.qinq_range)

    def _parse_networks(self):
        self.physical_networks = set()
        print ('cfg.CONF.ml2_type_vlan.network_vlan_ranges', cfg.CONF.ml2_type_vlan.network_vlan_ranges)
        for entry in cfg.CONF.ml2_type_vlan.network_vlan_ranges:
            if entry.count(':') != 2:
                raise n_exc.NetworkVlanRangeError(
                    vlan_range=entry,
                    error=_("Need exactly two values for vlan range"))
            physical_network, qinq_min, qinq_max = entry.split(':')
            print (physical_network, qinq_min, qinq_max)
            self.physical_networks.add(physical_network)
        print ('self.physical_networks', self.physical_networks)
        LOG.info(_LI("Network options: %s"), self.physical_networks)

    def validate_range(self, qinq_id):
        print ('validate_range')
        print qinq_id
        print self.qinq_range
        if qinq_id in self.qinq_range:
            return True
        return False

    @db_api.retry_db_errors
    def _sync_qinq_allocations(self):
        """determine what need to do with currently allocated."""
        # session = db_api.get_session()
        # with session.begin(subtransactions=True):
        #     # get existing allocations for all physical networks
        #     allocs = (session.query(qinq_alloc_model.QinqAllocation).
        #               with_lockmode('update'))
        #     for alloc in allocs:
        #         if not self.validate_range(alloc.qinq_id) and not alloc.allocated:
        #                 # it's not, so remove it from table
        #                 LOG.debug("Removing vlan %(vlan_id)s on "
        #                           "physical network "
        #                           "%(physical_network)s from pool",
        #                           {'vlan_id': alloc.vlan_id,
        #                            'physical_network':
        #                                alloc.physical_network})
        #                 session.delete(alloc)

    def get_type(self):
        return 'qinq'

    def initialize(self):
        vlan_type = type_vlan.VlanTypeDriver()
        vlan_type.initialize()
        self._sync_qinq_allocations()
        LOG.info(_LI("QinqTypeDriver initialization complete"))

    def is_partial_segment(self, segment):
        return segment.get(api.SEGMENTATION_ID) is None

    def validate_provider_segment(self, segment):
        print ('validate_provider_segment in qinq')
        physical_network = segment.get(api.PHYSICAL_NETWORK)
        segmentation_id = segment.get(api.SEGMENTATION_ID)

        if physical_network:
            print ('validate_provider_segment in qinq1')
            print ('physical_network', physical_network)
            print ('physical_networks', self.physical_networks)
            if physical_network not in self.physical_networks:
                print ('validate_provider_segment in qinq2')
                msg = (_("physical_network '%s' unknown ") % physical_network)
                raise exc.InvalidInput(error_message=msg)
            if not self.validate_range(segmentation_id):
                print ('validate_provider_segment in qinq3')
                msg = (_("segmentation_id out of range"))
                raise exc.InvalidInput(error_message=msg)
        elif segmentation_id:
            print ('validate_provider_segment in qinq4')
            msg = _("segmentation_id requires physical_network for QINQ "
                    "provider network")
            raise exc.InvalidInput(error_message=msg)

    def reserve_provider_segment(self, session, segment):
        filters = {}
        physical_network = segment.get(api.PHYSICAL_NETWORK)
        if physical_network is not None:
            filters['physical_network'] = physical_network
            qinq_id = segment.get(api.SEGMENTATION_ID)
            if qinq_id is not None:
                filters['qinq_id'] = qinq_id

        if self.is_partial_segment(segment):
            alloc = self.allocate_partially_specified_segment(
                session, **filters)
            if not alloc:
                raise exc.NoNetworkAvailable()
        else:
            alloc = self.allocate_fully_specified_segment(
                session, **filters)
            if not alloc:
                raise exc.VlanIdInUse(**filters)

        return {api.NETWORK_TYPE: self.get_type(),
                api.PHYSICAL_NETWORK: alloc.physical_network,
                api.SEGMENTATION_ID: alloc.qinq_id,
                api.MTU: self.get_mtu(alloc.physical_network)}

    def allocate_tenant_segment(self, session):
        alloc = self.allocate_partially_specified_segment(session)
        if not alloc:
            return
        return {api.NETWORK_TYPE: self.get_type(),
                api.PHYSICAL_NETWORK: alloc.physical_network,
                api.SEGMENTATION_ID: alloc.qinq_id,
                api.MTU: self.get_mtu(alloc.physical_network)}

    def release_segment(self, session, segment):
        physical_network = segment[api.PHYSICAL_NETWORK]
        qinq_id = segment[api.SEGMENTATION_ID]

        with session.begin(subtransactions=True):
            query = (session.query(QinqAllocation).
                     filter_by(physical_network=physical_network,
                               qinq_id=qinq_id))
            count = query.delete()
            if count:
                LOG.debug("Releasing vlan %(vlan_id)s on physical "
                          "network %(physical_network)s outside pool",
                          {'qinq_id': qinq_id,
                           'physical_network': physical_network})
            else:
                LOG.warning(_LW("No vlan_id %(vlan_id)s found on physical "
                                "network %(physical_network)s"),
                            {'qinq_id': qinq_id,
                             'physical_network': physical_network})

    def get_mtu(self, physical_network):
        seg_mtu = super(QinqTypeDriver, self).get_mtu()
        mtu = []
        if seg_mtu > 0:
            mtu.append(seg_mtu)
        if physical_network in self.physnet_mtus:
            mtu.append(int(self.physnet_mtus[physical_network]))
        return min(mtu) if mtu else 0

    def allocate_partially_specified_segment(self, session, **filters):
        """Allocate model segment from pool partially specified by filters.

        Return allocated db object or None.
        """
        qinq_allocated = set()
        with session.begin(subtransactions=True):
            select = session.query(self.model)
            for entry in select:
                qinq_allocated += entry.qinq_id
            selected_qinq = random.choice(self.qinq_range - qinq_allocated)
            selected_physical_network = random.choice(self.physical_network)
            print ('allocate_partially_specified_segment')
            alloc = QinqAllocation(
                physical_network=selected_physical_network[0],
                vlan_id=selected_qinq[0],
                allocated=True)
            session.add(alloc)
        return alloc

    def allocate_fully_specified_segment(self, session, **filters):
        """Allocate model segment from pool fully specified by filters.

        Return allocated db object or None.
        """
        qinq_allocated = set()
        with session.begin(subtransactions=True):
            select = session.query(QinqAllocation)
            for entry in select:
                qinq_allocated.add(entry.qinq_id)
            selected_qinq = random.sample(self.qinq_range - qinq_allocated, 1)
            selected_physical_network = random.sample(self.physical_networks, 1)
            print ('selected_qinq', selected_qinq[0])
            print ('selected_physical_network', selected_physical_network[0])
            selected_qinq[0] = filters['qinq_id']
            selected_physical_network[0] = filters['physical_network']
            alloc = QinqAllocation(
                physical_network=selected_physical_network[0],
                qinq_id=selected_qinq[0],
                allocated=True)
            session.add(alloc)
        return alloc

# _deprecate._MovedGlobals()
