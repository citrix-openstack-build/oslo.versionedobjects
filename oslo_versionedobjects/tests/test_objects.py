#    Copyright 2013 IBM Corp.
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

import copy
import datetime
import logging
import six

import mock
from oslo_context import context
from oslo_serialization import jsonutils
from testtools import matchers

from oslo_versionedobjects import base
from oslo_versionedobjects import exception
from oslo_versionedobjects import fields
from oslo_versionedobjects import fixture
from oslo_versionedobjects import test


LOG = logging.getLogger(__name__)


def is_test_object(cls):
    """Return True if class is defined in the tests.

    :param cls: Class to inspect
    """
    return 'oslo_versionedobjects.tests' in cls.__module__


@base.VersionedObjectRegistry.register
class MyOwnedObject(base.VersionedObject):
    VERSION = '1.0'
    fields = {'baz': fields.Field(fields.Integer())}


@base.VersionedObjectRegistry.register
class MyObj(base.VersionedObject, base.VersionedObjectDictCompat):
    VERSION = '1.6'
    fields = {'foo': fields.Field(fields.Integer(), default=1),
              'bar': fields.Field(fields.String()),
              'missing': fields.Field(fields.String()),
              'readonly': fields.Field(fields.Integer(), read_only=True),
              'rel_object': fields.ObjectField('MyOwnedObject', nullable=True),
              'rel_objects': fields.ListOfObjectsField('MyOwnedObject',
                                                       nullable=True),
              }

    @staticmethod
    def _from_db_object(context, obj, db_obj):
        self = MyObj()
        self.foo = db_obj['foo']
        self.bar = db_obj['bar']
        self.missing = db_obj['missing']
        self.readonly = 1
        return self

    def obj_load_attr(self, attrname):
        setattr(self, attrname, 'loaded!')

    @base.remotable_classmethod
    def query(cls, context):
        obj = cls(context=context, foo=1, bar='bar')
        obj.obj_reset_changes()
        return obj

    @base.remotable
    def marco(self):
        return 'polo'

    @base.remotable
    def _update_test(self):
        project_id = getattr(context, 'tenant', None)
        if project_id is None:
            project_id = getattr(context, 'project_id', None)
        if project_id == 'alternate':
            self.bar = 'alternate-context'
        else:
            self.bar = 'updated'

    @base.remotable
    def save(self):
        self.obj_reset_changes()

    @base.remotable
    def refresh(self):
        self.foo = 321
        self.bar = 'refreshed'
        self.obj_reset_changes()

    @base.remotable
    def modify_save_modify(self):
        self.bar = 'meow'
        self.save()
        self.foo = 42
        self.rel_object = MyOwnedObject(baz=42)

    def obj_make_compatible(self, primitive, target_version):
        super(MyObj, self).obj_make_compatible(primitive, target_version)
        # NOTE(danms): Simulate an older version that had a different
        # format for the 'bar' attribute
        if target_version == '1.1' and 'bar' in primitive:
            primitive['bar'] = 'old%s' % primitive['bar']


@base.VersionedObjectRegistry.register
class MyComparableObj(MyObj, base.ComparableVersionedObject):
    pass


@base.VersionedObjectRegistry.register
class MyObjDiffVers(MyObj):
    VERSION = '1.5'

    @classmethod
    def obj_name(cls):
        return 'MyObj'


@base.VersionedObjectRegistry.register_if(False)
class MyObj2(base.VersionedObject):
    @classmethod
    def obj_name(cls):
        return 'MyObj'

    @base.remotable_classmethod
    def query(cls, *args, **kwargs):
        pass


class RandomMixInWithNoFields(object):
    """Used to test object inheritance using a mixin that has no fields."""
    pass


@base.VersionedObjectRegistry.register
class TestSubclassedObject(RandomMixInWithNoFields, MyObj):
    fields = {'new_field': fields.Field(fields.String())}


class TestRegistry(test.TestCase):
    def test_obj_tracking(self):

        @base.VersionedObjectRegistry.register
        class NewBaseClass(object):
            VERSION = '1.0'
            fields = {}

            @classmethod
            def obj_name(cls):
                return cls.__name__

        @base.VersionedObjectRegistry.register
        class Fake1TestObj1(NewBaseClass):
            @classmethod
            def obj_name(cls):
                return 'fake1'

        @base.VersionedObjectRegistry.register
        class Fake1TestObj2(Fake1TestObj1):
            pass

        @base.VersionedObjectRegistry.register
        class Fake1TestObj3(Fake1TestObj1):
            VERSION = '1.1'

        @base.VersionedObjectRegistry.register
        class Fake2TestObj1(NewBaseClass):
            @classmethod
            def obj_name(cls):
                return 'fake2'

        @base.VersionedObjectRegistry.register
        class Fake1TestObj4(Fake1TestObj3):
            VERSION = '1.2'

        @base.VersionedObjectRegistry.register
        class Fake2TestObj2(Fake2TestObj1):
            VERSION = '1.1'

        @base.VersionedObjectRegistry.register
        class Fake1TestObj5(Fake1TestObj1):
            VERSION = '1.1'

        @base.VersionedObjectRegistry.register_if(False)
        class ConditionalObj1(NewBaseClass):
            fields = {'foo': fields.IntegerField()}

        @base.VersionedObjectRegistry.register_if(True)
        class ConditionalObj2(NewBaseClass):
            fields = {'foo': fields.IntegerField()}

        # Newest versions first in the list. Duplicate versions take the
        # newest object.
        expected = {'fake1': [Fake1TestObj4, Fake1TestObj5, Fake1TestObj2],
                    'fake2': [Fake2TestObj2, Fake2TestObj1]}
        self.assertEqual(expected['fake1'],
                         base.VersionedObjectRegistry.obj_classes()['fake1'])
        self.assertEqual(expected['fake2'],
                         base.VersionedObjectRegistry.obj_classes()['fake2'])
        self.assertEqual(
            [],
            base.VersionedObjectRegistry.obj_classes()['ConditionalObj1'])
        self.assertTrue(hasattr(ConditionalObj1, 'foo'))
        self.assertEqual(
            [ConditionalObj2],
            base.VersionedObjectRegistry.obj_classes()['ConditionalObj2'])
        self.assertTrue(hasattr(ConditionalObj2, 'foo'))

    def test_field_checking(self):
        def create_class(field):
            @base.VersionedObjectRegistry.register
            class TestField(base.VersionedObject):
                VERSION = '1.5'
                fields = {'foo': field()}
            return TestField

        create_class(fields.DateTimeField)
        self.assertRaises(exception.ObjectFieldInvalid,
                          create_class, fields.DateTime)
        self.assertRaises(exception.ObjectFieldInvalid,
                          create_class, int)

    def test_registration_hook(self):
        class TestObject(base.VersionedObject):
            VERSION = '1.0'

        class TestObjectNewer(base.VersionedObject):
            VERSION = '1.1'

            @classmethod
            def obj_name(cls):
                return 'TestObject'

        registry = base.VersionedObjectRegistry()
        with mock.patch.object(registry, 'registration_hook') as mock_hook:
            registry._register_class(TestObject)
            mock_hook.assert_called_once_with(TestObject, 0)

        with mock.patch.object(registry, 'registration_hook') as mock_hook:
            registry._register_class(TestObjectNewer)
            mock_hook.assert_called_once_with(TestObjectNewer, 0)

    def test_subclassability(self):
        class MyRegistry(base.VersionedObjectRegistry):
            pass

        @MyRegistry.register
        class ObjectInSubclassedRegistry(object):
            fields = {}

            @classmethod
            def obj_name(cls):
                return cls.__name__

        self.assertIn('ObjectInSubclassedRegistry',
                      MyRegistry.obj_classes())
        self.assertIn('ObjectInSubclassedRegistry',
                      base.VersionedObjectRegistry.obj_classes())


