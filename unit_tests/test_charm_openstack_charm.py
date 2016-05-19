# Note that the unit_tests/__init__.py has the following lines to stop
# side effects from the imorts from charm helpers.

# mock out some charmhelpers libraries as they have apt install side effects
# sys.modules['charmhelpers.contrib.openstack.utils'] = mock.MagicMock()
# sys.modules['charmhelpers.contrib.network.ip'] = mock.MagicMock()

import mock

import utils

import charm.openstack.charm as chm

TEST_CONFIG = {'config': True}


class BaseOpenStackCharmTest(utils.BaseTestCase):

    @classmethod
    def setUpClass(cls):
        cls.patched_config = mock.patch.object(chm.hookenv, 'config')
        cls.patched_config_started = cls.patched_config.start()

    @classmethod
    def tearDownClass(cls):
        cls.patched_config.stop()
        cls.patched_config_started = None
        cls.patched_config = None

    def setUp(self, target_cls, test_config):
        super(BaseOpenStackCharmTest, self).setUp()
        # set up the return value on the mock before instantiating the class to
        # get the config into the class.config.
        chm.hookenv.config.return_value = test_config
        self.target = target_cls()

    def tearDown(self):
        self.target = None
        super(BaseOpenStackCharmTest, self).tearDown()

    def patch_target(self, attr, return_value=None, name=None, new=None):
        # uses BaseTestCase.patch_object() to patch targer.
        self.patch_object(self.target, attr, return_value, name, new)


class TestOpenStackCharm(BaseOpenStackCharmTest):
    # Note that this only tests the OpenStackCharm() class, which has not very
    # useful defaults for testing.  In order to test all the code without too
    # many mocks, a separate test dervied charm class is used below.

    def setUp(self):
        super(TestOpenStackCharm, self).setUp(chm.OpenStackCharm, TEST_CONFIG)

    def test__init__(self):
        # Note cls.setUpClass() creates an OpenStackCharm() instance
        self.assertEqual(chm.hookenv.config(), TEST_CONFIG)
        self.assertEqual(self.target.config, TEST_CONFIG)
        # Note that we assume NO release unless given one.
        self.assertEqual(self.target.release, None)

    def test_install(self):
        # only tests that the default set_state is called
        self.patch_target('set_state')
        self.patch_object(chm.charmhelpers.fetch,
                          'filter_installed_packages',
                          name='fip',
                          return_value=None)
        self.target.install()
        self.target.set_state.assert_called_once_with('charmname-installed')
        self.fip.assert_called_once_with([])

    def test_set_state(self):
        # tests that OpenStackCharm.set_state() calls set_state() global
        self.patch_object(chm.charms.reactive.bus, 'set_state')
        self.target.set_state('hello')
        self.set_state.assert_called_once_with('hello', None)
        self.set_state.reset_mock()
        self.target.set_state('hello', 'there')
        self.set_state.assert_called_once_with('hello', 'there')

    def test_remove_state(self):
        # tests that OpenStackCharm.remove_state() calls remove_state() global
        self.patch_object(chm.charms.reactive.bus, 'remove_state')
        self.target.remove_state('hello')
        self.remove_state.assert_called_once_with('hello')

    def test_configure_source(self):
        self.patch_object(chm.os_utils,
                          'configure_installation_source',
                          name='cis')
        self.patch_object(chm.charmhelpers.fetch, 'apt_update')
        self.patch_target('config', new={'openstack-origin': 'an-origin'})
        self.target.configure_source()
        self.cis.assert_called_once_with('an-origin')
        self.apt_update.assert_called_once_with(fatal=True)

    def test_region(self):
        self.patch_target('config', new={'region': 'a-region'})
        self.assertEqual(self.target.region, 'a-region')

    def test_restart_on_change(self):
        from collections import OrderedDict
        hashs = OrderedDict([
            ('path1', 100),
            ('path2', 200),
            ('path3', 300),
            ('path4', 400),
        ])
        self.target.restart_map = {
            'path1': ['s1'],
            'path2': ['s2'],
            'path3': ['s3'],
            'path4': ['s2', 's4'],
        }
        self.patch_object(chm.ch_host, 'path_hash')
        self.path_hash.side_effect = lambda x: hashs[x]
        self.patch_object(chm.ch_host, 'service_restart')
        # slightly awkard, in that we need to test a context manager
        with self.target.restart_on_change():
            # test with no restarts
            pass
        self.assertEqual(self.service_restart.call_count, 0)

        with self.target.restart_on_change():
            # test with path1 and path3 restarts
            for k in ['path1', 'path3']:
                hashs[k] += 1
        self.assertEqual(self.service_restart.call_count, 2)
        self.service_restart.assert_any_call('s1')
        self.service_restart.assert_any_call('s3')

        # test with path2 and path4 and that s2 only gets restarted once
        self.service_restart.reset_mock()
        with self.target.restart_on_change():
            for k in ['path2', 'path4']:
                hashs[k] += 1
        self.assertEqual(self.service_restart.call_count, 2)
        calls = [mock.call('s2'), mock.call('s4')]
        self.service_restart.assert_has_calls(calls)

    def test_restart_all(self):
        self.patch_object(chm.ch_host, 'service_restart')
        self.patch_target('services', new=['s1', 's2'])
        self.target.restart_all()
        self.assertEqual(self.service_restart.call_args_list,
                         [mock.call('s1'), mock.call('s2')])

    def test_db_sync(self):
        self.patch_object(chm.hookenv, 'leader_get')
        self.patch_object(chm.hookenv, 'leader_set')
        self.patch_object(chm, 'subprocess', name='subprocess')
        self.patch_target('restart_all')
        # first check with leader_get returning True
        self.leader_get.return_value = True
        self.target.db_sync()
        self.leader_get.assert_called_once_with(attribute='db-sync-done')
        self.subprocess.check_call.assert_not_called()
        self.leader_set.assert_not_called()
        self.restart_all.assert_not_called()
        # Now check with leader_get returning False
        self.leader_get.reset_mock()
        self.leader_get.return_value = False
        self.target.sync_cmd = ['a', 'cmd']
        self.target.db_sync()
        self.leader_get.assert_called_once_with(attribute='db-sync-done')
        self.subprocess.check_call.assert_called_once_with(['a', 'cmd'])
        self.leader_set.assert_called_once_with({'db-sync-done': True})
        self.restart_all.assert_called_once_with()


