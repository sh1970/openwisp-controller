import uuid
from unittest import TestCase
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TransactionTestCase
from django.urls import reverse
from swapper import load_model

from openwisp_controller.config.tests.utils import (
    TestVpnX509Mixin,
    TestWireguardVpnMixin,
)
from openwisp_controller.subnet_division.rule_types.vpn import VpnSubnetDivisionRuleType
from openwisp_utils.tests import catch_signal

from .. import tasks
from ..signals import subnet_provisioned
from ..utils import get_subnet_division_config_context
from .helpers import SubnetDivisionTestMixin

Subnet = load_model("openwisp_ipam", "Subnet")
IpAddress = load_model("openwisp_ipam", "IpAddress")
SubnetDivisionRule = load_model("subnet_division", "SubnetDivisionRule")
SubnetDivisionIndex = load_model("subnet_division", "SubnetDivisionIndex")
VpnClient = load_model("config", "VpnClient")
Device = load_model("config", "Device")
OrganizationConfigSettings = load_model("config", "OrganizationConfigSettings")
Notification = load_model("openwisp_notifications", "Notification")


class BaseSubnetDivisionRule:
    config_label = "config"
    ipam_label = "openwisp_ipam"

    @property
    def ip_query(self):
        return IpAddress.objects.exclude(id=self.vpn_server.ip_id)

    def test_provisioned_subnets(self):
        rule = self._get_vpn_subdivision_rule()
        subnet_query = self.subnet_query.filter(organization_id=self.org.id).exclude(
            id=self.master_subnet.id
        )
        self.assertEqual(subnet_query.count(), 0)

        self.config.templates.add(self.template)

        self.assertEqual(
            subnet_query.count(),
            rule.number_of_subnets,
        )
        self.assertEqual(
            self.ip_query.count(), (rule.number_of_subnets * rule.number_of_ips)
        )

        # Verify context of config
        context = get_subnet_division_config_context(self.config)
        self.assertIn(f"{rule.label}_prefixlen", context)
        for subnet_id in range(1, rule.number_of_subnets + 1):
            self.assertIn(f"{rule.label}_subnet{subnet_id}", context)
            for ip_id in range(1, rule.number_of_ips + 1):
                self.assertIn(f"{rule.label}_subnet{subnet_id}_ip{ip_id}", context)