class TestObjMakeList(test.TestCase):

    def test_obj_make_list(self):
        @base.VersionedObjectRegistry.register
        class MyList(base.ObjectListBase, base.VersionedObject):
            pass

        db_objs = [{'foo': 1, 'bar': 'baz', 'missing': 'banana'},
                   {'foo': 2, 'bar': 'bat', 'missing': 'apple'},
                   ]
        mylist = base.obj_make_list('ctxt', MyList(), MyObj, db_objs)
        self.assertEqual(2, len(mylist))
        self.assertEqual('ctxt', mylist._context)
        for index, item in enumerate(mylist):
            self.assertEqual(db_objs[index]['foo'], item.foo)
            self.assertEqual(db_objs[index]['bar'], item.bar)
            self.assertEqual(db_objs[index]['missing'], item.missing)


def compare_obj(test, obj, db_obj, subs=None, allow_missing=None,
                comparators=None):
    """Compare a VersionedObject and a dict-like database object.

    This automatically converts TZ-aware datetimes and iterates over
    the fields of the object.

    :param:test: The TestCase doing the comparison
    :param:obj: The VersionedObject to examine
    :param:db_obj: The dict-like database object to use as reference
    :param:subs: A dict of objkey=dbkey field substitutions
    :param:allow_missing: A list of fields that may not be in db_obj
    :param:comparators: Map of comparator functions to use for certain fields
    """

    if subs is None:
        subs = {}
    if allow_missing is None:
        allow_missing = []
    if comparators is None:
        comparators = {}

    for key in obj.fields:
        if key in allow_missing and not obj.obj_attr_is_set(key):
            continue
        obj_val = getattr(obj, key)
        db_key = subs.get(key, key)
        db_val = db_obj[db_key]
        if isinstance(obj_val, datetime.datetime):
            obj_val = obj_val.replace(tzinfo=None)

        if key in comparators:
            comparator = comparators[key]
            comparator(db_val, obj_val)
        else:
            test.assertEqual(db_val, obj_val)


class _BaseTestCase(test.TestCase):
    def setUp(self):
        super(_BaseTestCase, self).setUp()
        self.remote_object_calls = list()
        self.user_id = 'fake-user'
        self.project_id = 'fake-project'
        self.context = context.RequestContext(self.user_id, self.project_id)

    def compare_obj(self, obj, db_obj, subs=None, allow_missing=None,
                    comparators=None):
        compare_obj(self, obj, db_obj, subs=subs, allow_missing=allow_missing,
                    comparators=comparators)

    def json_comparator(self, expected, obj_val):
        # json-ify an object field for comparison with its db str
        # equivalent
        self.assertEqual(expected, jsonutils.dumps(obj_val))

    def str_comparator(self, expected, obj_val):
        """Compare an object field to a string in the db by performing
        a simple coercion on the object field value.
        """
        self.assertEqual(expected, str(obj_val))

    def assertNotIsInstance(self, obj, cls, msg=None):
        """Python < v2.7 compatibility.  Assert 'not isinstance(obj, cls)."""
        try:
            f = super(_BaseTestCase, self).assertNotIsInstance
        except AttributeError:
            self.assertThat(obj,
                            matchers.Not(matchers.IsInstance(cls)),
                            message=msg or '')
        else:
            f(obj, cls, msg=msg)