class MyAdapter(object):

    def __init__(self, interfaces):
        self.interfaces = interfaces


class MyOpenStackCharm(chm.OpenStackCharm):

    name = 'my-charm'
    packages = ['p1', 'p2', 'p3', 'package-to-filter']
    api_ports = {
        'service1': {
            chm.os_ip.PUBLIC: 1,
            chm.os_ip.INTERNAL: 2,
        },
        'service2': {
            chm.os_ip.PUBLIC: 3,
        },
        'my-default-service': {
            chm.os_ip.PUBLIC: 1234,
            chm.os_ip.ADMIN: 2468,
            chm.os_ip.INTERNAL: 3579,
        },
    }
    service_type = 'my-service-type'
    default_service = 'my-default-service'
    restart_map = {
        'path1': ['s1'],
        'path2': ['s2'],
        'path3': ['s3'],
        'path4': ['s2', 's4'],
    }
    sync_cmd = ['my-sync-cmd', 'param1']
    services = ['my-default-service', 'my-second-service']
    adapters_class = MyAdapter


class TestMyOpenStackCharm(BaseOpenStackCharmTest):

    def setUp(self):
        def make_open_stack_charm():
            return MyOpenStackCharm(['interface1', 'interface2'])

        super(TestMyOpenStackCharm, self).setUp(make_open_stack_charm,
                                                TEST_CONFIG)

    def test_install(self):
        # tests that the packages are filtered before installation
        self.patch_target('set_state')
        self.patch_object(chm.charmhelpers.fetch,
                          'filter_installed_packages',
                          return_value=None,
                          name='fip')
        self.fip.side_effect = lambda x: ['p1', 'p2']
        self.patch_object(chm.hookenv, 'status_set')
        self.patch_object(chm.hookenv, 'apt_install')
        self.target.install()
        self.target.set_state.assert_called_once_with('my-charm-installed')
        self.fip.assert_called_once_with(self.target.packages)
        self.status_set.assert_called_once_with('maintenance',
                                                'Installing packages')

    def test_api_port(self):
        self.assertEqual(self.target.api_port('service1'), 1)
        self.assertEqual(self.target.api_port('service1', chm.os_ip.PUBLIC), 1)
        self.assertEqual(self.target.api_port('service2'), 3)
        with self.assertRaises(KeyError):
            self.target.api_port('service3')
        with self.assertRaises(KeyError):
            self.target.api_port('service2', chm.os_ip.INTERNAL)

    def test_public_url(self):
        self.patch_object(chm.os_ip,
                          'canonical_url',
                          return_value='my-ip-address')
        self.assertEqual(self.target.public_url, 'my-ip-address:1234')
        self.canonical_url.assert_called_once_with(chm.os_ip.PUBLIC)

    def test_admin_url(self):
        self.patch_object(chm.os_ip,
                          'canonical_url',
                          return_value='my-ip-address')
        self.assertEqual(self.target.admin_url, 'my-ip-address:2468')
        self.canonical_url.assert_called_once_with(chm.os_ip.ADMIN)

    def test_internal_url(self):
        self.patch_object(chm.os_ip,
                          'canonical_url',
                          return_value='my-ip-address')
        self.assertEqual(self.target.internal_url, 'my-ip-address:3579')
        self.canonical_url.assert_called_once_with(chm.os_ip.INTERNAL)

    def test_render_all_configs(self):
        self.patch_target('render_configs')
        self.target.render_all_configs()
        self.assertEqual(self.render_configs.call_count, 1)
        args = self.render_configs.call_args_list[0][0][0]
        self.assertEqual(['path1', 'path2', 'path3', 'path4'],
                         sorted(args))

    def test_render_configs(self):
        # give us a way to check that the context manager was called.
        from contextlib import contextmanager
        d = [0]

        @contextmanager
        def fake_restart_on_change():
            d[0] += 1
            yield

        self.patch_target('restart_on_change', new=fake_restart_on_change)
        self.patch_object(chm.charmhelpers.core.templating, 'render')
        self.patch_object(chm.os_templating,
                          'get_loader',
                          return_value='my-loader')
        # self.patch_target('adapter_instance', new='my-adapter')
        self.target.render_configs(['path1'])
        self.assertEqual(d[0], 1)
        self.render.assert_called_once_with(
            source='path1',
            template_loader='my-loader',
            target='path1',
            context=mock.ANY)
        # assert the context was an MyAdapter instance.
        context = self.render.call_args_list[0][1]['context']
        assert isinstance(context, MyAdapter)
        self.assertEqual(context.interfaces, ['interface1', 'interface2'])