class TestSubnetDivisionRule(
    SubnetDivisionTestMixin,
    BaseSubnetDivisionRule,
    TestWireguardVpnMixin,
    TransactionTestCase,
):
    def setUp(self):
        self.org = self._get_org()
        self.master_subnet = self._get_master_subnet()
        self.vpn_server = self._create_wireguard_vpn(
            subnet=self.master_subnet,
            organization=self.org,
        )
        self.template = self._create_template(
            name="vpn-test", type="vpn", vpn=self.vpn_server, organization=self.org
        )
        self.config = self._create_config(organization=self.org)

    def test_field_validations(self):
        default_options = {
            "label": "OW_1",
            "size": 28,
            "master_subnet": self.master_subnet,
            "number_of_ips": 2,
            "number_of_subnets": 2,
            "type": (
                "openwisp_controller.subnet_division.rule_types."
                "vpn.VpnSubnetDivisionRuleType"
            ),
            "organization": self.org,
        }

        with self.subTest("Test valid parameters"):
            options = default_options.copy()
            rule = SubnetDivisionRule(**options)
            rule.full_clean()
            self.assertEqual(str(rule), options["label"])

        with self.subTest("Test label"):
            options = default_options.copy()
            options["label"] = "OW_10.0.0.0/16"
            rule = SubnetDivisionRule(**options)
            with self.assertRaises(ValidationError) as error:
                rule.full_clean()
            self.assertDictEqual(
                error.exception.message_dict,
                {
                    "label": [
                        "Only alphanumeric characters and underscores are allowed."
                    ]
                },
            )

        with self.subTest("Test rule size exceeds size of master_subnet"):
            options = default_options.copy()
            options["size"] = 8
            rule = SubnetDivisionRule(**options)
            with self.assertRaises(ValidationError) as context_manager:
                rule.full_clean()
            expected_message_dict = {
                "size": ["Master subnet cannot accommodate subnets of size /8"]
            }
            self.assertDictEqual(
                context_manager.exception.message_dict, expected_message_dict
            )

        with self.subTest("Test rule does not provision any subnet"):
            options = default_options.copy()
            options["number_of_subnets"] = 0
            rule = SubnetDivisionRule(**options)
            with self.assertRaises(ValidationError) as context_manager:
                rule.full_clean()
            expected_message_dict = {
                "number_of_subnets": [
                    "Ensure this value is greater than or equal to 1."
                ]
            }
            self.assertDictEqual(
                context_manager.exception.message_dict, expected_message_dict
            )

        with self.subTest("Test rule does not provision any IP"):
            options = default_options.copy()
            options["number_of_ips"] = 0
            rule = SubnetDivisionRule(**options)
            with self.assertRaises(ValidationError) as context_manager:
                rule.full_clean()
            expected_message_dict = {
                "number_of_ips": ["Ensure this value is greater than or equal to 1."]
            }
            self.assertDictEqual(
                context_manager.exception.message_dict, expected_message_dict
            )

        with self.subTest("Test rule size is illegal"):
            options = default_options.copy()
            options["size"] = 33
            rule = SubnetDivisionRule(**options)
            with self.assertRaises(ValidationError) as context_manager:
                rule.full_clean()
            expected_message_dict = {
                "size": ["Master subnet cannot accommodate subnets of size /33"]
            }
            self.assertDictEqual(
                context_manager.exception.message_dict, expected_message_dict
            )

        with self.subTest("Test master_subnet cannot accommodate number_of_subnets"):
            options = default_options.copy()
            options["number_of_subnets"] = 99999999
            rule = SubnetDivisionRule(**options)
            with self.assertRaises(ValidationError) as context_manager:
                rule.full_clean()
            expected_message_dict = {
                "number_of_subnets": [
                    "The master subnet is too small to acommodate "
                    'the requested "number of subnets" plus the '
                    "reserved subnet, please increase the size of "
                    "the master subnet or decrease the "
                    '"size of subnets" field.'
                ]
            }
            self.assertDictEqual(
                context_manager.exception.message_dict, expected_message_dict
            )

        with self.subTest("Test generated subnets cannot accommodate number_of_ips"):
            options = default_options.copy()
            options["number_of_ips"] = 99999999
            rule = SubnetDivisionRule(**options)
            with self.assertRaises(ValidationError) as context_manager:
                rule.full_clean()
            expected_message_dict = {
                "number_of_ips": [
                    "Generated subnets of size /28 cannot accommodate 99999999 "
                    "IP Addresses."
                ]
            }
            self.assertDictEqual(
                context_manager.exception.message_dict, expected_message_dict
            )

        with self.subTest("Test updating existing subnet division rule"):
            rule = SubnetDivisionRule(**default_options.copy())
            rule.full_clean()
            rule.save()

            # Test changing size of provisioned subnets
            with self.assertRaises(ValidationError) as error:
                rule.size = 26
                rule.full_clean()
            self.assertDictEqual(
                error.exception.message_dict,
                {"size": ["Subnet size cannot be changed"]},
            )

            # Test decreasing number_of_ips
            with self.assertRaises(ValidationError) as error:
                rule.size = 28
                rule.number_of_ips = 1
                rule.full_clean()
            self.assertDictEqual(
                error.exception.message_dict,
                {"number_of_ips": ["Number of IPs cannot be decreased"]},
            )

            # Test changing number of subnets
            with self.assertRaises(ValidationError) as error:
                rule.number_of_ips = 2
                rule.number_of_subnets = 3
                rule.full_clean()
            self.assertDictEqual(
                error.exception.message_dict,
                {"number_of_subnets": ["Number of Subnets cannot be changed"]},
            )

        with self.subTest("Test multitenancy"):
            org1 = self._get_org()
            org2 = self._create_org(name="org2")
            master_subnet = self._create_subnet(
                subnet="192.168.0.0/16", organization=org1
            )
            with self.assertRaises(ValidationError) as error:
                rule = self._get_vpn_subdivision_rule(
                    organization=org2, master_subnet=master_subnet
                )
            self.assertDictEqual(
                error.exception.message_dict,
                {"organization": ["Organization should be same as the subnet"]},
            )

    def test_slash_32_rule_ipv4(self):
        rule = self._get_vpn_subdivision_rule(
            size=32, number_of_ips=1, number_of_subnets=1
        )
        self.config.templates.add(self.template)
        rule.subnetdivisionindex_set.count()
        index_queryset = rule.subnetdivisionindex_set.filter(
            config_id=self.config.id, subnet_id__isnull=False, ip_id__isnull=False
        )
        self.assertEqual(index_queryset.count(), 1)
        index = index_queryset.first()
        self.assertEqual(str(index.subnet.subnet), "10.0.0.1/32")
        self.assertEqual(index.ip.ip_address, "10.0.0.1")

    def test_slash_32_rule_ipv4_error(self):
        master_ipv4 = self._get_master_subnet(subnet="192.168.1.1/32")
        self.vpn_server.subnet = master_ipv4
        self.vpn_server.save()
        try:
            self._get_vpn_subdivision_rule(
                size=32, number_of_ips=1, number_of_subnets=1, master_subnet=master_ipv4
            )
        except ValidationError as e:
            self.assertIn("number_of_subnets", e.message_dict)
            self.assertIn(
                "The master subnet is too small to acommodate",
                e.message_dict["number_of_subnets"][0],
            )
        else:
            self.fail("Expected error not raised")

    def test_slash_128_rule_ipv6(self):
        master_ipv6 = self._get_master_subnet(subnet="fd12:3456:7890::/48")
        self.vpn_server.subnet = master_ipv6
        self.vpn_server.save()
        rule = self._get_vpn_subdivision_rule(
            size=128, number_of_ips=1, number_of_subnets=1, master_subnet=master_ipv6
        )
        self.config.templates.add(self.template)
        index_queryset = rule.subnetdivisionindex_set.filter(
            config_id=self.config.id, subnet_id__isnull=False, ip_id__isnull=False
        )
        self.assertEqual(index_queryset.count(), 1)
        index = index_queryset.first()
        self.assertEqual(str(index.subnet.subnet), "fd12:3456:7890::1/128")
        self.assertEqual(index.ip.ip_address, "fd12:3456:7890::1")

    def test_slash_128_rule_ipv6_error(self):
        master_ipv6 = self._get_master_subnet(subnet="fd12:3456:7890::/128")
        self.vpn_server.subnet = master_ipv6
        self.vpn_server.save()
        try:
            self._get_vpn_subdivision_rule(
                size=128,
                number_of_ips=1,
                number_of_subnets=1,
                master_subnet=master_ipv6,
            )
        except ValidationError as e:
            self.assertIn("number_of_subnets", e.message_dict)
            self.assertIn(
                "The master subnet is too small to acommodate",
                e.message_dict["number_of_subnets"][0],
            )
        else:
            self.fail("Expected error not raised")

    def test_rule_label_updated(self):
        new_rule_label = "TSDR"
        rule = self._get_vpn_subdivision_rule(label="VPN_OW")
        self.config.templates.add(self.template)
        index_queryset = rule.subnetdivisionindex_set.filter(config_id=self.config.id)
        subnet_queryset = self.subnet_query.filter(
            id__in=index_queryset.filter(
                ip__isnull=True, subnet__isnull=False
            ).values_list("subnet_id", flat=True)
        )
        index_count = index_queryset.count()
        subnet_count = subnet_queryset.count()
        rule.label = new_rule_label
        rule.save()
        rule.refresh_from_db()

        self.assertEqual(rule.label, new_rule_label)

        # Assert keywords of SubnetDivisionIndex are updated
        new_index_count = index_queryset.filter(
            keyword__startswith=new_rule_label,
        ).count()
        self.assertEqual(index_count, new_index_count)

        # Verify context of config
        context = get_subnet_division_config_context(config=self.config)
        self.assertIn(f"{rule.label}_prefixlen", context)
        for subnet_id in range(1, rule.number_of_subnets + 1):
            self.assertIn(f"{rule.label}_subnet{subnet_id}", context)
            for ip_id in range(1, rule.number_of_ips + 1):
                self.assertIn(f"{rule.label}_subnet{subnet_id}_ip{ip_id}", context)

        # Assert name and description of Subnet are updated
        new_subnet_count = subnet_queryset.filter(
            name__startswith=new_rule_label,
            description__contains=new_rule_label,
        ).count()
        self.assertEqual(subnet_count, new_subnet_count)

    def test_number_of_ips_updated(self):
        rule = self._get_vpn_subdivision_rule()
        self.config.templates.add(self.template)
        index_queryset = rule.subnetdivisionindex_set.filter(
            config_id=self.config.id, subnet_id__isnull=False, ip_id__isnull=False
        )

        # Check if nothing changes
        rule.save()
        rule.refresh_from_db()
        self.assertEqual(
            index_queryset.count(), rule.number_of_ips * rule.number_of_subnets
        )

        new_number_of_ips = rule.number_of_ips + 2
        rule.number_of_ips = new_number_of_ips
        rule.save()
        rule.refresh_from_db()

        self.assertEqual(rule.number_of_ips, new_number_of_ips)
        self.assertEqual(
            index_queryset.count(), new_number_of_ips * rule.number_of_subnets
        )

    def test_rule_deleted(self):
        rule = self._get_vpn_subdivision_rule()
        self.config.templates.add(self.template)
        subnet_query = self.subnet_query.exclude(id=self.master_subnet.id).filter(
            organization=rule.organization
        )
        ip_query = self.ip_query
        index_query = rule.subnetdivisionindex_set

        self.assertEqual(subnet_query.count(), rule.number_of_subnets)
        self.assertEqual(ip_query.count(), rule.number_of_subnets * rule.number_of_ips)
        self.assertEqual(
            index_query.count(),
            # Keywords for subnets + Keywords for IPs
            rule.number_of_subnets + (rule.number_of_subnets * rule.number_of_ips),
        )

        rule.delete()

        self.assertEqual(subnet_query.count(), 0)
        self.assertEqual(ip_query.count(), 0)
        self.assertEqual(SubnetDivisionIndex.objects.count(), 0)

    def test_vpnclient_deleted(self):
        rule = self._get_vpn_subdivision_rule()
        self.config.templates.add(self.template)
        subnet_query = self.subnet_query.filter(organization_id=self.org.id).exclude(
            id=self.master_subnet.id
        )

        self.config.templates.add(self.template)

        self.assertEqual(
            subnet_query.count(),
            rule.number_of_subnets,
        )
        # 1 IP is automatically assigned to VPN server and client each,
        # hence add two in below assertion
        self.assertEqual(
            self.ip_query.count(), (rule.number_of_subnets * rule.number_of_ips)
        )

        self.config.templates.remove(self.template)
        self.assertEqual(
            subnet_query.count(),
            0,
        )
        self.assertEqual(self.ip_query.count(), 0)

    def test_multiple_vpnclient_delete(self):
        """
        When a VpnClient object is deleted, it should only delete
        the related provisioned subnets.
        """
        rule = self._get_vpn_subdivision_rule()
        self.config.templates.add(self.template)
        subnet_query = self.subnet_query.filter(organization_id=self.org.id).exclude(
            id=self.master_subnet.id
        )
        self.config.templates.add(self.template)
        self.assertEqual(
            subnet_query.count(),
            rule.number_of_subnets,
        )
        self.assertEqual(
            self.ip_query.count(), (rule.number_of_subnets * rule.number_of_ips)
        )

        # Create another VPN and VPN template and add this
        # template to the Config object
        vpn2_subnet = self._create_subnet(subnet="172.18.0.0/24")
        subnet_query = subnet_query.exclude(id=vpn2_subnet.id)
        vpn_server2 = self._create_wireguard_vpn(
            name="wg1",
            subnet=vpn2_subnet,
            organization=self.org,
        )
        ip_query = self.ip_query.exclude(id=vpn_server2.ip_id)
        vpn2_template = self._create_template(
            name="vpn2-test", type="vpn", vpn=vpn_server2, organization=self.org
        )
        self.config.templates.add(vpn2_template)

        # Number of subnets should remain same
        self.assertEqual(
            subnet_query.count(),
            rule.number_of_subnets,
        )
        # Number of IPs should increase by one:
        # 1 IP for the VpnClient (auto_ip)
        self.assertEqual(
            ip_query.count(), (rule.number_of_subnets * rule.number_of_ips) + 1
        )

        # Remove the template for the second VPN.
        # Number of subnets would return to the original numbers
        # Number of IPs would stay increased by 1
        self.config.templates.remove(vpn2_template)
        self.assertEqual(
            subnet_query.count(),
            rule.number_of_subnets,
        )
        self.assertEqual(
            ip_query.count(), (rule.number_of_subnets * rule.number_of_ips)
        )

    @patch("openwisp_controller.subnet_division.rule_types.base.logger.info")
    def test_subnets_exhausted(self, mocked_logger, *args):
        subnet = self._get_master_subnet(
            "10.0.0.0/29", master_subnet=self.master_subnet
        )
        # The master subnet can acommodate
        # this rule only once:
        # A /29 has 4 /31 slots available
        # Minus the reserved subnet = 3
        # Each run will eat 2 slots.
        # Hence we expect this to run fine the
        # first time but fail the second time.
        self._get_vpn_subdivision_rule(
            master_subnet=subnet,
            size=31,
            number_of_ips=2,
            number_of_subnets=2,
        )
        # A user is required to verify notification is created
        self._get_admin()
        self.vpn_server.subnet = subnet
        self.vpn_server.save()
        self.config.templates.add(self.template)

        config2 = self._create_config(
            device=self._create_device(mac_address="00:11:22:33:44:66")
        )
        config2.templates.add(self.template)
        mocked_logger.assert_called_with(
            f"Cannot create more subnets of {subnet}",
        )
        notification = Notification.objects.first()
        self.assertEqual(notification.level, "error")
        self.assertEqual(notification.type, "generic_message")
        self.assertEqual(notification.target, config2.device)
        self.assertEqual(notification.action_object, subnet)
        self.assertEqual(
            notification.message,
            (
                "<p>Failed to provision subnets for "
                '<a href="https://example.com{device_path}">'
                "{device_name}</a></p>"
            ).format(
                device_path=reverse(
                    f"admin:{self.config_label}_device_change", args=[config2.device_id]
                ),
                device_name=config2.device.name,
            ),
        )
        self.assertEqual(
            notification.rendered_description,
            (
                '<p>The <a href="https://example.com{subnet_path}">'
                "{subnet_name}</a> subnet has run out of space.</p>"
            ).format(
                subnet_path=reverse(
                    f"admin:{self.ipam_label}_subnet_change", args=[subnet.id]
                ),
                subnet_name=subnet,
            ),
        )

    def test_vpn_subnet_none(self):
        self.vpn_server.subnet = None
        self.vpn_server.save()

        rule = self._get_vpn_subdivision_rule()

        self.assertEqual(rule.subnetdivisionindex_set.count(), 0)
        self.assertEqual(self.subnet_query.exclude(id=self.master_subnet.id).count(), 0)
        self.assertEqual(self.ip_query.count(), 0)

    def test_vpn_subnet_no_rule(self):
        # Tests the scenario where a SubDivisionRule does not exist
        # for subnet of the VPN Server.
        self.config.templates.add(self.template)

    def test_subnet_already_provisioned(self):
        rule = self._get_vpn_subdivision_rule()
        index_count = (
            rule.number_of_subnets + rule.number_of_subnets * rule.number_of_ips
        )
        self.config.templates.add(self.template)
        self.assertEqual(
            self.config.subnetdivisionindex_set.count(),
            index_count,
        )
        vpn_client = VpnClient.objects.first()
        vpn_client.save()
        self.assertEqual(
            self.config.subnetdivisionindex_set.count(),
            index_count,
        )

    def test_shareable_vpn_vpnclient_subnet(self):
        self.vpn_server.organization = None
        self.vpn_server.save()

        self.template.organization = None
        self.template.save()

        self.master_subnet.organization = None
        self.master_subnet.save()

        rule = self._get_vpn_subdivision_rule()
        self.config.templates.add(self.template)

        # Following query asserts that subnet created belongs to the
        # organization of the related config.device
        subnet_query = self.subnet_query.filter(
            organization_id=self.org.id, master_subnet_id=self.master_subnet.id
        ).exclude(id=self.master_subnet.id)

        self.assertEqual(subnet_query.count(), rule.number_of_subnets)

    def test_sharable_vpn_vpnclient_subnet_multiple_rules(self):
        self.master_subnet.organization = None
        self.master_subnet.save()

        vpn_server = self._create_wireguard_vpn(
            name="vpn-server", subnet=self.master_subnet
        )

        template = self._create_template(name="vpn-client", type="vpn", vpn=vpn_server)

        org1 = self._create_org(name="org1")
        org2 = self._create_org(name="org2")

        rule1 = self._get_vpn_subdivision_rule(organization=org1)
        rule2 = self._get_vpn_subdivision_rule(organization=org2)

        config1 = self._create_config(organization=org1)
        config2 = self._create_config(organization=org2)

        config1.templates.add(template)
        config2.templates.add(template)

        self.assertEqual(
            self.subnet_query.exclude(id=self.master_subnet.id).count(),
            rule1.number_of_subnets + rule2.number_of_subnets,
        )
        config1_subnets = config1.subnetdivisionindex_set.filter(
            ip__isnull=True, subnet__isnull=False
        ).values_list("subnet__subnet", flat=True)
        config2_subnets = config2.subnetdivisionindex_set.filter(
            ip__isnull=True, subnet__isnull=False
        ).values_list("subnet__subnet", flat=True)
        self.assertNotIn(config1_subnets.first(), config2_subnets)
        self.assertNotIn(config1_subnets.last(), config2_subnets)

    def test_device_deleted(self):
        rule = self._get_vpn_subdivision_rule()
        subnet_query = self.subnet_query.filter(organization_id=self.org.id).exclude(
            id=self.master_subnet.id
        )
        self.config.templates.add(self.template)
        self.assertEqual(
            subnet_query.count(),
            rule.number_of_subnets,
        )

        self.config.device.delete(check_deactivated=False)
        self.assertEqual(
            subnet_query.count(),
            0,
        )

    def test_reserved_subnet(self):
        # An IP is already provisioned
        ip = self.master_subnet.request_ip()

        rule = self._get_vpn_subdivision_rule()
        subnet_query = Subnet.objects.exclude(id=self.master_subnet.id)
        self.config.templates.add(self.template)

        # Check reserved subnet is created
        self.assertEqual(
            subnet_query.filter(
                name__contains="Reserved Subnet", subnet=f"10.0.0.0/{rule.size}"
            ).count(),
            1,
        )
        # Check 10.0.0.1 is not provisioned again
        self.assertEqual(SubnetDivisionIndex.objects.filter(ip_id=ip.id).count(), 0)

    def test_device_subnet_division_rule(self):
        self.config.delete()
        rule = self._get_device_subdivision_rule()
        OrganizationConfigSettings.objects.create(
            organization=self.org, shared_secret="shared_secret"
        )
        subnet_query = self.subnet_query.filter(organization_id=self.org.id).exclude(
            id=self.master_subnet.id
        )
        self.assertEqual(subnet_query.count(), 0)

        # Register device
        options = {
            "hardware_id": "1234",
            "secret": "shared_secret",
            "name": "FF:FF:FF:FF:FF:FF",
            "mac_address": "FF:FF:FF:FF:FF:FF",
            "backend": "netjsonconfig.OpenWrt",
        }
        response = self.client.post(reverse("controller:device_register"), options)
        self.assertEqual(response.status_code, 201)

        # Verify generated subnets and IP addresses match expectations
        self.assertEqual(
            subnet_query.count(),
            rule.number_of_subnets,
        )
        self.assertEqual(
            self.ip_query.count(), (rule.number_of_subnets * rule.number_of_ips)
        )
        subnets = subnet_query.order_by("created")
        subnet1 = subnets[0]
        subnet2 = subnets[1]
        self.assertEqual(str(subnet1.subnet), "10.0.0.16/28")
        self.assertEqual(str(subnet2.subnet), "10.0.0.32/28")
        self.assertEqual(subnet1.ipaddress_set.count(), 2)
        self.assertEqual(subnet2.ipaddress_set.count(), 2)
        subnet1_ips = list(subnet1.ipaddress_set.order_by("created").all())
        with self.subTest("Check IP addresses of subnet1"):
            self.assertEqual(str(subnet1_ips[0].ip_address), "10.0.0.17")
            self.assertEqual(str(subnet1_ips[1].ip_address), "10.0.0.18")
        subnet2_ips = list(subnet2.ipaddress_set.order_by("created").all())
        with self.subTest("Check IP addresses of subnet2"):
            self.assertEqual(str(subnet2_ips[0].ip_address), "10.0.0.33")
            self.assertEqual(str(subnet2_ips[1].ip_address), "10.0.0.34")

        # Verify context of config
        device = Device.objects.get(mac_address="FF:FF:FF:FF:FF:FF")
        context = get_subnet_division_config_context(device.config)
        self.assertIn(f"{rule.label}_prefixlen", context)
        for subnet_id in range(1, rule.number_of_subnets + 1):
            self.assertIn(f"{rule.label}_subnet{subnet_id}", context)
            for ip_id in range(1, rule.number_of_ips + 1):
                self.assertIn(f"{rule.label}_subnet{subnet_id}_ip{ip_id}", context)

        # Verify working of delete handler
        device.delete(check_deactivated=False)
        self.assertEqual(
            subnet_query.count(),
            0,
        )
        self.assertEqual(self.ip_query.count(), 0)

    def test_device_rule_use_entire_subnet(self):
        self.config.delete()
        rule = self._get_device_subdivision_rule(size=29, number_of_ips=8)
        OrganizationConfigSettings.objects.create(
            organization=self.org, shared_secret="shared_secret"
        )
        subnet_query = self.subnet_query.filter(organization_id=self.org.id).exclude(
            id=self.master_subnet.id
        )
        self.assertEqual(subnet_query.count(), 0)

        # Register device
        options = {
            "hardware_id": "1234",
            "secret": "shared_secret",
            "name": "FF:FF:FF:FF:FF:FF",
            "mac_address": "FF:FF:FF:FF:FF:FF",
            "backend": "netjsonconfig.OpenWrt",
        }
        response = self.client.post(reverse("controller:device_register"), options)
        self.assertEqual(response.status_code, 201)

        # Verify generated subnets and IP addresses match expectations
        self.assertEqual(
            subnet_query.count(),
            rule.number_of_subnets,
        )
        self.assertEqual(
            self.ip_query.count(), (rule.number_of_subnets * rule.number_of_ips)
        )
        subnets = subnet_query.order_by("created")
        subnet1 = subnets[0]
        subnet2 = subnets[1]
        self.assertEqual(str(subnet1.subnet), "10.0.0.8/29")
        self.assertEqual(str(subnet2.subnet), "10.0.0.16/29")
        self.assertEqual(subnet1.ipaddress_set.count(), 8)
        self.assertEqual(subnet2.ipaddress_set.count(), 8)

        number = 8
        for subnet in [subnet1, subnet2]:
            for ip in subnet.ipaddress_set.order_by("created").all():
                expected_ip = f"10.0.0.{number}"
                with self.subTest(f"Expect IP address: {expected_ip}"):
                    self.assertEqual(str(ip.ip_address), expected_ip)
                number += 1

        # Verify context of config
        device = Device.objects.get(mac_address="FF:FF:FF:FF:FF:FF")
        context = get_subnet_division_config_context(device.config)
        self.assertIn(f"{rule.label}_prefixlen", context)
        for subnet_id in range(1, rule.number_of_subnets + 1):
            self.assertIn(f"{rule.label}_subnet{subnet_id}", context)
            for ip_id in range(1, rule.number_of_ips + 1):
                self.assertIn(f"{rule.label}_subnet{subnet_id}_ip{ip_id}", context)

        # Verify working of delete handler
        device.delete(check_deactivated=False)
        self.assertEqual(
            subnet_query.count(),
            0,
        )
        self.assertEqual(self.ip_query.count(), 0)

    def test_device_subnet_division_rule_existing_devices(self):
        subnet_query = self.subnet_query.filter(organization_id=self.org.id).exclude(
            id=self.master_subnet.id
        )
        self.assertEqual(subnet_query.count(), 0)
        rule = self._get_device_subdivision_rule()
        self.assertEqual(
            subnet_query.count(),
            rule.number_of_subnets,
        )
        self.assertEqual(
            self.ip_query.count(), (rule.number_of_subnets * rule.number_of_ips)
        )

    def test_vpn_subnet_division_rule_existing_devices(self):
        subnet_query = self.subnet_query.filter(organization_id=self.org.id).exclude(
            id=self.master_subnet.id
        )
        self.config.templates.add(self.template)
        self.assertEqual(subnet_query.count(), 0)
        rule = self._get_vpn_subdivision_rule()
        self.assertEqual(
            subnet_query.count(),
            rule.number_of_subnets,
        )
        self.assertEqual(
            self.ip_query.count(), (rule.number_of_subnets * rule.number_of_ips)
        )

    def test_vpn_subnet_division_rule_existing_devices_different_orgs(self):
        self.master_subnet.organization = None
        self.master_subnet.save()
        vpn_server = self._create_wireguard_vpn(
            name="vpn-server", subnet=self.master_subnet
        )
        template = self._create_template(name="vpn-client", type="vpn", vpn=vpn_server)
        org1 = self._create_org(name="org1")
        org2 = self._create_org(name="org2")
        config1 = self._create_config(organization=org1)
        config2 = self._create_config(organization=org2)

        config1.templates.add(template)
        config2.templates.add(template)

        rule1 = self._get_vpn_subdivision_rule(organization=org1)
        rule2 = self._get_vpn_subdivision_rule(organization=org2)

        self.assertEqual(
            self.subnet_query.exclude(id=self.master_subnet.id).count(),
            rule1.number_of_subnets + rule2.number_of_subnets,
        )
        config1_subnets = config1.subnetdivisionindex_set.filter(
            ip__isnull=True, subnet__isnull=False
        ).values_list("subnet__subnet", flat=True)
        config2_subnets = config2.subnetdivisionindex_set.filter(
            ip__isnull=True, subnet__isnull=False
        ).values_list("subnet__subnet", flat=True)
        self.assertNotIn(config1_subnets.first(), config2_subnets)
        self.assertNotIn(config1_subnets.last(), config2_subnets)

    def test_backend_class_property(self):
        rule = self._get_vpn_subdivision_rule()
        self.assertEqual(rule.rule_class, VpnSubnetDivisionRuleType)

    def test_subnet_ips_provisioned_signal(self):
        rule = self._get_vpn_subdivision_rule()
        with catch_signal(subnet_provisioned) as handler:
            self.config.templates.add(self.template)
            handler.assert_called_once()
        subnet_query = self.subnet_query.filter(organization_id=self.org.id).exclude(
            id=self.master_subnet.id
        )
        self.assertEqual(
            subnet_query.count(),
            rule.number_of_subnets,
        )

    def test_vpn_rule_assigns_vpnclient_ip(self):
        rule = self._get_vpn_subdivision_rule()
        subnet_query = self.subnet_query.filter(organization_id=self.org.id).exclude(
            id=self.master_subnet.id
        )
        self.config.templates.add(self.template)
        expected_assigned_ip = self.config.subnetdivisionindex_set.get(
            keyword=f"{rule.label}_subnet1_ip1"
        ).ip
        vpn_client = self.config.vpnclient_set.first()
        self.assertEqual(vpn_client.ip, expected_assigned_ip)
        self.assertEqual(
            subnet_query.count(),
            rule.number_of_subnets,
        )

    def test_subnet_division_index_validation(self):
        rule = self._get_vpn_subdivision_rule()
        index = SubnetDivisionIndex(rule=rule, keyword="test")
        subnet = Subnet.objects.create(subnet="10.0.0.0/16")
        ip = IpAddress.objects.create(subnet=subnet, ip_address="10.0.0.1")

        with self.subTest("ip, subnet and config are missing"):
            index.full_clean()

        with self.subTest("subnet and config are missing"):
            index.ip = ip
            index.full_clean()

        with self.subTest("config is missing"):
            index.subnet = subnet
            index.full_clean()

        with self.subTest("All related fields are present"):
            index.config = self.config
            index.full_clean()

    def test_single_subnet_multiple_vpn_rule(self):
        rule1 = self._get_vpn_subdivision_rule()
        rule2 = self._get_vpn_subdivision_rule(label="VPN")
        self.config.templates.add(self.template)
        self.assertEqual(
            self.subnet_query.exclude(id=self.master_subnet.id).count(),
            rule1.number_of_subnets + rule2.number_of_subnets,
        )
        rule2.delete()
        self.assertEqual(
            self.subnet_query.exclude(id=self.master_subnet.id).count(),
            rule1.number_of_subnets,
        )

    def test_single_subnet_multiple_device_rule(self):
        rule1 = self._get_device_subdivision_rule(label="LAN1")
        rule2 = self._get_device_subdivision_rule(label="LAN2")
        self.assertEqual(
            self.subnet_query.exclude(id=self.master_subnet.id).count(),
            rule1.number_of_subnets + rule2.number_of_subnets,
        )
        rule2.delete()
        self.assertEqual(
            self.subnet_query.exclude(id=self.master_subnet.id).count(),
            rule1.number_of_subnets,
        )

    def test_single_subnet_vpn_device_rule(self):
        device_rule = self._get_device_subdivision_rule(label="LAN")
        vpn_rule = self._get_vpn_subdivision_rule(label="VPN")
        self.config.templates.add(self.template)
        self.assertEqual(
            self.subnet_query.exclude(id=self.master_subnet.id).count(),
            device_rule.number_of_subnets + vpn_rule.number_of_subnets,
        )
        self.config.templates.remove(self.template)
        self.assertEqual(
            self.subnet_query.exclude(id=self.master_subnet.id).count(),
            device_rule.number_of_subnets,
        )

    def test_invalid_master_subnet(self):
        # Instantiate a subnet without setting its 'subnet' attribute
        invalid_subnet = Subnet(name="Invalid Subnet")
        rule = SubnetDivisionRule(
            type="openwisp_controller.subnet_division.rule_types.vpn."
            "VpnSubnetDivisionRuleType",
            label="TEST",
            size=28,
            number_of_subnets=2,
            number_of_ips=2,
            organization=self.org,
            master_subnet=invalid_subnet,  # Invalid master_subnet
        )
        with self.assertRaises(ValidationError) as cm:
            rule.full_clean()
        e = cm.exception
        self.assertIn(
            "Invalid master subnet.",
            e.message_dict.get("master_subnet", []),
        )