class TestFixture(_BaseTestCase):
    def test_fake_indirection_takes_serializer(self):
        ser = mock.MagicMock()
        iapi = fixture.FakeIndirectionAPI(ser)
        ser.serialize_entity.return_value = mock.sentinel.serial
        iapi.object_action(mock.sentinel.context, mock.sentinel.objinst,
                           mock.sentinel.objmethod, (), {})
        ser.serialize_entity.assert_called_once_with(mock.sentinel.context,
                                                     mock.sentinel.objinst)
        ser.deserialize_entity.assert_called_once_with(mock.sentinel.context,
                                                       mock.sentinel.serial)

    def test_indirection_fixture_takes_indirection_api(self):
        iapi = mock.sentinel.iapi
        self.useFixture(fixture.IndirectionFixture(iapi))
        self.assertEqual(iapi, base.VersionedObject.indirection_api)

    def test_indirection_action(self):
        self.useFixture(fixture.IndirectionFixture())
        obj = MyObj(context=self.context)
        with mock.patch.object(base.VersionedObject.indirection_api,
                               'object_action') as mock_action:
            mock_action.return_value = ({}, 'foo')
            obj.marco()
            mock_action.assert_called_once_with(self.context,
                                                obj, 'marco',
                                                (), {})

    def test_indirection_class_action(self):
        self.useFixture(fixture.IndirectionFixture())
        with mock.patch.object(base.VersionedObject.indirection_api,
                               'object_class_action') as mock_caction:
            mock_caction.return_value = 'foo'
            MyObj.query(self.context)
            mock_caction.assert_called_once_with(self.context,
                                                 'MyObj', 'query',
                                                 MyObj.VERSION,
                                                 (), {})

    def test_fake_indirection_serializes_arguments(self):
        ser = mock.MagicMock()
        iapi = fixture.FakeIndirectionAPI(serializer=ser)
        arg1 = mock.MagicMock()
        arg2 = mock.MagicMock()
        iapi.object_action(mock.sentinel.context, mock.sentinel.objinst,
                           mock.sentinel.objmethod, (arg1,), {'foo': arg2})
        ser.serialize_entity.assert_any_call(mock.sentinel.context, arg1)
        ser.serialize_entity.assert_any_call(mock.sentinel.context, arg2)

    def test_get_hashes(self):
        checker = fixture.ObjectVersionChecker()
        hashes = checker.get_hashes()
        # NOTE(danms): If this object's version or hash changes, this needs
        # to change. Otherwise, leave it alone.
        self.assertEqual('1.6-69d0534216ba3bcb601e9be3b534fcd5',
                         hashes['TestSubclassedObject'])

    def test_test_hashes(self):
        checker = fixture.ObjectVersionChecker()
        hashes = checker.get_hashes()
        actual_hash = hashes['TestSubclassedObject']
        hashes['TestSubclassedObject'] = 'foo'
        expected, actual = checker.test_hashes(hashes)
        self.assertEqual(['TestSubclassedObject'], list(expected.keys()))
        self.assertEqual(['TestSubclassedObject'], list(actual.keys()))
        self.assertEqual('foo', expected['TestSubclassedObject'])
        self.assertEqual(actual_hash, actual['TestSubclassedObject'])

    def test_get_dependency_tree(self):
        checker = fixture.ObjectVersionChecker()
        tree = checker.get_dependency_tree()

        # NOTE(danms): If this object's dependencies change, this n eeds
        # to change. Otherwise, leave it alone.
        self.assertEqual({'MyOwnedObject': '1.0'},
                         tree['TestSubclassedObject'])

    def test_test_relationships(self):
        checker = fixture.ObjectVersionChecker()
        tree = checker.get_dependency_tree()
        actual = tree['TestSubclassedObject']
        tree['TestSubclassedObject']['Foo'] = '9.8'
        expected, actual = checker.test_relationships(tree)
        self.assertEqual(['TestSubclassedObject'], list(expected.keys()))
        self.assertEqual(['TestSubclassedObject'], list(actual.keys()))
        self.assertEqual({'MyOwnedObject': '1.0',
                          'Foo': '9.8'},
                         expected['TestSubclassedObject'])
        self.assertEqual({'MyOwnedObject': '1.0'},
                         actual['TestSubclassedObject'])

    def test_test_compatibility(self):
        registry = base.VersionedObjectRegistry()
        checker = fixture.ObjectVersionChecker()
        fake_classes = {mock.sentinel.class_one: [mock.sentinel.impl_one_one,
                                                  mock.sentinel.impl_one_two],
                        mock.sentinel.class_two: [mock.sentinel.impl_two_one,
                                                  mock.sentinel.impl_two_two],
                        }

        @mock.patch.object(checker, '_test_object_compatibility')
        def test(mock_compat):
            checker.test_compatibility_routines()
            mock_compat.assert_has_calls(
                [mock.call(mock.sentinel.impl_one_one),
                 mock.call(mock.sentinel.impl_one_two),
                 mock.call(mock.sentinel.impl_two_one),
                 mock.call(mock.sentinel.impl_two_two)],
                any_order=True)

        with mock.patch.object(registry, '_obj_classes', new=fake_classes):
            test()

    def test_test_compatibility_checks_obj_to_primitive(self):
        fake = mock.MagicMock()
        fake.VERSION = '1.3'

        checker = fixture.ObjectVersionChecker()
        checker._test_object_compatibility(fake)
        fake().obj_to_primitive.assert_has_calls(
            [mock.call(target_version='1.0'),
             mock.call(target_version='1.1'),
             mock.call(target_version='1.2'),
             mock.call(target_version='1.3')])

    def test_test_relationships_in_order(self):
        registry = base.VersionedObjectRegistry()
        checker = fixture.ObjectVersionChecker()
        fake_classes = {mock.sentinel.class_one: [mock.sentinel.impl_one_one,
                                                  mock.sentinel.impl_one_two],
                        mock.sentinel.class_two: [mock.sentinel.impl_two_one,
                                                  mock.sentinel.impl_two_two],
                        }

        @mock.patch.object(checker, '_test_relationships_in_order')
        def test(mock_compat):
            checker.test_relationships_in_order()
            mock_compat.assert_has_calls(
                [mock.call(mock.sentinel.impl_one_one),
                 mock.call(mock.sentinel.impl_one_two),
                 mock.call(mock.sentinel.impl_two_one),
                 mock.call(mock.sentinel.impl_two_two)],
                any_order=True)

        with mock.patch.object(registry, '_obj_classes', new=fake_classes):
            test()

    def test_test_relationships_in_order_good(self):
        fake = mock.MagicMock()
        fake.VERSION = '1.5'
        fake.fields = {'foo': fields.ObjectField('bar')}
        fake.obj_relationships = {'foo': [('1.2', '1.0'),
                                          ('1.3', '1.2')]}

        checker = fixture.ObjectVersionChecker()
        checker._test_relationships_in_order(fake)

    def _test_test_relationships_in_order_bad(self, fake_rels):
        fake = mock.MagicMock()
        fake.VERSION = '1.5'
        fake.fields = {'foo': fields.ObjectField('bar')}
        fake.obj_relationships = fake_rels
        checker = fixture.ObjectVersionChecker()
        self.assertRaises(AssertionError,
                          checker._test_relationships_in_order, fake)

    def test_test_relationships_in_order_bad_my_version(self):
        self._test_test_relationships_in_order_bad(
            {'foo': [('1.4', '1.1'), ('1.3', '1.2')]})

    def test_test_relationships_in_order_bad_child_version(self):
        self._test_test_relationships_in_order_bad(
            {'foo': [('1.2', '1.3'), ('1.3', '1.2')]})

    def test_test_relationships_in_order_bad_both_versions(self):
        self._test_test_relationships_in_order_bad(
            {'foo': [('1.5', '1.4'), ('1.3', '1.2')]})


class _LocalTest(_BaseTestCase):
    def setUp(self):
        super(_LocalTest, self).setUp()
        self.assertIsNone(base.VersionedObject.indirection_api)


class _RemoteTest(_BaseTestCase):
    def setUp(self):
        super(_RemoteTest, self).setUp()
        self.useFixture(fixture.IndirectionFixture())


