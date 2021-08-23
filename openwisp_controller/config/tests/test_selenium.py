from django.contrib.auth.models import Permission
from django.test import tag
from django.urls.base import reverse
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from swapper import load_model

from openwisp_users.tests.utils import TestOrganizationMixin

from ...tests.utils import MultitenantSeleniumTestCase, SeleniumTestCase
from .utils import CreateConfigTemplateMixin

Group = load_model('openwisp_users', 'Group')


@tag('selenium')
class TestDeviceAdmin(
    TestOrganizationMixin, CreateConfigTemplateMixin, SeleniumTestCase
):
    serialized_rollback = True

    def setUp(self):
        self.admin = self._create_admin(
            username=self.admin_username, password=self.admin_password
        )

    def test_create_new_device(self):
        required_template = self._create_template(name='Required', required=True)
        default_template = self._create_template(name='Default', default=True)
        org = self._get_org()
        self.login()
        self.open(reverse('admin:config_device_add'))
        self.web_driver.find_element_by_name('name').send_keys('11:22:33:44:55:66')
        self.web_driver.find_element_by_css_selector(
            'span[data-select2-id="1"]'
        ).click()
        self.web_driver.find_element_by_css_selector(
            'input.select2-search__field'
        ).send_keys(org.name)
        self.web_driver.find_element_by_class_name(
            'select2-results__option--highlighted'
        ).click()
        self.web_driver.find_element_by_name('mac_address').send_keys(
            '11:22:33:44:55:66'
        )
        self.web_driver.find_element_by_xpath(
            '//*[@id="config-group"]/fieldset/div[2]/a'
        ).click()

        try:
            WebDriverWait(self.web_driver, 2).until(
                EC.element_to_be_clickable(
                    (By.XPATH, f'//*[@value="{default_template.id}"]')
                )
            )
        except TimeoutException:
            self.fail('Default template clickable timed out')

        required_template_element = self.web_driver.find_element_by_xpath(
            f'//*[@value="{required_template.id}"]'
        )
        default_template_element = self.web_driver.find_element_by_xpath(
            f'//*[@value="{default_template.id}"]'
        )
        self.assertEqual(required_template_element.is_enabled(), False)
        self.assertEqual(required_template_element.is_selected(), True)
        self.assertEqual(default_template_element.is_enabled(), True)
        self.assertEqual(default_template_element.is_selected(), True)
        # Hide user tools because it covers the save button
        self.web_driver.execute_script(
            'document.querySelector("#ow-user-tools").style.display="none"'
        )
        self.web_driver.find_element_by_name('_save').click()
        self.assertEqual(
            self.web_driver.find_elements_by_class_name('success')[0].text,
            'The Device “11:22:33:44:55:66” was added successfully.',
        )

    def test_unsaved_changes(self):
        self.login()
        device = self._create_config(organization=self._get_org()).device
        self.open(reverse('admin:config_device_change', args=[device.id]))
        with self.subTest('Alert should not be displayed without any change'):
            self.web_driver.refresh()
            try:
                WebDriverWait(self.web_driver, 1).until(EC.alert_is_present())
            except TimeoutException:
                pass
            else:
                self.fail('Unsaved changes alert displayed without any change')

        with self.subTest('Alert should be displayed after making changes'):
            self.web_driver.find_element_by_name('name').send_keys('new.device.name')
            self.web_driver.refresh()
            try:
                WebDriverWait(self.web_driver, 1).until(EC.alert_is_present())
            except TimeoutException:
                self.fail('Timed out wating for unsaved changes alert')
            else:
                self.web_driver.switch_to_alert().accept()

    def test_multiple_organization_templates(self):
        shared_required_template = self._create_template(
            name='shared required', organization=None
        )

        org1 = self._create_org(name='org1', slug='org1')
        org1_required_template = self._create_template(
            name='org1 required', organization=org1, required=True
        )
        org1_default_template = self._create_template(
            name='org1 default', organization=org1, default=True
        )

        org2 = self._create_org(name='org2', slug='org2')
        org2_required_template = self._create_template(
            name='org2 required', organization=org2, required=True
        )
        org2_default_template = self._create_template(
            name='org2 default', organization=org2, default=True
        )

        org1_device = self._create_config(
            device=self._create_device(organization=org1)
        ).device

        self.login()
        self.open(
            reverse('admin:config_device_change', args=[org1_device.id])
            + '#config-group'
        )
        wait = WebDriverWait(self.web_driver, 2)
        # org2 templates should not be visible
        try:
            wait.until(
                EC.invisibility_of_element_located(
                    (By.XPATH, f'//*[@value="{org2_required_template.id}"]')
                )
            )
            wait.until(
                EC.invisibility_of_element_located(
                    (By.XPATH, f'//*[@value="{org2_default_template.id}"]')
                )
            )
        except (TimeoutException, StaleElementReferenceException):
            self.fail('Template belonging to other organization found')

        # org1 and shared templates should be visible
        wait.until(
            EC.visibility_of_any_elements_located(
                (By.XPATH, f'//*[@value="{org1_required_template.id}"]')
            )
        )
        wait.until(
            EC.visibility_of_any_elements_located(
                (By.XPATH, f'//*[@value="{org1_default_template.id}"]')
            )
        )
        wait.until(
            EC.visibility_of_any_elements_located(
                (By.XPATH, f'//*[@value="{shared_required_template.id}"]')
            )
        )

    def test_change_config_backend(self):
        device = self._create_config(organization=self._get_org()).device
        template = self._create_template()

        self.login()
        self.open(
            reverse('admin:config_device_change', args=[device.id]) + '#config-group'
        )
        self.web_driver.find_element_by_xpath(f'//*[@value="{template.id}"]')
        # Change config backed to
        config_backend_select = Select(
            self.web_driver.find_element_by_name('config-0-backend')
        )
        config_backend_select.select_by_visible_text('OpenWISP Firmware 1.x')
        try:
            WebDriverWait(self.web_driver, 1).until(
                EC.invisibility_of_element_located(
                    (By.XPATH, f'//*[@value="{template.id}"]')
                )
            )
        except TimeoutException:
            self.fail('Template for other config backend found')

    def test_template_context_variables(self):
        self._create_template(
            name='Template1', default_values={'vni': '1'}, required=True
        )
        self._create_template(
            name='Template2', default_values={'vni': '2'}, required=True
        )
        device = self._create_config(organization=self._get_org()).device
        self.login()
        self.open(
            reverse('admin:config_device_change', args=[device.id]) + '#config-group'
        )
        try:
            WebDriverWait(self.web_driver, 2).until(
                EC.text_to_be_present_in_element_value(
                    (
                        By.XPATH,
                        '//*[@id="flat-json-config-0-context"]/div[2]/div/div/input[1]',
                    ),
                    'vni',
                )
            )
        except TimeoutException:
            self.fail('Timed out wating for configuration variabled to get loaded')
        self.web_driver.find_element_by_xpath(
            '//*[@id="main-content"]/div[2]/a[3]'
        ).click()
        try:
            WebDriverWait(self.web_driver, 2).until(EC.alert_is_present())
        except TimeoutException:
            pass
        else:
            self.web_driver.switch_to_alert().accept()
            self.fail('Unsaved changes alert displayed without any change')