class TestOpenVPNSubnetDivisionRule(
    SubnetDivisionTestMixin,
    BaseSubnetDivisionRule,
    TestVpnX509Mixin,
    TransactionTestCase,
):
    def setUp(self):
        self.org = self._get_org()
        self.master_subnet = self._get_master_subnet()
        self.vpn_server = self._create_vpn(
            subnet=self.master_subnet,
            organization=self.org,
        )
        self.template = self._create_template(
            name="vpn-test", type="vpn", vpn=self.vpn_server, organization=self.org
        )
        self.config = self._create_config(organization=self.org)


class TestCeleryTasks(TestCase):
    def test_subnet_division_rule_does_not_exist(self):
        id = uuid.uuid4()
        log_message = (
            "Failed to {action} Subnet Division Rule with id: "
            f'"{id}", reason: SubnetDivisionRule matching query does not exist.'
        )
        with patch("logging.Logger.warning") as mocked_logger:
            tasks.update_subnet_division_index.run(id)
            mocked_logger.assert_called_once_with(
                log_message.format(action="update indexes for")
            )

        with patch("logging.Logger.warning") as mocked_logger:
            tasks.update_subnet_name_description.run(id)
            mocked_logger.assert_called_once_with(
                log_message.format(action="update subnets related to")
            )

        with patch("logging.Logger.warning") as mocked_logger:
            tasks.provision_extra_ips.run(id, old_number_of_ips=0)
            mocked_logger.assert_called_once_with(
                log_message.format(action="provision extra IPs for")
            )

        with patch("logging.Logger.warning") as mocked_logger:
            tasks.provision_subnet_ip_for_existing_devices.run(id)
            mocked_logger.assert_called_once_with(
                log_message.format(action="provision IPs on existing devices for")
            )