class _TestObject(object):
    # def test_object_attrs_in_init(self):
    #     # Spot check a few
    #     objects.Instance
    #     objects.InstanceInfoCache
    #     objects.SecurityGroup
    #     # Now check the test one in this file. Should be newest version
    #     self.assertEqual('1.6', objects.MyObj.VERSION)

    def test_hydration_type_error(self):
        primitive = {'versioned_object.name': 'MyObj',
                     'versioned_object.namespace': 'versionedobjects',
                     'versioned_object.version': '1.5',
                     'versioned_object.data': {'foo': 'a'}}
        self.assertRaises(ValueError, MyObj.obj_from_primitive, primitive)

    def test_hydration(self):
        primitive = {'versioned_object.name': 'MyObj',
                     'versioned_object.namespace': 'versionedobjects',
                     'versioned_object.version': '1.5',
                     'versioned_object.data': {'foo': 1}}
        real_method = MyObj._obj_from_primitive

        def _obj_from_primitive(*args):
            return real_method(*args)

        with mock.patch.object(MyObj, '_obj_from_primitive') as ofp:
            ofp.side_effect = _obj_from_primitive
            obj = MyObj.obj_from_primitive(primitive)
            ofp.assert_called_once_with(None, '1.5', primitive)
        self.assertEqual(obj.foo, 1)

    def test_hydration_version_different(self):
        primitive = {'versioned_object.name': 'MyObj',
                     'versioned_object.namespace': 'versionedobjects',
                     'versioned_object.version': '1.2',
                     'versioned_object.data': {'foo': 1}}
        obj = MyObj.obj_from_primitive(primitive)
        self.assertEqual(obj.foo, 1)
        self.assertEqual('1.2', obj.VERSION)

    def test_hydration_bad_ns(self):
        primitive = {'versioned_object.name': 'MyObj',
                     'versioned_object.namespace': 'foo',
                     'versioned_object.version': '1.5',
                     'versioned_object.data': {'foo': 1}}
        self.assertRaises(exception.UnsupportedObjectError,
                          MyObj.obj_from_primitive, primitive)

    def test_hydration_additional_unexpected_stuff(self):
        primitive = {'versioned_object.name': 'MyObj',
                     'versioned_object.namespace': 'versionedobjects',
                     'versioned_object.version': '1.5.1',
                     'versioned_object.data': {
                         'foo': 1,
                         'unexpected_thing': 'foobar'}}
        obj = MyObj.obj_from_primitive(primitive)
        self.assertEqual(1, obj.foo)
        self.assertFalse(hasattr(obj, 'unexpected_thing'))
        # NOTE(danms): If we call obj_from_primitive() directly
        # with a version containing .z, we'll get that version
        # in the resulting object. In reality, when using the
        # serializer, we'll get that snipped off (tested
        # elsewhere)
        self.assertEqual('1.5.1', obj.VERSION)

    def test_dehydration(self):
        expected = {'versioned_object.name': 'MyObj',
                    'versioned_object.namespace': 'versionedobjects',
                    'versioned_object.version': '1.6',
                    'versioned_object.data': {'foo': 1}}
        obj = MyObj(foo=1)
        obj.obj_reset_changes()
        self.assertEqual(obj.obj_to_primitive(), expected)

    def test_object_property(self):
        obj = MyObj(foo=1)
        self.assertEqual(obj.foo, 1)

    def test_object_property_type_error(self):
        obj = MyObj()

        def fail():
            obj.foo = 'a'
        self.assertRaises(ValueError, fail)

    def test_object_dict_syntax(self):
        obj = MyObj(foo=123, bar='bar')
        self.assertEqual(obj['foo'], 123)
        self.assertEqual(sorted(obj.items(), key=lambda x: x[0]),
                         [('bar', 'bar'), ('foo', 123)])
        self.assertEqual(sorted(list(obj.iteritems()), key=lambda x: x[0]),
                         [('bar', 'bar'), ('foo', 123)])

    def test_load(self):
        obj = MyObj()
        self.assertEqual(obj.bar, 'loaded!')

    def test_load_in_base(self):
        @base.VersionedObjectRegistry.register
        class Foo(base.VersionedObject):
            fields = {'foobar': fields.Field(fields.Integer())}
        obj = Foo()
        with self.assertRaisesRegex(NotImplementedError, ".*foobar.*"):
            obj.foobar

    def test_loaded_in_primitive(self):
        obj = MyObj(foo=1)
        obj.obj_reset_changes()
        self.assertEqual(obj.bar, 'loaded!')
        expected = {'versioned_object.name': 'MyObj',
                    'versioned_object.namespace': 'versionedobjects',
                    'versioned_object.version': '1.6',
                    'versioned_object.changes': ['bar'],
                    'versioned_object.data': {'foo': 1,
                                              'bar': 'loaded!'}}
        self.assertEqual(obj.obj_to_primitive(), expected)

    def test_changes_in_primitive(self):
        obj = MyObj(foo=123)
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        primitive = obj.obj_to_primitive()
        self.assertIn('versioned_object.changes', primitive)
        obj2 = MyObj.obj_from_primitive(primitive)
        self.assertEqual(obj2.obj_what_changed(), set(['foo']))
        obj2.obj_reset_changes()
        self.assertEqual(obj2.obj_what_changed(), set())

    def test_obj_class_from_name(self):
        obj = base.VersionedObject.obj_class_from_name('MyObj', '1.5')
        self.assertEqual('1.5', obj.VERSION)

    def test_obj_class_from_name_latest_compatible(self):
        obj = base.VersionedObject.obj_class_from_name('MyObj', '1.1')
        self.assertEqual('1.6', obj.VERSION)

    def test_unknown_objtype(self):
        self.assertRaises(exception.UnsupportedObjectError,
                          base.VersionedObject.obj_class_from_name,
                          'foo', '1.0')

    def test_obj_class_from_name_supported_version(self):
        self.assertRaises(exception.IncompatibleObjectVersion,
                          base.VersionedObject.obj_class_from_name,
                          'MyObj', '1.25')
        try:
            base.VersionedObject.obj_class_from_name('MyObj', '1.25')
        except exception.IncompatibleObjectVersion as error:
            self.assertEqual('1.6', error.kwargs['supported'])

    def test_orphaned_object(self):
        obj = MyObj.query(self.context)
        obj._context = None
        self.assertRaises(exception.OrphanedObjectError,
                          obj._update_test)

    def test_changed_1(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        obj._update_test()
        self.assertEqual(obj.obj_what_changed(), set(['foo', 'bar']))
        self.assertEqual(obj.foo, 123)

    def test_changed_2(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        obj.save()
        self.assertEqual(obj.obj_what_changed(), set([]))
        self.assertEqual(obj.foo, 123)

    def test_changed_3(self):
        obj = MyObj.query(self.context)
        obj.foo = 123
        self.assertEqual(obj.obj_what_changed(), set(['foo']))
        obj.refresh()
        self.assertEqual(obj.obj_what_changed(), set([]))
        self.assertEqual(obj.foo, 321)
        self.assertEqual(obj.bar, 'refreshed')

    def test_changed_4(self):
        obj = MyObj.query(self.context)
        obj.bar = 'something'
        self.assertEqual(obj.obj_what_changed(), set(['bar']))
        obj.modify_save_modify()
        self.assertEqual(obj.obj_what_changed(), set(['foo', 'rel_object']))
        self.assertEqual(obj.foo, 42)
        self.assertEqual(obj.bar, 'meow')
        self.assertIsInstance(obj.rel_object, MyOwnedObject)

    def test_changed_with_sub_object(self):
        @base.VersionedObjectRegistry.register
        class ParentObject(base.VersionedObject):
            fields = {'foo': fields.IntegerField(),
                      'bar': fields.ObjectField('MyObj'),
                      }
        obj = ParentObject()
        self.assertEqual(set(), obj.obj_what_changed())
        obj.foo = 1
        self.assertEqual(set(['foo']), obj.obj_what_changed())
        bar = MyObj()
        obj.bar = bar
        self.assertEqual(set(['foo', 'bar']), obj.obj_what_changed())
        obj.obj_reset_changes()
        self.assertEqual(set(), obj.obj_what_changed())
        bar.foo = 1
        self.assertEqual(set(['bar']), obj.obj_what_changed())

    def test_static_result(self):
        obj = MyObj.query(self.context)
        self.assertEqual(obj.bar, 'bar')
        result = obj.marco()
        self.assertEqual(result, 'polo')

    def test_updates(self):
        obj = MyObj.query(self.context)
        self.assertEqual(obj.foo, 1)
        obj._update_test()
        self.assertEqual(obj.bar, 'updated')

    def test_contains(self):
        obj = MyObj()
        self.assertNotIn('foo', obj)
        obj.foo = 1
        self.assertIn('foo', obj)
        self.assertNotIn('does_not_exist', obj)

    def test_obj_attr_is_set(self):
        obj = MyObj(foo=1)
        self.assertTrue(obj.obj_attr_is_set('foo'))
        self.assertFalse(obj.obj_attr_is_set('bar'))
        self.assertRaises(AttributeError, obj.obj_attr_is_set, 'bang')

    def test_obj_reset_changes_recursive(self):
        obj = MyObj(rel_object=MyOwnedObject(baz=123),
                    rel_objects=[MyOwnedObject(baz=456)])
        self.assertEqual(set(['rel_object', 'rel_objects']),
                         obj.obj_what_changed())
        obj.obj_reset_changes()
        self.assertEqual(set(['rel_object']), obj.obj_what_changed())
        self.assertEqual(set(['baz']), obj.rel_object.obj_what_changed())
        self.assertEqual(set(['baz']), obj.rel_objects[0].obj_what_changed())
        obj.obj_reset_changes(recursive=True, fields=['foo'])
        self.assertEqual(set(['rel_object']), obj.obj_what_changed())
        self.assertEqual(set(['baz']), obj.rel_object.obj_what_changed())
        self.assertEqual(set(['baz']), obj.rel_objects[0].obj_what_changed())
        obj.obj_reset_changes(recursive=True)
        self.assertEqual(set([]), obj.rel_object.obj_what_changed())
        self.assertEqual(set([]), obj.obj_what_changed())

    def test_get(self):
        obj = MyObj(foo=1)
        # Foo has value, should not get the default
        self.assertEqual(obj.get('foo', 2), 1)
        # Foo has value, should return the value without error
        self.assertEqual(obj.get('foo'), 1)
        # Bar is not loaded, so we should get the default
        self.assertEqual(obj.get('bar', 'not-loaded'), 'not-loaded')
        # Bar without a default should lazy-load
        self.assertEqual(obj.get('bar'), 'loaded!')
        # Bar now has a default, but loaded value should be returned
        self.assertEqual(obj.get('bar', 'not-loaded'), 'loaded!')
        # Invalid attribute should raise AttributeError
        self.assertRaises(AttributeError, obj.get, 'nothing')
        # ...even with a default
        self.assertRaises(AttributeError, obj.get, 'nothing', 3)

    def test_object_inheritance(self):
        base_fields = []
        myobj_fields = (['foo', 'bar', 'missing',
                         'readonly', 'rel_object', 'rel_objects'] +
                        base_fields)
        myobj3_fields = ['new_field']
        self.assertTrue(issubclass(TestSubclassedObject, MyObj))
        self.assertEqual(len(myobj_fields), len(MyObj.fields))
        self.assertEqual(set(myobj_fields), set(MyObj.fields.keys()))
        self.assertEqual(len(myobj_fields) + len(myobj3_fields),
                         len(TestSubclassedObject.fields))
        self.assertEqual(set(myobj_fields) | set(myobj3_fields),
                         set(TestSubclassedObject.fields.keys()))

    def test_obj_as_admin(self):
        self.skip('oslo.context does not support elevated()')
        obj = MyObj(context=self.context)

        def fake(*args, **kwargs):
            self.assertTrue(obj._context.is_admin)

        with mock.patch.object(obj, 'obj_reset_changes') as mock_fn:
            mock_fn.side_effect = fake
            with obj.obj_as_admin():
                obj.save()
            self.assertTrue(mock_fn.called)

        self.assertFalse(obj._context.is_admin)

    def test_get_changes(self):
        obj = MyObj()
        self.assertEqual({}, obj.obj_get_changes())
        obj.foo = 123
        self.assertEqual({'foo': 123}, obj.obj_get_changes())
        obj.bar = 'test'
        self.assertEqual({'foo': 123, 'bar': 'test'}, obj.obj_get_changes())
        obj.obj_reset_changes()
        self.assertEqual({}, obj.obj_get_changes())

    def test_obj_fields(self):
        class TestObj(base.VersionedObject):
            fields = {'foo': fields.Field(fields.Integer())}
            obj_extra_fields = ['bar']

            @property
            def bar(self):
                return 'this is bar'

        obj = TestObj()
        self.assertEqual(['foo', 'bar'], obj.obj_fields)

    def test_obj_constructor(self):
        obj = MyObj(context=self.context, foo=123, bar='abc')
        self.assertEqual(123, obj.foo)
        self.assertEqual('abc', obj.bar)
        self.assertEqual(set(['foo', 'bar']), obj.obj_what_changed())

    def test_obj_read_only(self):
        obj = MyObj(context=self.context, foo=123, bar='abc')
        obj.readonly = 1
        self.assertRaises(exception.ReadOnlyFieldError, setattr,
                          obj, 'readonly', 2)

    def test_obj_repr(self):
        obj = MyObj(foo=123)
        self.assertEqual('MyObj(bar=<?>,foo=123,missing=<?>,readonly=<?>,'
                         'rel_object=<?>,rel_objects=<?>)',
                         repr(obj))

    def test_obj_make_obj_compatible(self):
        subobj = MyOwnedObject(baz=1)
        obj = MyObj(rel_object=subobj)
        obj.obj_relationships = {
            'rel_object': [('1.5', '1.1'), ('1.7', '1.2')],
        }
        primitive = obj.obj_to_primitive()['versioned_object.data']
        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            obj._obj_make_obj_compatible(copy.copy(primitive), '1.8',
                                         'rel_object')
            self.assertFalse(mock_compat.called)

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            obj._obj_make_obj_compatible(copy.copy(primitive),
                                         '1.7', 'rel_object')
            mock_compat.assert_called_once_with(
                primitive['rel_object']['versioned_object.data'], '1.2')
            self.assertEqual(
                '1.2', primitive['rel_object']['versioned_object.version'])

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            obj._obj_make_obj_compatible(copy.copy(primitive),
                                         '1.6', 'rel_object')
            mock_compat.assert_called_once_with(
                primitive['rel_object']['versioned_object.data'], '1.1')
            self.assertEqual(
                '1.1', primitive['rel_object']['versioned_object.version'])

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            obj._obj_make_obj_compatible(copy.copy(primitive), '1.5',
                                         'rel_object')
            mock_compat.assert_called_once_with(
                primitive['rel_object']['versioned_object.data'], '1.1')
            self.assertEqual(
                '1.1', primitive['rel_object']['versioned_object.version'])

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_compat:
            _prim = copy.copy(primitive)
            obj._obj_make_obj_compatible(_prim, '1.4', 'rel_object')
            self.assertFalse(mock_compat.called)
            self.assertNotIn('rel_object', _prim)

    def test_obj_make_compatible_hits_sub_objects(self):
        subobj = MyOwnedObject(baz=1)
        obj = MyObj(foo=123, rel_object=subobj)
        obj.obj_relationships = {'rel_object': [('1.0', '1.0')]}
        with mock.patch.object(obj, '_obj_make_obj_compatible') as mock_compat:
            obj.obj_make_compatible({'rel_object': 'foo'}, '1.10')
            mock_compat.assert_called_once_with({'rel_object': 'foo'}, '1.10',
                                                'rel_object')

    def test_obj_make_compatible_skips_unset_sub_objects(self):
        obj = MyObj(foo=123)
        obj.obj_relationships = {'rel_object': [('1.0', '1.0')]}
        with mock.patch.object(obj, '_obj_make_obj_compatible') as mock_compat:
            obj.obj_make_compatible({'rel_object': 'foo'}, '1.10')
            self.assertFalse(mock_compat.called)

    def test_obj_make_compatible_complains_about_missing_rules(self):
        subobj = MyOwnedObject(baz=1)
        obj = MyObj(foo=123, rel_object=subobj)
        obj.obj_relationships = {}
        self.assertRaises(exception.ObjectActionError,
                          obj.obj_make_compatible, {}, '1.0')

    def test_obj_make_compatible_handles_list_of_objects(self):
        subobj = MyOwnedObject(baz=1)
        obj = MyObj(rel_objects=[subobj])
        obj.obj_relationships = {'rel_objects': [('1.0', '1.123')]}

        def fake_make_compat(primitive, version):
            self.assertEqual('1.123', version)
            self.assertIn('baz', primitive)

        with mock.patch.object(subobj, 'obj_make_compatible') as mock_mc:
            mock_mc.side_effect = fake_make_compat
            obj.obj_to_primitive('1.0')
            self.assertTrue(mock_mc.called)

    def test_obj_make_compatible_on_list_base(self):
        @base.VersionedObjectRegistry.register_if(False)
        class MyList(base.ObjectListBase, base.VersionedObject):
            VERSION = '1.1'
            fields = {'objects': fields.ListOfObjectsField('MyObj')}

        childobj = MyObj(foo=1)
        listobj = MyList(objects=[childobj])
        with mock.patch.object(childobj, 'obj_make_compatible') as mock_compat:
            listobj.obj_to_primitive(target_version='1.0')
            mock_compat.assert_called_once_with({'foo': 1}, '1.0')

    def test_comparable_objects(self):
        obj1 = MyComparableObj(foo=1)
        obj2 = MyComparableObj(foo=1)
        obj3 = MyComparableObj(foo=2)
        self.assertTrue(obj1 == obj2)
        self.assertFalse(obj1 == obj3)


class TestObject(_LocalTest, _TestObject):
    def test_set_defaults(self):
        obj = MyObj()
        obj.obj_set_defaults('foo')
        self.assertTrue(obj.obj_attr_is_set('foo'))
        self.assertEqual(1, obj.foo)

    def test_set_defaults_no_default(self):
        obj = MyObj()
        self.assertRaises(exception.ObjectActionError,
                          obj.obj_set_defaults, 'bar')

    def test_set_all_defaults(self):
        obj = MyObj()
        obj.obj_set_defaults()
        self.assertEqual(set(['foo']), obj.obj_what_changed())
        self.assertEqual(1, obj.foo)

    def test_set_defaults_not_overwrite(self):
        # NOTE(danms): deleted defaults to False, so verify that it does
        # not get reset by obj_set_defaults()
        obj = MyObj(deleted=True)
        obj.obj_set_defaults()
        self.assertEqual(1, obj.foo)
        self.assertTrue(obj.deleted)


class TestRemoteObject(_RemoteTest, _TestObject):
    def test_major_version_mismatch(self):
        MyObj2.VERSION = '2.0'
        self.assertRaises(exception.IncompatibleObjectVersion,
                          MyObj2.query, self.context)

    def test_minor_version_greater(self):
        MyObj2.VERSION = '1.7'
        self.assertRaises(exception.IncompatibleObjectVersion,
                          MyObj2.query, self.context)

    def test_minor_version_less(self):
        MyObj2.VERSION = '1.2'
        obj = MyObj2.query(self.context)
        self.assertEqual(obj.bar, 'bar')

    def test_compat(self):
        MyObj2.VERSION = '1.1'
        obj = MyObj2.query(self.context)
        self.assertEqual('oldbar', obj.bar)

    def test_revision_ignored(self):
        MyObj2.VERSION = '1.1.456'
        obj = MyObj2.query(self.context)
        self.assertEqual('bar', obj.bar)


class TestObjectListBase(test.TestCase):
    def test_list_like_operations(self):
        @base.VersionedObjectRegistry.register
        class MyElement(base.VersionedObject):
            fields = {'foo': fields.IntegerField()}

            def __init__(self, foo):
                super(MyElement, self).__init__()
                self.foo = foo

        class Foo(base.ObjectListBase, base.VersionedObject):
            fields = {'objects': fields.ListOfObjectsField('MyElement')}

        objlist = Foo(context='foo',
                      objects=[MyElement(1), MyElement(2), MyElement(3)])
        self.assertEqual(list(objlist), objlist.objects)
        self.assertEqual(len(objlist), 3)
        self.assertIn(objlist.objects[0], objlist)
        self.assertEqual(list(objlist[:1]), [objlist.objects[0]])
        self.assertEqual(objlist[:1]._context, 'foo')
        self.assertEqual(objlist[2], objlist.objects[2])
        self.assertEqual(objlist.count(objlist.objects[0]), 1)
        self.assertEqual(objlist.index(objlist.objects[1]), 1)
        objlist.sort(key=lambda x: x.foo, reverse=True)
        self.assertEqual([3, 2, 1],
                         [x.foo for x in objlist])

    def test_serialization(self):
        @base.VersionedObjectRegistry.register
        class Foo(base.ObjectListBase, base.VersionedObject):
            fields = {'objects': fields.ListOfObjectsField('Bar')}

        @base.VersionedObjectRegistry.register
        class Bar(base.VersionedObject):
            fields = {'foo': fields.Field(fields.String())}

        obj = Foo(objects=[])
        for i in 'abc':
            bar = Bar(foo=i)
            obj.objects.append(bar)

        obj2 = base.VersionedObject.obj_from_primitive(obj.obj_to_primitive())
        self.assertFalse(obj is obj2)
        self.assertEqual([x.foo for x in obj],
                         [y.foo for y in obj2])

    def _test_object_list_version_mappings(self, list_obj_class):
        # Figure out what sort of object this list is for
        list_field = list_obj_class.fields['objects']
        item_obj_field = list_field._type._element_type
        item_obj_name = item_obj_field._type._obj_name

        # Look through all object classes of this type and make sure that
        # the versions we find are covered by the parent list class
        obj_classes = base.VersionedObjectRegistry.obj_classes()[item_obj_name]
        for item_class in obj_classes:
            if is_test_object(item_class):
                continue
            self.assertIn(
                item_class.VERSION,
                list_obj_class.child_versions.values(),
                'Version mapping is incomplete for %s' % (
                    list_obj_class.__name__))

    def test_object_version_mappings(self):
        self.skip('this needs to be generalized')
        # Find all object list classes and make sure that they at least handle
        # all the current object versions
        for obj_classes in base.VersionedObjectRegistry.obj_classes().values():
            for obj_class in obj_classes:
                if issubclass(obj_class, base.ObjectListBase):
                    self._test_object_list_version_mappings(obj_class)

    def test_list_changes(self):
        @base.VersionedObjectRegistry.register
        class Foo(base.ObjectListBase, base.VersionedObject):
            fields = {'objects': fields.ListOfObjectsField('Bar')}

        @base.VersionedObjectRegistry.register
        class Bar(base.VersionedObject):
            fields = {'foo': fields.StringField()}

        obj = Foo(objects=[])
        self.assertEqual(set(['objects']), obj.obj_what_changed())
        obj.objects.append(Bar(foo='test'))
        self.assertEqual(set(['objects']), obj.obj_what_changed())
        obj.obj_reset_changes()
        # This should still look dirty because the child is dirty
        self.assertEqual(set(['objects']), obj.obj_what_changed())
        obj.objects[0].obj_reset_changes()
        # This should now look clean because the child is clean
        self.assertEqual(set(), obj.obj_what_changed())

    def test_initialize_objects(self):
        class Foo(base.ObjectListBase, base.VersionedObject):
            fields = {'objects': fields.ListOfObjectsField('Bar')}

        class Bar(base.VersionedObject):
            fields = {'foo': fields.StringField()}

        obj = Foo()
        self.assertEqual([], obj.objects)
        self.assertEqual(set(), obj.obj_what_changed())

    def test_obj_repr(self):
        @base.VersionedObjectRegistry.register
        class Foo(base.ObjectListBase, base.VersionedObject):
            fields = {'objects': fields.ListOfObjectsField('Bar')}

        @base.VersionedObjectRegistry.register
        class Bar(base.VersionedObject):
            fields = {'uuid': fields.StringField()}

        obj = Foo(objects=[Bar(uuid='fake-uuid')])
        self.assertEqual('Foo(objects=[Bar(fake-uuid)])', repr(obj))


class TestObjectSerializer(_BaseTestCase):
    def test_serialize_entity_primitive(self):
        ser = base.VersionedObjectSerializer()
        for thing in (1, 'foo', [1, 2], {'foo': 'bar'}):
            self.assertEqual(thing, ser.serialize_entity(None, thing))

    def test_deserialize_entity_primitive(self):
        ser = base.VersionedObjectSerializer()
        for thing in (1, 'foo', [1, 2], {'foo': 'bar'}):
            self.assertEqual(thing, ser.deserialize_entity(None, thing))

    def test_serialize_set_to_list(self):
        ser = base.VersionedObjectSerializer()
        self.assertEqual([1, 2], ser.serialize_entity(None, set([1, 2])))

    @mock.patch('oslo_versionedobjects.base.VersionedObject.indirection_api')
    def _test_deserialize_entity_newer(self, obj_version, backported_to,
                                       mock_iapi,
                                       my_version='1.6'):
        ser = base.VersionedObjectSerializer()
        mock_iapi.object_backport.return_value = 'backported'

        @base.VersionedObjectRegistry.register
        class MyTestObj(MyObj):
            VERSION = my_version

        obj = MyTestObj()
        obj.VERSION = obj_version
        primitive = obj.obj_to_primitive()
        result = ser.deserialize_entity(self.context, primitive)
        if backported_to is None:
            self.assertFalse(mock_iapi.object_backport.called)
        else:
            self.assertEqual('backported', result)
            mock_iapi.object_backport.assert_called_with(self.context,
                                                         primitive,
                                                         backported_to)

    def test_deserialize_entity_newer_version_backports(self):
        self._test_deserialize_entity_newer('1.25', '1.6')

    def test_deserialize_entity_newer_revision_does_not_backport_zero(self):
        self._test_deserialize_entity_newer('1.6.0', None)

    def test_deserialize_entity_newer_revision_does_not_backport(self):
        self._test_deserialize_entity_newer('1.6.1', None)

    def test_deserialize_entity_newer_version_passes_revision(self):
        self._test_deserialize_entity_newer('1.7', '1.6.1', my_version='1.6.1')

    def test_deserialize_dot_z_with_extra_stuff(self):
        primitive = {'versioned_object.name': 'MyObj',
                     'versioned_object.namespace': 'versionedobjects',
                     'versioned_object.version': '1.6.1',
                     'versioned_object.data': {
                         'foo': 1,
                         'unexpected_thing': 'foobar'}}
        ser = base.VersionedObjectSerializer()
        obj = ser.deserialize_entity(self.context, primitive)
        self.assertEqual(1, obj.foo)
        self.assertFalse(hasattr(obj, 'unexpected_thing'))
        # NOTE(danms): The serializer is where the logic lives that
        # avoids backports for cases where only a .z difference in
        # the received object version is detected. As a result, we
        # end up with a version of what we expected, effectively the
        # .0 of the object.
        self.assertEqual('1.6', obj.VERSION)

    def test_object_serialization(self):
        ser = base.VersionedObjectSerializer()
        obj = MyObj()
        primitive = ser.serialize_entity(self.context, obj)
        self.assertIn('versioned_object.name', primitive)
        obj2 = ser.deserialize_entity(self.context, primitive)
        self.assertIsInstance(obj2, MyObj)
        self.assertEqual(self.context, obj2._context)

    def test_object_serialization_iterables(self):
        ser = base.VersionedObjectSerializer()
        obj = MyObj()
        for iterable in (list, tuple, set):
            thing = iterable([obj])
            primitive = ser.serialize_entity(self.context, thing)
            self.assertEqual(1, len(primitive))
            for item in primitive:
                self.assertNotIsInstance(item, base.VersionedObject)
            thing2 = ser.deserialize_entity(self.context, primitive)
            self.assertEqual(1, len(thing2))
            for item in thing2:
                self.assertIsInstance(item, MyObj)
        # dict case
        thing = {'key': obj}
        primitive = ser.serialize_entity(self.context, thing)
        self.assertEqual(1, len(primitive))
        for item in six.itervalues(primitive):
            self.assertNotIsInstance(item, base.VersionedObject)
        thing2 = ser.deserialize_entity(self.context, primitive)
        self.assertEqual(1, len(thing2))
        for item in six.itervalues(thing2):
            self.assertIsInstance(item, MyObj)

        # object-action updates dict case
        thing = {'foo': obj.obj_to_primitive()}
        primitive = ser.serialize_entity(self.context, thing)
        self.assertEqual(thing, primitive)
        thing2 = ser.deserialize_entity(self.context, thing)
        self.assertIsInstance(thing2['foo'], base.VersionedObject)

    def test_serializer_subclass_namespace(self):
        @base.VersionedObjectRegistry.register
        class MyNSObj(base.VersionedObject):
            OBJ_SERIAL_NAMESPACE = 'foo'
            fields = {'foo': fields.IntegerField()}

        class MySerializer(base.VersionedObjectSerializer):
            OBJ_BASE_CLASS = MyNSObj

        ser = MySerializer()
        obj = MyNSObj(foo=123)
        obj2 = ser.deserialize_entity(None, ser.serialize_entity(None, obj))
        self.assertIsInstance(obj2, MyNSObj)
        self.assertEqual(obj.foo, obj2.foo)

    def test_serializer_subclass_namespace_mismatch(self):
        @base.VersionedObjectRegistry.register
        class MyNSObj(base.VersionedObject):
            OBJ_SERIAL_NAMESPACE = 'foo'
            fields = {'foo': fields.IntegerField()}

        class MySerializer(base.VersionedObjectSerializer):
            OBJ_BASE_CLASS = MyNSObj

        myser = MySerializer()
        voser = base.VersionedObjectSerializer()
        obj = MyObj(foo=123)
        obj2 = myser.deserialize_entity(None,
                                        voser.serialize_entity(None, obj))

        # NOTE(danms): The new serializer should have ignored the objects
        # serialized by the base serializer, so obj2 here should be a dict
        # primitive and not a hydrated object
        self.assertNotIsInstance(obj2, MyNSObj)
        self.assertIn('versioned_object.name', obj2)

    def test_serializer_subclass_base_object_indirection(self):
        @base.VersionedObjectRegistry.register
        class MyNSObj(base.VersionedObject):
            OBJ_SERIAL_NAMESPACE = 'foo'
            fields = {'foo': fields.IntegerField()}
            indirection_api = mock.MagicMock()

        class MySerializer(base.VersionedObjectSerializer):
            OBJ_BASE_CLASS = MyNSObj

        ser = MySerializer()
        prim = MyNSObj(foo=1).obj_to_primitive()
        prim['foo.version'] = '2.0'
        ser.deserialize_entity(mock.sentinel.context, prim)
        MyNSObj.indirection_api.object_backport.assert_called_once_with(
            mock.sentinel.context, prim, '1.0')


class TestNamespaceCompatibility(test.TestCase):
    def setUp(self):
        super(TestNamespaceCompatibility, self).setUp()

        @base.VersionedObjectRegistry.register_if(False)
        class TestObject(base.VersionedObject):
            OBJ_SERIAL_NAMESPACE = 'foo'
            OBJ_PROJECT_NAMESPACE = 'tests'

        self.test_class = TestObject

    def test_obj_primitive_key(self):
        self.assertEqual('foo.data',
                         self.test_class._obj_primitive_key('data'))

    def test_obj_primitive_field(self):
        primitive = {
            'foo.data': mock.sentinel.data,
        }
        self.assertEqual(mock.sentinel.data,
                         self.test_class._obj_primitive_field(primitive,
                                                              'data'))

    def test_obj_primitive_field_namespace(self):
        primitive = {
            'foo.name': 'TestObject',
            'foo.namespace': 'tests',
            'foo.version': '1.0',
            'foo.data': {},
        }
        with mock.patch.object(self.test_class, 'obj_class_from_name'):
            self.test_class.obj_from_primitive(primitive)

    def test_obj_primitive_field_namespace_wrong(self):
        primitive = {
            'foo.name': 'TestObject',
            'foo.namespace': 'wrong',
            'foo.version': '1.0',
            'foo.data': {},
        }
        self.assertRaises(exception.UnsupportedObjectError,
                          self.test_class.obj_from_primitive, primitive)