@tag('selenium')
class TestMultitenantAdmin(MultitenantSeleniumTestCase):
    app_label = 'config'
    serialized_rollback = True

    def test_vpn_multitenant_organization(self):
        group = Group.objects.get(name='Administrator')
        group.permissions.add(*Permission.objects.filter(codename__endswith='vpn'))
        url = reverse(f'admin:{self.app_label}_vpn_add')
        self._test_organization_field_multitenancy(url)

    def test_device_multitenant_organization(self):
        group = Group.objects.get(name='Administrator')
        group.permissions.add(*Permission.objects.filter(codename__endswith='device'))
        url = reverse(f'admin:{self.app_label}_device_add')
        self._test_organization_field_multitenancy(url)

    def test_template_multitenant_organization(self):
        group = Group.objects.get(name='Administrator')
        group.permissions.add(*Permission.objects.filter(codename__endswith='template'))
        url = reverse(f'admin:{self.app_label}_template_add')
        self._test_organization_field_multitenancy(url)

    def test_devicegroup_multitenant_organization(self):
        group = Group.objects.get(name='Administrator')
        group.permissions.add(
            *Permission.objects.filter(codename__endswith='devicegroup')
        )
        url = reverse(f'admin:{self.app_label}_devicegroup_add')
        self._test_organization_field_multitenancy(url)
